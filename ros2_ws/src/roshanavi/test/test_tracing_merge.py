"""Trace results into traffic entries, 処理が追いついていない, unsupported nodes (pure)."""

from roshanavi.tracing import merge


def win(hz_recv, hz_processed, cb=None):
    return {'hz_recv': hz_recv, 'hz_processed': hz_processed, 'cb_ms': cb}


def snap(subs=(), pubs=(), nodes=()):
    return {'subscriptions': list(subs), 'publishers': list(pubs), 'nodes': list(nodes),
            'unknown_pids': []}


def trace_sub(node, topic, w5, lang='cpp', intra=False):
    return {'node': node, 'topic': topic, 'pid': 1, 'lang': lang, 'intra': intra,
            'symbol': 'cb', 'windows': {'1': w5, '5': w5, '10': w5}}


def entry(subs, pubs=(), topic='/chatter'):
    return {'topic': topic, 'status': 'ok', 'avg_size': 10.0, 'hz': 10.0,
            'subscribers': list(subs), 'publishers': list(pubs)}


def theo(node, hz=10.0, basis='theoretical'):
    return {'node': node, 'hz': hz, 'bps': 100.0, 'basis': basis,
            'delivered': basis != 'not_delivered', 'sources': ['/talker']}


def test_covered_subscriber_becomes_measured_and_keeps_the_theoretical_value():
    cb = {'avg': 2.0, 'p95': 3.0, 'max': 4.0}
    out = merge.apply_trace([entry([theo('/listener'), theo('/other')])],
                            snap([trace_sub('/listener', '/chatter', win(9.9, 9.9, cb))]), 5)
    measured, other = out[0]['subscribers']
    assert measured['basis'] == 'measured' and measured['hz'] == 9.9
    assert measured['hz_expected'] == 10.0 and measured['hz_processed'] == 9.9
    assert measured['cb_ms'] == cb and measured['bps'] == 99.0 and measured['behind'] is None
    assert other == theo('/other')


def test_slow_callback_is_behind_against_what_the_senders_sent():
    cb = {'avg': 200.0, 'p95': 201.0, 'max': 205.0}
    out = merge.apply_trace([entry([theo('/slow')])],
                            snap([trace_sub('/slow', '/chatter', win(5.0, 5.0, cb))]), 5)
    sub = out[0]['subscribers'][0]
    assert sub['behind'] == {'incoming_hz': 10.0, 'processed_hz': 5.0, 'basis': 'sent',
                             'cb_avg_ms': 200.0}
    diags = merge.behind_list(out)
    assert diags == [{'code': 'processing_behind', 'node': '/slow', 'topic': '/chatter',
                      'incoming_hz': 10.0, 'processed_hz': 5.0, 'basis': 'sent',
                      'cb_avg_ms': 200.0}]


def test_received_more_than_processed_is_behind_on_received():
    assert merge.behind(None, 20.0, 12.0) == {'incoming_hz': 20.0, 'processed_hz': 12.0,
                                              'basis': 'received'}
    assert merge.behind(10.0, 10.0, 9.6) is None   # within 10 %
    assert merge.behind(0.3, 0.3, 0.0) is None     # too slow to judge
    assert merge.behind(10.0, 10.0, None) is None  # rclpy: not measurable


def test_rclpy_subscriber_is_measured_for_receive_only():
    out = merge.apply_trace([entry([theo('/py')])],
                            snap([trace_sub('/py', '/chatter', win(10.0, None), lang='py')]), 5)
    sub = out[0]['subscribers'][0]
    assert sub['basis'] == 'measured' and sub['lang'] == 'py'
    assert sub['hz_processed'] is None and sub['cb_ms'] is None and sub['behind'] is None


def test_warming_up_keeps_the_theoretical_basis():
    out = merge.apply_trace([entry([theo('/l')])],
                            snap([trace_sub('/l', '/chatter', win(None, None))]), 1)
    assert out[0]['subscribers'][0]['basis'] == 'theoretical'


def test_not_delivered_stays_not_delivered_but_gets_trace_values():
    out = merge.apply_trace([entry([theo('/l', 0.0, 'not_delivered')])],
                            snap([trace_sub('/l', '/chatter', win(0.0, 0.0))]), 5)
    sub = out[0]['subscribers'][0]
    assert sub['basis'] == 'not_delivered' and sub['hz_recv'] == 0.0


