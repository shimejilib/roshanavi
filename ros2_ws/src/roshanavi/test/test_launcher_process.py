"""Process lifecycle: log capture, stop escalation, no orphans, crash / auto-restart."""

import os
import sys
import textwrap
import time

import psutil
import pytest

from conftest import wait_for
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.logbuf import LogBuffer
from roshanavi.launcher.process import ProcessRunner
from roshanavi.launcher.schema import TargetSpec
from roshanavi.launcher.target import Target

FAST = (0.6, 0.6)  # SIGINT / SIGTERM grace periods for tests


def script(body: str):
    return [sys.executable, '-c', textwrap.dedent(body)]


IGNORE_INT = '''
    import signal, sys, time
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    print("ready", flush=True)
    while True: time.sleep(0.1)
'''
IGNORE_ALL = '''
    import signal, time
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print("ready", flush=True)
    while True: time.sleep(0.1)
'''
WITH_GRANDCHILD = '''
    import subprocess, sys, time
    subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    print("ready", flush=True)
    time.sleep(60)
'''


def runner_for(body, exits=None):
    log = LogBuffer()
    codes = exits if exits is not None else []
    runner = ProcessRunner(script(body), dict(os.environ), '/', log, on_exit=codes.append,
                           timeouts=FAST)
    runner.start()
    wait_for(lambda: any(ln['text'] == 'ready' for ln in log.since(0)[0]), timeout=10)
    return runner, log, codes


def gone(pids):
    def check(pid):
        try:
            return psutil.Process(pid).status() == psutil.STATUS_ZOMBIE
        except psutil.NoSuchProcess:
            return True
    return all(check(p) for p in pids)


def test_logs_are_tagged_by_stream():
    log = LogBuffer()
    exits = []
    runner = ProcessRunner(script('''
        import sys
        print("out line", flush=True)
        print("err line", file=sys.stderr, flush=True)
        sys.exit(3)
    '''), dict(os.environ), '/', log, on_exit=exits.append)
    runner.start()
    wait_for(lambda: exits, timeout=10)
    lines = {(ln['stream'], ln['text']) for ln in log.since(0)[0]}
    assert ('stdout', 'out line') in lines and ('stderr', 'err line') in lines
    assert ('system', '[exit 3]') in lines and exits == [3]


def test_stop_escalates_to_sigterm():
    runner, log, _ = runner_for(IGNORE_INT)
    started = time.monotonic()
    code = runner.stop()
    assert code == -15
    assert FAST[0] <= time.monotonic() - started < FAST[0] + FAST[1] + 2
    assert any('SIGTERM' in ln['text'] for ln in log.since(0)[0])


def test_stop_escalates_to_sigkill():
    runner, log, _ = runner_for(IGNORE_ALL)
    assert runner.stop() == -9
    assert any('SIGKILL' in ln['text'] for ln in log.since(0)[0])


def test_stop_kills_the_whole_process_group():
    runner, _, _ = runner_for(WITH_GRANDCHILD)
    pids = wait_for(lambda: (lambda p: p if len(p) == 2 else None)(runner.tree_pids()))
    runner.stop()
    wait_for(lambda: gone(pids), timeout=5)


def test_ring_buffer_limit_and_cursor():
    log = LogBuffer(max_lines=3)
    for i in range(5):
        log.append('stdout', f'l{i}\n')
    lines, cursor = log.since(0)
    assert [ln['text'] for ln in lines] == ['l2', 'l3', 'l4'] and cursor == 5
    log.append('stderr', 'x')
    assert [ln['text'] for ln in log.since(cursor)[0]] == ['x']


def make_target(body, auto_restart=False):
    spec = TargetSpec(id='t1', kind='run', package='p', executable='e', auto_restart=auto_restart)
    return Target(spec, lambda _s: script(body), lambda: dict(os.environ), '/', FAST)


def test_target_status_crash_and_stop():
    target = make_target('import sys, time; time.sleep(0.3); sys.exit(4)')
    target.start()
    assert target.status() == 'starting'
    wait_for(lambda: target.status() == 'crashed', timeout=10)
    assert target.to_dict()['exit_code'] == 4
    target = make_target(IGNORE_INT)
    target.start()
    with pytest.raises(LauncherError) as err:
        target.start()
    assert err.value.code == 'already_running'
    target.stop()
    assert target.status() == 'stopped' and not target.alive()


def test_target_exited_cleanly():
    target = make_target('print("bye")')
    target.start()
    wait_for(lambda: target.status() == 'exited', timeout=10)


def test_auto_restart_after_crash():
    target = make_target('import sys, time; time.sleep(0.2); sys.exit(1)', auto_restart=True)
    target.start()
    wait_for(lambda: target.to_dict()['restart_count'] >= 1, timeout=10)
    target.stop()
    assert target.status() == 'stopped'
    count = target.to_dict()['restart_count']
    time.sleep(2.5)  # no more restarts once the user stopped it
    assert target.to_dict()['restart_count'] == count


def test_restart_counts_and_replaces_process():
    target = make_target('import time; time.sleep(60)')
    target.start()
    first = target.to_dict()['pid']
    target.restart()
    info = target.to_dict()
    assert info['restart_count'] == 1 and info['pid'] != first
    target.stop()


def test_service_reports_running_once_the_node_is_mapped_even_within_the_starting_window():
    """#7: 「起動中」 lasts until the node shows up on the map, not a fixed 2 s."""
    from roshanavi.launcher.service import Launcher
    from roshanavi.process_map import NodeMapping

    class Manager:
        def list(self):
            return [{'id': 'a', 'status': 'starting'}, {'id': 'b', 'status': 'starting'},
                    {'id': 'c', 'status': 'stopped'}]

    class Mapper:
        def mapping(self):
            return {'/a_node': NodeMapping('/a_node', 'a', 10, 'exact')}

    service = object.__new__(Launcher)
    service.manager, service.mapper = Manager(), Mapper()
    by_id = {t['id']: t for t in service.targets()}
    assert by_id['a']['status'] == 'running' and by_id['a']['nodes'][0]['node'] == '/a_node'
    assert by_id['b']['status'] == 'starting'  # nothing mapped yet
    assert by_id['c']['status'] == 'stopped'
