"""No orphans: every launcher child dies when the server process is stopped."""

import signal
import socket
import subprocess

import httpx
import psutil
import pytest

from conftest import wait_for

PROJECT = '''targets:
- {id: talker, kind: run, package: demo_nodes_cpp, executable: talker, name: rn_sd_talker,
   autostart: true}
- {id: pair, kind: launch, package: demo_nodes_cpp, launch_file: talker_listener_launch.py,
   autostart: true}
dummies:
- {id: dum, name: rn_sd_dummy, topic: /rn_sd, type: std_msgs/msg/String, mode: periodic,
   payload: {data: x}, rate_hz: 2, autostart: true}
'''


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


def alive(pid: int) -> bool:
    try:
        return psutil.Process(pid).status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def running_pids(base: str):
    try:
        targets = httpx.get(f'{base}/api/targets', timeout=2).json()['targets']
    except (httpx.HTTPError, ValueError):
        return None
    if len(targets) == 3 and all(t['status'] == 'running' and t['pids'] for t in targets):
        pids = [pid for t in targets for pid in t['pids']]
        return pids if len(pids) >= 6 else None
    return None


@pytest.mark.parametrize('sig', [signal.SIGTERM, signal.SIGINT, signal.SIGHUP])
def test_server_stop_leaves_no_orphans(tmp_path, sig):
    (tmp_path / 'data').mkdir()
    (tmp_path / 'roshanavi.yaml').write_text(PROJECT)
    port = free_port()
    server = subprocess.Popen(
        ['ros2', 'run', 'roshanavi', 'server', '--port', str(port), '--workspace', str(tmp_path),
         '--data-dir', str(tmp_path / 'data'), '--log-level', 'warning'],
        stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True, start_new_session=True)
    base = f'http://127.0.0.1:{port}'
    try:
        pids = wait_for(lambda: running_pids(base), timeout=40)
        # `ros2 run roshanavi server` is a wrapper: signal the real server process.
        real = [p for p in psutil.Process(server.pid).children()
                if 'server' in ' '.join(p.cmdline())] or [psutil.Process(server.pid)]
        real[0].send_signal(sig)
        server.wait(timeout=30)
        wait_for(lambda: not any(alive(pid) for pid in pids), timeout=10)
    finally:
        if server.poll() is None:
            server.kill()
            server.wait()
        _, err = server.communicate()
    assert 'Traceback' not in err, err