def test_publishers_get_the_traced_rate_and_no_snapshot_is_a_copy():
    pubs = [{'node': '/talker', 'hz': 10.0, 'bps': 1.0, 'basis': 'measured'}]
    traced = {'node': '/talker', 'topic': '/chatter', 'pid': 1,
              'windows': {'5': {'hz': 9.8}}}
    out = merge.apply_trace([entry([], pubs)], snap(pubs=[traced]), 5)
    assert out[0]['publishers'][0]['hz_traced'] == 9.8
    original = [entry([theo('/l')])]
    assert merge.apply_trace(original, None, 5) == original


def test_unsupported_nodes_with_reasons():
    graph = [{'id': '/cpp'}, {'id': '/py'}, {'id': '/old'}, {'id': '/remote'},
             {'id': '/intra'}, {'id': '/roshanavi'}, {'id': 'dummy:j1', 'job_id': 'j1'}]
    trace = snap(subs=[trace_sub('/intra', '/x', win(None, 5.0), intra=True)],
                 nodes=[{'node': '/cpp', 'lang': 'cpp'}, {'node': '/py', 'lang': 'py'},
                        {'node': '/intra', 'lang': 'cpp'}])
    pids = {'/old': 42, '/remote': None}
    result = merge.unsupported_nodes(graph, trace, pids, trace_started=1000.0,
                                     created_at=lambda pid: 900.0)
    assert result == [
        {'node': '/intra', 'reason': 'intra_process', 'pid': None},
        {'node': '/old', 'reason': 'restart_needed', 'pid': 42},
        {'node': '/py', 'reason': 'rclpy', 'pid': None},
        {'node': '/remote', 'reason': 'not_traced', 'pid': None},
    ]
    later = merge.unsupported_nodes([{'id': '/old'}], trace, pids, 1000.0, lambda pid: 1100.0)
    assert later == [{'node': '/old', 'reason': 'not_traced', 'pid': 42}]


def trace_pub(node, topic, hz):
    return {'node': node, 'topic': topic, 'pid': 1, 'windows': {'5': {'hz': hz}}}


def heavy_entry(pubs, subs=()):
    return {'topic': '/cam', 'type': 'sensor_msgs/msg/Image', 'status': 'not_monitored',
            'monitored': False, 'avg_size': 0.0, 'hz': 0.0, 'heavy': True,
            'publishers': list(pubs), 'subscribers': list(subs)}


def off_pub(node):
    return {'node': node, 'hz': None, 'bps': None, 'basis': 'not_monitored'}


def test_heavy_topic_shows_the_traced_send_rate_without_bandwidth():
    # #61: with 詳細計測モード the Hz of a topic nobody measures comes from the trace
    out = merge.apply_trace([heavy_entry([off_pub('/cam_a'), off_pub('/cam_b')])],
                            snap(pubs=[trace_pub('/cam_a', '/cam', 10.0),
                                       trace_pub('/cam_b', '/cam', 20.0)]), 5)[0]
    a, b = out['publishers']
    assert (a['hz'], a['basis'], a['bps'], a['hz_traced']) == (10.0, 'traced', None, 10.0)
    assert b['hz'] == 20.0
    assert out['hz_traced'] == 30.0  # the topic's send rate: the sum over the publishers
    assert out['status'] == 'not_monitored'  # still not measured by subscription


def test_heavy_topic_with_an_untraced_publisher_has_no_topic_rate():
    out = merge.apply_trace([heavy_entry([off_pub('/cam_a'), off_pub('/other')])],
                            snap(pubs=[trace_pub('/cam_a', '/cam', 10.0)]), 5)[0]
    assert out['publishers'][0]['basis'] == 'traced'
    assert out['publishers'][1]['basis'] == 'not_monitored' and out['publishers'][1]['hz'] is None
    assert out['hz_traced'] is None


def test_heavy_topic_subscriber_gets_the_received_rate_from_the_trace():
    sub = {'node': '/viewer', 'hz': None, 'bps': None, 'basis': 'not_monitored',
           'delivered': True, 'sources': ['/cam_a']}
    out = merge.apply_trace([heavy_entry([off_pub('/cam_a')], [sub])],
                            snap(subs=[trace_sub('/viewer', '/cam', win(9.5, 9.5))]), 5)[0]
    assert out['subscribers'][0]['basis'] == 'measured'
    assert out['subscribers'][0]['hz'] == 9.5 and out['subscribers'][0]['bps'] is None


def test_monitored_topics_keep_their_own_rows_and_get_no_topic_rate():
    pubs = [{'node': '/talker', 'hz': 10.0, 'bps': 1.0, 'basis': 'measured'}]
    out = merge.apply_trace([entry([], pubs)], snap(pubs=[trace_pub('/talker', '/chatter', 9.8)]), 5)[0]
    assert out['publishers'][0]['basis'] == 'measured' and out['publishers'][0]['hz'] == 10.0
    assert 'hz_traced' not in out
