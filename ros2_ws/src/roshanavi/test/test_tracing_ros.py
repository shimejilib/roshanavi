"""詳細計測モード end to end with real C++ / Python nodes (LTTng in the test container).

Nodes are started after the Lab (so their init events are captured), the mode
is turned on through the API, and the subscriber rows must become
``measured``. Also: the slow-callback fixture is reported as behind, rclpy is
receive-only, cleanup leaves no LTTng process / session / files, and a tiny
buffer reports discarded events.
"""

import os
import subprocess
import time

import psutil
import pytest

from conftest import WS_ROOT, wait_for
from roshanavi.tracing.service import availability

pytestmark = pytest.mark.skipif(availability() is not None,
                                reason='lttng-tools / python3-bt2 not installed')

WINDOW = 5.0


def _executable(package, name):
    from ament_index_python.packages import get_package_prefix
    return os.path.join(get_package_prefix(package), 'lib', package, name)


class Nodes:
    """Child ROS processes, terminated at teardown."""

    def __init__(self):
        self.procs = []

    def start(self, package, executable, *ros_args):
        argv = [_executable(package, executable), '--ros-args', *ros_args]
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.procs.append(proc)
        return proc

    def close(self):
        for proc in self.procs:
            proc.terminate()
        for proc in self.procs:
            try:
                proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5.0)


@pytest.fixture
def nodes():
    group = Nodes()
    yield group
    group.close()


def _lttng_pids():
    return {p.pid for p in psutil.process_iter(['name'])
            if (p.info.get('name') or '').startswith('lttng-')}


def _make_lab(data_dir, tmp_path, **kwargs):
    from roshanavi.lab import Lab
    return Lab(data_dir=str(data_dir), period_sec=0.2, workspace=WS_ROOT,
               project_path=str(tmp_path / 'project' / 'roshanavi.yaml'),
               stop_timeouts=(3.0, 2.0), probe='auto', tracing='auto', **kwargs).start()


@pytest.fixture
def trace_client(data_dir, tmp_path):
    from fastapi.testclient import TestClient
    from roshanavi.server import create_app
    lab = _make_lab(data_dir, tmp_path)
    with TestClient(create_app(lab, static_dir=None, live_period=0.2),
                    base_url='http://localhost') as client:
        yield lab, client
    lab.stop()


def _subscriber(lab, topic, node):
    entry = next((e for e in lab.traffic_view(WINDOW) if e['topic'] == topic), None)
    return next((s for s in (entry or {}).get('subscribers') or [] if s['node'] == node), None)


def _publisher(lab, topic, node):
    entry = next(e for e in lab.traffic_view(WINDOW) if e['topic'] == topic)
    return next(p for p in entry['publishers'] if p['node'] == node)


def _measured(lab, topic, node, check=lambda s: True):
    def ready():
        if (lab.tracing.status()['active_sec'] or 0) < WINDOW + 2.5:  # one full window
            return None
        sub = _subscriber(lab, topic, node)
        return sub if sub and sub['basis'] == 'measured' and check(sub) else None
    return wait_for(ready, timeout=40.0, interval=0.5)


def test_measured_receive_process_and_slow_callback(trace_client, nodes):
    lab, client = trace_client
    assert client.get('/api/tracing').json()['available'] is True
    nodes.start('demo_nodes_cpp', 'talker', '-r', '__node:=tl_talker', '-r', 'chatter:=/tl_chat')
    nodes.start('demo_nodes_cpp', 'listener', '-r', '__node:=tl_listener',
                '-r', 'chatter:=/tl_chat')
    nodes.start('roshanavi_test_nodes', 'rate_talker', '-r', '__node:=tl_fast',
                '-p', 'topic:=/tl_fast', '-p', 'rate_hz:=10.0')
    nodes.start('roshanavi_test_nodes', 'slow_listener', '-r', '__node:=tl_slow',
                '-p', 'topic:=/tl_fast', '-p', 'sleep_ms:=200')
    wait_for(lambda: _subscriber(lab, '/tl_fast', '/tl_slow'), timeout=30.0)
    resp = client.put('/api/tracing', json={'enabled': True})
    assert resp.status_code == 200, resp.text
    assert resp.json()['active'] is True

    listener = _measured(lab, '/tl_chat', '/tl_listener',
                         lambda s: s['hz_processed'] and s['hz_recv'])
    assert listener['hz_recv'] == pytest.approx(1.0, abs=0.25)
    assert listener['hz_processed'] == pytest.approx(listener['hz_recv'], abs=0.25)
    assert listener['lang'] == 'cpp' and listener['cb_ms']['max'] < 50.0
    assert 'Listener' in (listener['symbol'] or '')
    # trace and probe agree on the same 1 Hz stream (>= 6 s of tracing, see _measured)
    probe_pub = _publisher(lab, '/tl_chat', '/tl_talker')
    assert probe_pub['basis'] == 'measured'
    assert listener['hz_recv'] == pytest.approx(probe_pub['hz'], rel=0.02)
    assert listener['hz_processed'] == pytest.approx(probe_pub['hz'], rel=0.02)
    assert probe_pub['hz_traced'] == pytest.approx(probe_pub['hz'], rel=0.02)

    slow = _measured(lab, '/tl_fast', '/tl_slow', lambda s: s.get('behind'))
    assert slow['hz_processed'] == pytest.approx(5.0, abs=0.8)
    assert slow['cb_ms']['avg'] == pytest.approx(200.0, abs=40.0)
    assert slow['hz_expected'] == pytest.approx(10.0, abs=1.5)
    assert slow['behind']['incoming_hz'] > slow['behind']['processed_hz'] + 3.0

    status = client.get('/api/tracing').json()
    diag = [d for d in status['diagnostics'] if d['node'] == '/tl_slow']
    assert diag and diag[0]['code'] == 'processing_behind' and diag[0]['topic'] == '/tl_fast'
    assert status['discarded'] == 0 and status['events_per_sec'] > 0
    assert status['cpu_percent']['total'] is not None
    assert status['disk_bytes'] < 32 * 1024 * 1024
    pub = next(p for e in lab.traffic_view(WINDOW) if e['topic'] == '/tl_fast'
               for p in e['publishers'] if p['node'] == '/tl_fast')
    assert pub['hz_traced'] == pytest.approx(10.0, abs=1.5)

    assert client.put('/api/tracing', json={'enabled': False}).json()['active'] is False
    assert _subscriber(lab, '/tl_chat', '/tl_listener')['basis'] == 'theoretical'


