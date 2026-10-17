"""rclpy integration: real publishers/subscribers in-process (separate contexts)."""

import time

import pytest
from rclpy.qos import QoSProfile, ReliabilityPolicy
from std_msgs.msg import Int32, String

from conftest import wait_for
from roshanavi.jobs import InjectSpec


def _traffic_entry(lab, topic):
    return next((t for t in lab.traffic.snapshot() if t['topic'] == topic), None)


def test_traffic_detects_rate(lab, helper):
    helper.periodic_publisher(String, '/tl_hz', 10.0, lambda i: String(data=f'm{i}'))

    def steady():
        entry = _traffic_entry(lab, '/tl_hz')
        return entry if entry and entry['total_count'] >= 15 else None
    entry = wait_for(steady, timeout=15.0)
    assert entry['status'] == 'ok'
    assert entry['type'] == 'std_msgs/msg/String'
    assert entry['hz'] == pytest.approx(10.0, rel=0.25)
    assert entry['avg_size'] > 0
    assert entry['last_seen'] is not None


def test_traffic_uses_source_timestamps_and_sees_no_drops(lab, helper):
    helper.periodic_publisher(String, '/tl_src', 10.0, lambda i: String(data=f'm{i}'))

    def steady():
        entry = _traffic_entry(lab, '/tl_src')
        return entry if entry and entry['total_count'] >= 20 else None
    entry = wait_for(steady, timeout=20.0)
    assert entry['hz_basis'] == 'source'
    assert entry['hz'] == pytest.approx(10.0, rel=0.15)
    assert entry['dropped'] == 0
    assert entry['latency_ms'] is not None and entry['latency_ms'] < 100


def test_traffic_best_effort_publisher(lab, helper):
    qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.BEST_EFFORT)
    helper.periodic_publisher(Int32, '/tl_be', 20.0, lambda i: Int32(data=i), qos=qos)
    wait_for(lambda: (_traffic_entry(lab, '/tl_be') or {}).get('total_count', 0) >= 10,
             timeout=15.0)


def test_graph_shows_helper_edges(lab, helper):
    helper.periodic_publisher(String, '/tl_graph', 5.0, lambda i: String(data='x'))
    helper.collector(String, '/tl_graph')
    node_id = '/' + helper.node.get_name()

    def has_edges():
        snap, _ = lab.graph.snapshot()
        dirs = {e['dir'] for e in snap['edges'] if e['topic'] == '/tl_graph'
                and e['node'] == node_id}
        return dirs == {'pub', 'sub'}
    wait_for(has_edges, timeout=15.0)
    snap, _ = lab.graph.snapshot()
    assert not any(n['id'].startswith('/roshanavi') for n in snap['nodes'])


def _wait_subscriber_visible(lab, topic):
    wait_for(lambda: lab.runtime.subscriptions_info(topic), timeout=15.0)


def test_injector_periodic_delivers_exact_count(lab, helper):
    received = helper.collector(String, '/tl_inject')
    _wait_subscriber_visible(lab, '/tl_inject')
    job = lab.injector.start(InjectSpec(mode='periodic', topic='/tl_inject',
                                        type='std_msgs/msg/String',
                                        payload={'data': 'hello ${i}'}, rate_hz=20.0, count=10))
    wait_for(lambda: lab.injector.get(job['id'])['state'] == 'done', timeout=10.0)
    wait_for(lambda: len(received) >= 10, timeout=5.0)
    assert [m.data for m in received] == [f'hello {i}' for i in range(10)]
    assert lab.injector.get(job['id'])['sent'] == 10


def test_injector_once(lab, helper):
    received = helper.collector(Int32, '/tl_once')
    _wait_subscriber_visible(lab, '/tl_once')
    job = lab.injector.start(InjectSpec(mode='once', topic='/tl_once', type='std_msgs/msg/Int32',
                                        payload={'data': 42}))
    wait_for(lambda: received, timeout=5.0)
    assert received[0].data == 42
    wait_for(lambda: lab.injector.get(job['id'])['state'] == 'done', timeout=5.0)
    assert lab.injector.get(job['id'])['sent'] == 1


def test_injector_stream_jsonl(lab, helper, data_dir):
    (data_dir / 's.jsonl').write_text('{"data": 1}\n{"data": 2}\n{"data": 3}\n')
    received = helper.collector(Int32, '/tl_stream')
    _wait_subscriber_visible(lab, '/tl_stream')
    job = lab.injector.start(InjectSpec(mode='stream', topic='/tl_stream',
                                        type='std_msgs/msg/Int32', source='s.jsonl',
                                        rate_hz=50.0))
    wait_for(lambda: lab.injector.get(job['id'])['state'] == 'done', timeout=10.0)
    wait_for(lambda: len(received) >= 3, timeout=5.0)
    assert [m.data for m in received] == [1, 2, 3]


def test_injector_stop(lab):
    job = lab.injector.start(InjectSpec(mode='periodic', topic='/tl_stop',
                                        type='std_msgs/msg/Int32', payload={'data': 1},
                                        rate_hz=50.0))
    wait_for(lambda: lab.injector.get(job['id'])['sent'] > 0, timeout=5.0)
    stopped = lab.injector.stop(job['id'])
    assert stopped['state'] == 'stopped'
    sent = stopped['sent']
    time.sleep(0.3)
    assert lab.injector.get(job['id'])['sent'] == sent


def test_echo_latest_message(lab, helper):
    helper.periodic_publisher(String, '/tl_echo', 10.0, lambda i: String(data=f'echo {i}'))
    wait_for(lambda: '/tl_echo' in dict(lab.runtime.topic_names_and_types()), timeout=15.0)
    assert lab.echo.acquire('/tl_echo') == 'std_msgs/msg/String'
    try:
        seq, msg = wait_for(lambda: (lambda r: r if r[1] else None)(lab.echo.latest('/tl_echo')),
                            timeout=5.0)
        assert seq >= 1
        assert msg['data'].startswith('echo ')
    finally:
        lab.echo.release('/tl_echo')
    assert lab.echo.latest('/tl_echo') == (0, None)
