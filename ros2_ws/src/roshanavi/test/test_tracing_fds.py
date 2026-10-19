"""File-descriptor regression for the tracing worker and the server.

The bt2 iterator used to keep every CTF stream file of each rotated chunk open
(deleted but not closed, one per CPU), so the worker ran into RLIMIT_NOFILE
after a few minutes and its restarts piled up lttng-sessiond processes.
"""

import os
import subprocess
import time

import psutil
import pytest

from conftest import WS_ROOT, wait_for
from roshanavi.tracing import config
from roshanavi.tracing.service import availability
from roshanavi.tracing.worker import Worker
from test_tracing_ros import Nodes, _make_lab  # noqa: F401  (fixtures below reuse Nodes)

pytestmark = pytest.mark.skipif(availability() is not None,
                                reason='lttng-tools / python3-bt2 not installed')

ROTATIONS = 16
UST_STEP_PER_CPU = 4
SLACK_FDS = 8        # steady-state wobble of the whole-process counts (restart test)
UST_STEP_BASE = 16   # constant part of the transient LTTng-UST re-registration step
SETTLE_SECONDS = 1.0
SETTLE_TIMEOUT = 20.0
TAIL_SLACK = 2       # once settled the worker fd count is flat; a one-fd-per-rotation leak shows here


def _fds(pid=None):
    return len(os.listdir(f'/proc/{pid or os.getpid()}/fd'))


def _sessiond_count():
    return sum(1 for p in psutil.process_iter(['name', 'uids'])
               if p.info['name'] == 'lttng-sessiond' and p.info['uids'].real == os.getuid())


def _settled_fds(stable_for=SETTLE_SECONDS, timeout=SETTLE_TIMEOUT):
    """fd count of this process once it has not changed for `stable_for` s (bounded wait)."""
    deadline = time.monotonic() + timeout
    last, since = _fds(), time.monotonic()
    while time.monotonic() < deadline:
        time.sleep(0.1)
        now = _fds()
        if now != last:
            last, since = now, time.monotonic()
        elif time.monotonic() - since >= stable_for:
            break
    return last


@pytest.fixture
def nodes():
    group = Nodes()
    yield group
    group.close()


def test_worker_fds_stay_bounded_over_many_rotations(tmp_path, nodes):
    worker = Worker('roshanavi-fdtest',
                    str(tmp_path / 'trace'), config.DEFAULT_RT_PER_CPU, lambda _msg: None)
    worker.parser.recycle_every = 4  # exercise the disposable parser child
    worker.start()
    try:
        nodes.start('demo_nodes_cpp', 'talker', '-r', '__node:=fd_talker', '-r', 'chatter:=/fd_chat')
        nodes.start('demo_nodes_cpp', 'listener', '-r', '__node:=fd_listener',
                    '-r', 'chatter:=/fd_chat')
        samples, parser_fds = [], []
        for _ in range(ROTATIONS):
            time.sleep(0.8)  # a requested rotation completes 0.3-1 s later
            worker.cycle(emit=False)
            samples.append(_fds())
            if worker.parser.pid:
                parser_fds.append(_fds(worker.parser.pid))
        assert worker._events_total > 0, 'no init events were parsed; the test would prove nothing'
        tail = samples[-6:]
        assert max(tail) <= min(tail) + TAIL_SLACK, f'fd count keeps growing: {samples}'
        # LTTng-UST registering this (traced) process with the new session daemon is a one-off
        # step proportional to the CPU count; a leak adds ~(cpus + 1) per rotation on top.
        assert samples[-1] <= samples[0] + UST_STEP_PER_CPU * (os.cpu_count() or 1) + SLACK_FDS, \
            f'fd count grew too much: {samples}'
        assert _sessiond_count() == 1
        # bt2 runs only in the parser child; it is replaced every 4 chunks, so whatever bt2
        # leaks (a metadata fd per chunk) is bounded and nothing is closed behind its back.
        assert worker.parser.children_started >= 2, 'the parser child was never recycled'
        assert parser_fds and max(parser_fds) <= min(parser_fds) + 4 + TAIL_SLACK, parser_fds
    finally:
        worker.close()
    assert worker.parser.pid is None
    wait_for(lambda: _sessiond_count() == 0, timeout=15.0)


def test_server_and_worker_fds_bounded_across_worker_restarts(data_dir, tmp_path):
    lab = _make_lab(data_dir, tmp_path)
    try:
        wait_for(lambda: lab.tracing.worker_pid(), timeout=20.0)
        time.sleep(3.0)
        baseline = _fds()
        after = []
        for restart in range(1, 4):
            os.kill(lab.tracing.worker_pid(), 9)
            wait_for(lambda: lab.tracing.status()['restarts'] == restart
                     and lab.tracing.worker_pid(), timeout=40.0, interval=0.5)
            assert _sessiond_count() == 1, 'a restart must reuse / replace the one sessiond'
            after.append(_settled_fds())
        # Right after a sessiond / worker restart this (UST-registered) process re-registers with
        # the new daemon: a transient per-CPU step (shm + pipes). It must be bounded by the CPU
        # count, and what remains once settled must not grow from restart to restart.
        step_limit = (os.cpu_count() or 1) * UST_STEP_PER_CPU + UST_STEP_BASE
        assert max(after) <= baseline + step_limit, f'server fds {baseline} -> {after}'
        assert after[-1] <= after[0] + SLACK_FDS, f'server fds grow per restart: {after}'
        worker_fds = _fds(lab.tracing.worker_pid())
        time.sleep(6.0)
        assert _fds(lab.tracing.worker_pid()) <= worker_fds + SLACK_FDS
    finally:
        lab.stop()