def test_rclpy_is_receive_only_and_older_nodes_are_listed(data_dir, tmp_path, nodes):
    nodes.start('demo_nodes_cpp', 'listener', '-r', '__node:=tl_early',
                '-r', 'chatter:=/tl_py')  # running before roshanavi: no init events
    time.sleep(2.0)
    lab = _make_lab(data_dir, tmp_path)
    try:
        nodes.start('demo_nodes_cpp', 'talker', '-r', '__node:=tl_pytalker',
                    '-r', 'chatter:=/tl_py')
        nodes.start('demo_nodes_py', 'listener', '-r', '__node:=tl_pylistener',
                    '-r', 'chatter:=/tl_py')
        wait_for(lambda: _subscriber(lab, '/tl_py', '/tl_pylistener'), timeout=30.0)
        lab.set_tracing(True)
        py = _measured(lab, '/tl_py', '/tl_pylistener', lambda s: s['hz_recv'])
        assert py['lang'] == 'py' and py['hz_processed'] is None and py['cb_ms'] is None
        assert py['behind'] is None

        def listed():
            reasons = {u['node']: u['reason'] for u in lab.tracing_status()['unsupported']}
            return reasons if '/tl_pylistener' in reasons and '/tl_early' in reasons else None
        reasons = wait_for(listed, timeout=20.0, interval=0.5)
        assert reasons['/tl_pylistener'] == 'rclpy'
        assert reasons['/tl_early'] == 'not_traced'  # not ours: cannot know its pid
        assert _subscriber(lab, '/tl_py', '/tl_early')['basis'] == 'theoretical'
    finally:
        lab.stop()


def test_cleanup_leaves_no_lttng_process_session_or_files(data_dir, tmp_path, nodes):
    before = _lttng_pids()
    lab = _make_lab(data_dir, tmp_path)
    out_dir = lab.tracing.out_dir
    nodes.start('demo_nodes_cpp', 'talker', '-r', '__node:=tl_clean', '-r', 'chatter:=/tl_cl')
    lab.set_tracing(True)
    wait_for(lambda: lab.tracing.snapshot(), timeout=20.0)
    assert out_dir and os.path.isdir(out_dir)
    worker = psutil.Process(lab.tracing.worker_pid())
    lab.stop()
    assert not psutil.pid_exists(worker.pid) or worker.status() == psutil.STATUS_ZOMBIE
    assert not os.path.exists(out_dir)
    wait_for(lambda: _lttng_pids() <= before, timeout=15.0)
    listing = subprocess.run(['lttng', 'list'], capture_output=True, text=True)
    assert 'roshanavi-' not in listing.stdout


def test_tiny_buffer_reports_discarded_events(data_dir, tmp_path, nodes):
    lab = _make_lab(data_dir, tmp_path, trace_buffer_per_cpu=8 * 1024)
    try:
        nodes.start('roshanavi_test_nodes', 'rate_talker', '-r', '__node:=tl_burst',
                    '-p', 'topic:=/tl_burst', '-p', 'rate_hz:=20.0', '-p', 'burst:=2000')
        nodes.start('roshanavi_test_nodes', 'slow_listener', '-r', '__node:=tl_burst_sub',
                    '-p', 'topic:=/tl_burst')
        time.sleep(2.0)
        status = lab.set_tracing(True)
        assert status['active'] is True
        found = wait_for(lambda: lab.tracing.status()['discarded'], timeout=30.0, interval=0.5)
        assert found > 0
        assert lab.tracing.status()['buffer_per_cpu'] == 8 * 1024
    finally:
        lab.stop()


def test_worker_crash_is_restarted(data_dir, tmp_path):
    lab = _make_lab(data_dir, tmp_path)
    try:
        first = lab.tracing.worker_pid()
        os.kill(first, 9)
        wait_for(lambda: lab.tracing.status()['restarts'] == 1 and lab.tracing.worker_pid(),
                 timeout=30.0, interval=0.5)
        assert lab.tracing.worker_pid() != first
        assert lab.tracing.status()['available'] is True
        assert lab.set_tracing(True)['active'] is True
    finally:
        lab.stop()
