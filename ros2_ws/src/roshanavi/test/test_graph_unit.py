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


class _FakeRuntime:
    """collect() inputs; ``bad`` topics raise like rclpy does for over-long names."""

    def __init__(self, topics, bad=()):
        self.topics, self.bad = topics, set(bad)

    def topic_names_and_types(self):
        return list(self.topics.items())

    def _info(self, topic):
        if topic in self.bad:
            from rclpy.exceptions import InvalidTopicNameException
            raise InvalidTopicNameException(topic, 'topic length should not exceed', 0)
        return []

    publishers_info = subscriptions_info = _info

    def node_names_and_namespaces(self):
        return []

    def service_names_and_types(self):
        return []


def test_collect_skips_a_topic_rclpy_cannot_query():
    from roshanavi.graph import collect
    raw = collect(_FakeRuntime({'/ok': ['std_msgs/msg/String'], '/bad': ['std_msgs/msg/String']},
                               bad={'/bad'}))
    assert list(raw.topics) == ['/ok'] and set(raw.publishers) == {'/ok'}
    assert set(raw.subscribers) == {'/ok'}


def test_rmw_companion_topics_are_never_listed():
    import threading

    from roshanavi.ros_runtime import RosRuntime, is_rmw_internal_topic
    assert is_rmw_internal_topic('/audio/_buf_cpu')
    assert is_rmw_internal_topic('/audio/_buf_cpu/_buf_cpu')
    assert not is_rmw_internal_topic('/audio') and not is_rmw_internal_topic('/my_buf_cpu')

    class Node:
        def get_topic_names_and_types(self):
            return [('/audio', ['a/msg/A']), ('/audio/_buf_cpu', ['a/msg/A']),
                    ('/audio/_buf_cpu/_buf_cpu', ['a/msg/A'])]

    runtime = RosRuntime.__new__(RosRuntime)
    runtime._node, runtime._lock = Node(), threading.Lock()
    assert runtime.topic_names_and_types() == [('/audio', ['a/msg/A'])]
