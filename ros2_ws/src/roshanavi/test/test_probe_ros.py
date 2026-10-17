"""The C++ probe end to end: per-node rates, fallback, restart, hidden self topics."""

import pytest
from rclpy.node import Node
from std_msgs.msg import String

from conftest import WS_ROOT, wait_for
from roshanavi.probe_process import find_probe_executable

pytestmark = pytest.mark.skipif(find_probe_executable() is None,
                                reason='roshanavi_probe is not built')

WINDOW = 10.0  # long window: rates within +-5 % even for the 2 Hz publisher


def _lab(data_dir, tmp_path, probe):
    from roshanavi.lab import Lab
    return Lab(data_dir=str(data_dir), period_sec=0.2, workspace=WS_ROOT,
               project_path=str(tmp_path / 'project' / 'roshanavi.yaml'),
               stop_timeouts=(3.0, 2.0), probe=probe).start()


@pytest.fixture
def probe_lab(data_dir, tmp_path):
    instance = _lab(data_dir, tmp_path, 'auto')
    yield instance
    instance.stop()


@pytest.fixture
def python_lab(data_dir, tmp_path):
    instance = _lab(data_dir, tmp_path, 'off')
    yield instance
    instance.stop()


def entry_of(lab, topic, window=WINDOW):
    return next((t for t in lab.traffic_view(window) if t['topic'] == topic), None)


def publishers_of(lab, topic):
    entry = entry_of(lab, topic)
    return {p['node']: p for p in (entry or {}).get('publishers') or []}


def second_node(helper, name):
    node = Node(name, context=helper.context)
    helper.executor.add_node(node)
    return node


def test_two_publishers_on_one_topic_are_measured_per_node(probe_lab, helper):
    other = second_node(helper, 'tl_slow_pub')
    helper.periodic_publisher(String, '/tl_two', 5.0, lambda i: String(data=f'f{i}'))
    slow_pub = other.create_publisher(String, '/tl_two', 10)
    other.create_timer(0.5, lambda: slow_pub.publish(String(data='s')))
    fast = '/' + helper.node.get_name()

    def settled():
        pubs = publishers_of(probe_lab, '/tl_two')
        entry = entry_of(probe_lab, '/tl_two')
        if not entry or entry['total_count'] < 70 or len(pubs) != 2:
            return None
        return pubs
    pubs = wait_for(settled, timeout=30.0, interval=0.5)
    assert pubs[fast]['basis'] == 'measured' and pubs['/tl_slow_pub']['basis'] == 'measured'
    assert pubs[fast]['hz'] == pytest.approx(5.0, rel=0.05)
    assert pubs['/tl_slow_pub']['hz'] == pytest.approx(2.0, rel=0.05)
    entry = entry_of(probe_lab, '/tl_two')
    assert entry['measurement'] == 'probe' and entry['hz_basis'] == 'source'
    assert entry['hz'] == pytest.approx(7.0, rel=0.05)
    assert entry['dropped'] == 0
    status = probe_lab.traffic.status()
    assert status['mode'] == 'probe' and status['gid_resolution'] == 'matched'
    assert status['cpu_percent'] is not None and status['rmw'] == 'rmw_fastrtps_cpp'
    other.destroy_node()


def test_probe_topics_are_hidden(probe_lab, helper):
    helper.periodic_publisher(String, '/tl_seen', 5.0, lambda i: String(data='x'))
    wait_for(lambda: probe_lab.traffic.status()['receiving'], timeout=15.0)
    wait_for(lambda: entry_of(probe_lab, '/tl_seen'), timeout=10.0)
    snapshot, _ = probe_lab.graph.snapshot()
    names = {t['name'] for t in snapshot['topics']}
    assert not any(n.startswith('/roshanavi/_probe') for n in names)
    assert not any(n['id'].startswith('/roshanavi_probe') for n in snapshot['nodes'])
    assert not any(t['topic'].startswith('/roshanavi/_probe') for t in probe_lab.traffic_view())


def test_probe_is_restarted_after_a_crash(probe_lab, helper):
    helper.periodic_publisher(String, '/tl_crash', 10.0, lambda i: String(data='x'))
    wait_for(lambda: (entry_of(probe_lab, '/tl_crash', 5.0) or {}).get('total_count', 0) > 5,
             timeout=15.0)
    process = probe_lab.traffic.backend.process
    first = process.pid
    process.kill()
    wait_for(lambda: process.pid not in (None, first), timeout=10.0)
    assert process.restarts == 1

    def counting_again():
        entry = entry_of(probe_lab, '/tl_crash', 5.0)
        return entry and entry['status'] == 'ok' and entry['hz'] > 5.0
    wait_for(counting_again, timeout=15.0)  # the latched config reached the new probe
    assert probe_lab.traffic.status()['state'] == 'running'


def test_probe_off_uses_the_python_monitor(python_lab, helper):
    helper.periodic_publisher(String, '/tl_py', 10.0, lambda i: String(data='x'))
    entry = wait_for(lambda: entry_of(python_lab, '/tl_py', 5.0), timeout=10.0)
    assert entry['measurement'] == 'python'
    status = python_lab.traffic.status()
    assert status['mode'] == 'python' and status['reason'] == 'disabled'


def test_api_reports_the_measurement(probe_lab):
    from fastapi.testclient import TestClient
    from roshanavi.server import create_app
    with TestClient(create_app(probe_lab, static_dir=None, live_period=0.2),
                    base_url='http://localhost') as client:
        body = client.get('/api/traffic').json()
    assert body['measurement']['mode'] == 'probe'
    assert body['measurement']['reason'] is None
