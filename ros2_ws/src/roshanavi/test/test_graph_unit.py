from roshanavi.graph import Endpoint, RawGraph, build_snapshot, snapshot_hash, topic_is_live

QOS = {'reliability': 'reliable', 'durability': 'volatile', 'history': 'keep_last', 'depth': 10}


def raw():
    return RawGraph(
        nodes=[('talker', '/'), ('listener', '/'), ('roshanavi', '/')],
        topics={'/chatter': ['std_msgs/msg/String'], '/only_self_sub': ['std_msgs/msg/String'],
                '/injected': ['std_msgs/msg/String']},
        publishers={'/chatter': [Endpoint('/talker', QOS)], '/only_self_sub': [],
                    '/injected': [Endpoint('/roshanavi', QOS)]},
        subscribers={'/chatter': [Endpoint('/listener', QOS), Endpoint('/roshanavi', QOS)],
                     '/only_self_sub': [Endpoint('/roshanavi', QOS)], '/injected': []},
    )


def test_topic_liveness_ignores_own_subscriptions():
    g = raw()
    assert topic_is_live(g, '/chatter')
    assert topic_is_live(g, '/injected')
    assert not topic_is_live(g, '/only_self_sub')


def test_snapshot_excludes_self_by_default():
    snap = build_snapshot(raw())
    assert [n['id'] for n in snap['nodes']] == ['/listener', '/talker']
    assert [t['name'] for t in snap['topics']] == ['/chatter', '/injected']
    assert {(e['node'], e['topic'], e['dir']) for e in snap['edges']} == {
        ('/talker', '/chatter', 'pub'), ('/listener', '/chatter', 'sub')}
    assert snap['edges'][0]['qos'] == QOS


def test_snapshot_show_self():
    snap = build_snapshot(raw(), show_self=True)
    assert '/roshanavi' in [n['id'] for n in snap['nodes']]
    assert ('/roshanavi', '/injected', 'pub') in {
        (e['node'], e['topic'], e['dir']) for e in snap['edges']}


def test_hash_changes_only_on_content_change():
    assert snapshot_hash(build_snapshot(raw())) == snapshot_hash(build_snapshot(raw()))
    assert snapshot_hash(build_snapshot(raw())) != snapshot_hash(build_snapshot(RawGraph()))


def test_nodes_have_role_and_snapshot_has_diagnostics():
    snap = build_snapshot(raw())
    assert {n['role'] for n in snap['nodes']} == {'other'}
    assert snap['diagnostics'] == []  # /injected has no visible endpoints


def test_running_inject_job_becomes_dummy_source():
    jobs = [{'id': 'abc', 'mode': 'periodic', 'topic': '/injected', 'state': 'running',
             'qos': {'reliability': 'best_effort'}},
            {'id': 'old', 'mode': 'once', 'topic': '/injected', 'state': 'done'},
            {'id': 'bag', 'mode': 'bag', 'topic': None, 'state': 'running'}]
    snap = build_snapshot(raw(), jobs=jobs)
    dummies = [n for n in snap['nodes'] if n['role'] == 'dummy']
    assert dummies == [{'id': 'dummy:abc', 'name': 'inject periodic', 'namespace': '',
                        'role': 'dummy', 'job_id': 'abc'}]
    edge = next(e for e in snap['edges'] if e['node'] == 'dummy:abc')
    assert (edge['topic'], edge['dir'], edge['qos']['reliability']) == (
        '/injected', 'pub', 'best_effort')
    assert [d['code'] for d in snap['diagnostics']] == ['no_subscriber']
    assert snapshot_hash(snap) != snapshot_hash(build_snapshot(raw()))
