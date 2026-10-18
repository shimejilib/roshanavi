"""#12: a SIGKILLed server leaves its nodes; they are recorded, shown on the next start and
stopped by ``ros2 run roshanavi cleanup`` or ``POST /api/leftovers/stop``."""

import json
import os
import signal
import subprocess
import sys
import threading
import time

import httpx
import psutil
import pytest

from conftest import wait_for
from roshanavi.launcher import proc_record
from roshanavi.launcher.logbuf import LogBuffer
from roshanavi.launcher.process import ProcessRunner
from test_launcher_shutdown import PROJECT, alive, free_port, running_pids


def _server(tmp_path, port):
    return subprocess.Popen(
        ['ros2', 'run', 'roshanavi', 'server', '--port', str(port), '--workspace', str(tmp_path),
         '--data-dir', str(tmp_path / 'data'), '--log-level', 'warning',
         # a SIGKILLed server leaves its LTTng sessions until the next start: keep tracing
         # out of this test (test_tracing_ros checks that no roshanavi session is left)
         '--tracing', 'off', '--no-sample-media'],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True)


def _real_server(wrapper):
    """`ros2 run roshanavi server` is a wrapper: the real server is its python child."""
    children = [p for p in psutil.Process(wrapper.pid).children()
                if 'server' in ' '.join(p.cmdline())]
    return children[0] if children else psutil.Process(wrapper.pid)


def _kill9(tmp_path):
    """Start a server with 3 targets, wait until they are recorded, SIGKILL the server."""
    port = free_port()
    wrapper = _server(tmp_path, port)
    base = f'http://127.0.0.1:{port}'
    try:
        pids = wait_for(lambda: running_pids(base), timeout=40)
        record_dir = tmp_path / 'data' / proc_record.RECORD_DIR

        def recorded():
            files = list(record_dir.glob('procs-*.json'))
            if not files:
                return None
            entries = json.loads(files[0].read_text())['processes']
            return entries if {e['pid'] for e in entries} >= set(pids) else None
        wait_for(recorded, timeout=15)
        _real_server(wrapper).kill()
        wrapper.kill()
        wrapper.wait(timeout=10)
    finally:
        if wrapper.poll() is None:
            wrapper.kill()
    return pids


def _survivors(pids):
    time.sleep(1.0)  # PR_SET_PDEATHSIG has stopped the direct children by now
    return [pid for pid in pids if alive(pid)]


@pytest.fixture
def workspace(tmp_path):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'roshanavi.yaml').write_text(PROJECT)
    yield tmp_path
    for leftover in proc_record.find_leftovers(str(tmp_path / 'data')):
        leftover.proc.kill()  # never leave anything behind, even when a test fails


def test_cleanup_command_stops_what_a_sigkilled_server_left(workspace):
    pids = _kill9(workspace)
    left = _survivors(pids)
    assert left, 'nothing survived: the grandchildren case is not exercised'
    data = str(workspace / 'data')
    dry = subprocess.run(['ros2', 'run', 'roshanavi', 'cleanup', '--data-dir', data,
                          '--dry-run'], capture_output=True, text=True, timeout=30)
    assert dry.returncode == 0 and 'process(es) left' in dry.stdout, dry.stdout
    assert all(alive(pid) for pid in left)
    done = subprocess.run(['ros2', 'run', 'roshanavi', 'cleanup', '--data-dir', data],
                          capture_output=True, text=True, timeout=60)
    assert done.returncode == 0, done.stdout + done.stderr
    wait_for(lambda: not any(alive(pid) for pid in pids), timeout=10)
    assert list((workspace / 'data' / proc_record.RECORD_DIR).glob('procs-*.json')) == []
    again = subprocess.run(['ros2', 'run', 'roshanavi', 'cleanup', '--data-dir', data],
                           capture_output=True, text=True, timeout=30)
    assert 'Nothing to clean up' in again.stdout


def test_next_start_shows_the_leftovers_and_stops_them(workspace):
    pids = _kill9(workspace)
    left = _survivors(pids)
    assert left
    (workspace / 'roshanavi.yaml').write_text('targets: []\n')  # the next run starts nothing
    port = free_port()
    wrapper = _server(workspace, port)
    base = f'http://127.0.0.1:{port}'
    try:
        state = wait_for(lambda: _get(f'{base}/api/leftovers'), timeout=40)
        assert state['count'] == len(left)
        assert {p['pid'] for p in state['processes']} == set(left)
        result = httpx.post(f'{base}/api/leftovers/stop', timeout=30,
                            headers={'Content-Type': 'application/json'}, content='{}').json()
        assert sorted(p['pid'] for p in result['stopped']) == sorted(left)
        wait_for(lambda: not any(alive(pid) for pid in pids), timeout=10)
        assert _get(f'{base}/api/leftovers')['count'] == 0
    finally:
        wrapper.send_signal(signal.SIGTERM)
        try:
            wrapper.wait(timeout=30)
        except subprocess.TimeoutExpired:
            wrapper.kill()


def _get(url):
    try:
        return httpx.get(url, timeout=2).json()
    except (httpx.HTTPError, ValueError):
        return None


def test_record_fingerprint_ignores_reused_pids(tmp_path):
    record = proc_record.ProcessRecord(str(tmp_path), server_pid=os.getpid())
    sleeper = subprocess.Popen(['sleep', '60'])
    try:
        record.update([('t', 0.0, sleeper.pid)])
        data = json.loads(open(record.path).read())
        assert [e['pid'] for e in data['processes']] == [sleeper.pid]
        # a record from a dead server whose pid now belongs to another program
        first = data['processes'][0]
        assert first['start_ticks'] and first['create_time']
        entry = dict(first, start_ticks=first['start_ticks'] - 99,
                     create_time=first['create_time'] - 99)
        fake = {'version': 1, 'server': {'pid': 1, 'create_time': 0, 'cmd_hash': 'x'},
                'processes': [entry]}
        path = os.path.join(proc_record.records_dir(str(tmp_path)), 'procs-999999.json')
        with open(path, 'w') as handle:
            json.dump(fake, handle)
        assert proc_record.find_leftovers(str(tmp_path), own_pid=os.getpid()) == []
        assert not os.path.exists(path)  # nothing of it was left: tidied up
        # the same entry with the right fingerprint is a leftover
        with open(path, 'w') as handle:
            json.dump({**fake, 'processes': data['processes']}, handle)
        found = proc_record.find_leftovers(str(tmp_path), own_pid=os.getpid())
        assert [f.proc.pid for f in found] == [sleeper.pid]
        result = proc_record.stop_leftovers(found, steps=((signal.SIGTERM, 3.0),))
        assert [p['pid'] for p in result['stopped']] == [sleeper.pid]
        sleeper.wait(timeout=5)
    finally:
        if sleeper.poll() is None:
            sleeper.kill()
        record.close()
    assert not os.path.exists(record.path)


def test_children_survive_the_thread_that_started_them(tmp_path):
    """PR_SET_PDEATHSIG fires when the forking *thread* ends: spawning must not depend on the
    (short-lived) caller thread."""
    log = LogBuffer()
    runner = ProcessRunner(['sleep', '30'], dict(os.environ), str(tmp_path), log,
                           on_exit=lambda code: None)
    thread = threading.Thread(target=runner.start)
    thread.start()
    thread.join()
    time.sleep(1.0)
    try:
        assert runner.alive()
        if sys.platform.startswith('linux'):
            status = open(f'/proc/{runner.pid}/status').read()
            assert runner.pid and status  # the child is ours and running
    finally:
        runner.stop()
