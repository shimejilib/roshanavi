"""executor_busy_demo (roshanavi_examples): the statistics, then the real busy-loop reproduction.

The integration tests at the bottom are TIMING- AND ENVIRONMENT-SENSITIVE (they measure how often
a real rclpy executor wakes up per second, over ~6 s windows). The margins are generous (a
measured ~25x difference is asserted as >= 5x). If the busy-loop does not reproduce at all
(another RMW, or an upstream fix of ros2/rmw_fastrtps#929) the reproduction test is skipped with
that reason instead of being weakened; the "workaround is healthy" tests still run.
"""

import json
import os
import subprocess
import time

import pytest
import rclpy
from rclpy.context import Context
from rclpy.signals import SignalHandlerOptions
from std_msgs.msg import String

from conftest import Helper, wait_for
from roshanavi_examples.executor_busy_demo import (BusyStats, PassCounter, format_summary,
                                                   make_executor, normalize_qos_events,
                                                   validate_options)
from test_dummy import stop_group


# ---- BusyStats ---------------------------------------------------------------------------

def test_snapshot_turns_counts_into_per_second_numbers():
    stats = BusyStats(now=100.0, cpu_seconds=1.0)
    for empty in [True] * 150 + [False] * 50:
        stats.record_pass(empty)
    for _ in range(20):
        stats.record_callback()
    snap = stats.snapshot(now=102.0, cpu_seconds=2.5)
    assert snap == {'wait_passes_per_sec': 100.0, 'empty_passes_per_sec': 75.0,
                    'empty_ratio': 0.75, 'callbacks_per_sec': 10.0, 'passes_per_callback': 10.0,
                    'process_cpu_percent': 75.0}


def test_snapshot_starts_a_new_window():
    stats = BusyStats(now=0.0, cpu_seconds=0.0)
    stats.record_pass(True)
    stats.snapshot(now=1.0, cpu_seconds=0.5)
    snap = stats.snapshot(now=2.0, cpu_seconds=0.5)
    assert snap['wait_passes_per_sec'] == 0.0 and snap['empty_ratio'] == 0.0
    assert snap['process_cpu_percent'] == 0.0 and snap['passes_per_callback'] == 0.0


def test_snapshot_with_no_elapsed_time_is_all_zero():
    stats = BusyStats(now=5.0, cpu_seconds=0.0)
    stats.record_pass(True)
    assert set(stats.snapshot(now=5.0, cpu_seconds=1.0).values()) == {0.0}


def test_cpu_percent_can_exceed_100_with_several_threads():
    stats = BusyStats(now=0.0, cpu_seconds=0.0)
    assert stats.snapshot(now=1.0, cpu_seconds=2.5)['process_cpu_percent'] == 250.0


def test_format_summary_is_one_readable_line():
    line = format_summary({'executor': 'multi', 'qos_events': 'default',
                           'wait_passes_per_sec': 8203.4, 'empty_ratio': 0.9951,
                           'callbacks_per_sec': 41.0, 'process_cpu_percent': 87.2})
    assert line == ('executor=multi qos_events=default wait passes/s=8203 empty=99.5% '
                    'callbacks/s=41 cpu=87%')


# ---- options -----------------------------------------------------------------------------

@pytest.mark.parametrize('value,expected', [('off', 'off'), (' OFF ', 'off'), ('default', 'default'),
                                            (False, 'off'), (True, 'default')])
def test_qos_events_accepts_the_yaml_boolean_trap(value, expected):
    # `-p qos_events:=off` is parsed as YAML: a bare `off` is the boolean False.
    assert normalize_qos_events(value) == expected


@pytest.mark.parametrize('args', [('dual', 'default', 5.0, 4), ('multi', 'maybe', 5.0, 4),
                                  ('multi', 'off', -1.0, 4), ('multi', 'off', 5.0, -2)])
def test_invalid_options_are_rejected(args):
    with pytest.raises(ValueError):
        validate_options(*args)


def test_valid_options_pass():
    validate_options('single', 'off', 0.0, 0)


# ---- PassCounter (fake executor: no ROS involved) ------------------------------------------

class FakeExecutor:
    """Replays a script: each wait_for_ready_callbacks call returns an item or raises."""

    def __init__(self, script=()):
        self.script = list(script)

    def get_nodes(self):
        return []

    def wait_for_ready_callbacks(self, *args, **kwargs):
        step = self.script.pop(0)
        if step is None:
            raise TimeoutError('nothing ready')
        return step


class CountingFake(PassCounter, FakeExecutor):
    pass


def test_pass_counter_separates_productive_and_empty_passes():
    stats = BusyStats(0.0, 0.0)
    ex = CountingFake(stats=stats, script=['a', 'b'])
    ex.get_nodes()                               # pass 1 starts
    assert ex.wait_for_ready_callbacks() == 'a'  # ... returns two callbacks
    assert ex.wait_for_ready_callbacks() == 'b'
    ex.get_nodes()                               # pass 2 starts (closes pass 1: productive)
    ex.get_nodes()                               # pass 3 starts (closes pass 2: it was empty)
    ex.get_nodes()                               # pass 4 starts (closes pass 3: empty)
    snap = stats.snapshot(now=1.0, cpu_seconds=0.0)
    assert snap['wait_passes_per_sec'] == 3.0
    assert snap['empty_passes_per_sec'] == 2.0


def test_pass_counter_does_not_count_the_pass_still_in_progress():
    stats = BusyStats(0.0, 0.0)
    ex = CountingFake(stats=stats)
    ex.get_nodes()
    assert stats.snapshot(now=1.0, cpu_seconds=0.0)['wait_passes_per_sec'] == 0.0


def test_pass_counter_passes_exceptions_through_without_marking_work():
    stats = BusyStats(0.0, 0.0)
    ex = CountingFake(stats=stats, script=[None])
    ex.get_nodes()
    with pytest.raises(TimeoutError):
        ex.wait_for_ready_callbacks()
    ex.get_nodes()
    assert stats.snapshot(now=1.0, cpu_seconds=0.0)['empty_passes_per_sec'] == 1.0


# ---- the real rclpy executors ----------------------------------------------------------------

@pytest.mark.parametrize('kind', ['single', 'multi'])
def test_counting_executor_counts_real_passes(kind):
    context = Context()
    rclpy.init(context=context, signal_handler_options=SignalHandlerOptions.NO)
    try:
        node = rclpy.create_node('rn_busy_unit', context=context)
        fired = []
        timer = node.create_timer(0.02, lambda: fired.append(1))
        stats = BusyStats(time.monotonic(), time.process_time())
        executor = make_executor(kind, stats, 2, context=context)
        executor.add_node(node)
        deadline = time.monotonic() + 0.6
        while time.monotonic() < deadline:
            executor.spin_once(timeout_sec=0.1)
        timer.cancel()
        executor.spin_once(timeout_sec=0.05)   # let a callback that is still running finish
        executor.shutdown()
        node.destroy_node()
        snap = stats.snapshot(time.monotonic(), time.process_time())
        assert len(fired) >= 5
        assert snap['wait_passes_per_sec'] > 0
        assert 0.0 <= snap['empty_ratio'] <= 1.0
    finally:
        rclpy.shutdown(context=context)


def test_make_executor_rejects_unknown_kind():
    with pytest.raises(ValueError):
        make_executor('dual', BusyStats(0.0, 0.0))


# ---- integration: the busy-loop on a real node (timing/environment sensitive) -----------------

WARMUP_ROWS = 3        # stats rows to ignore (start-up, discovery)
SAMPLE_ROWS = 6        # stats rows (= seconds) that are measured
DRIVER_HZ = 100.0


def run_ros(executable, *ros_args):
    return subprocess.Popen(['ros2', 'run', 'roshanavi_examples', executable, '--ros-args',
                             *ros_args], start_new_session=True, stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL)


def measure(helper, tag, executor, qos_events):
    """Run driver + demo with private topic names; return the median of the stats rows."""
    stats_topic, in_topic = f'/rn_busy_{tag}/stats', f'/rn_busy_{tag}/in'
    rows = []
    helper.node.create_subscription(String, stats_topic,
                                    lambda m: rows.append(json.loads(m.data)), 10)
    driver = run_ros('busy_demo_driver', '-r', f'__node:=rn_busy_drv_{tag}',
                     '-p', f'rate_hz:={DRIVER_HZ}', '-p', f'topic:={in_topic}')
    demo = run_ros('executor_busy_demo', '-r', f'__node:=rn_busy_demo_{tag}',
                   '-p', f'executor:={executor}', '-p', f'qos_events:={qos_events}',
                   '-p', f'input_topic:={in_topic}', '-p', f'stats_topic:={stats_topic}')
    try:
        wait_for(lambda: len(rows) >= WARMUP_ROWS + SAMPLE_ROWS, timeout=40)
    finally:
        stop_group(demo)
        stop_group(driver)
    window = rows[WARMUP_ROWS:WARMUP_ROWS + SAMPLE_ROWS]
    assert {r['executor'] for r in window} == {executor}
    assert {r['qos_events'] for r in window} == {qos_events}
    median = {}
    for key in window[0]:
        if isinstance(window[0][key], (int, float)):
            values = sorted(r[key] for r in window)
            median[key] = values[len(values) // 2]
    return median


@pytest.fixture(scope='module')
def module_helper():
    h = Helper()
    yield h
    h.close()


@pytest.fixture(scope='module')
def configs(module_helper):
    """The three configurations of the example project, measured one after another."""
    results = {}
    for tag, executor, qos in (('md', 'multi', 'default'), ('mo', 'multi', 'off'),
                               ('sd', 'single', 'default')):
        results[(executor, qos)] = measure(module_helper, tag, executor, qos)
    print('\nbusy demo measurements:', json.dumps({f'{k[0]}+{k[1]}': v
                                                   for k, v in results.items()}, indent=1))
    return results


def test_workarounds_keep_the_executor_calm(configs):
    """multi+off and single+default: about one wake-up per callback, all messages processed."""
    for key in (('multi', 'off'), ('single', 'default')):
        row = configs[key]
        assert row['callbacks_per_sec'] >= 0.7 * DRIVER_HZ, (key, row)
        assert row['wait_passes_per_sec'] < 1500, (key, row)
        assert row['passes_per_callback'] < 20, (key, row)


def test_multi_with_default_qos_events_spins_in_circles(configs):
    """The upstream bug (ros2/rmw_fastrtps#929): far more, and mostly empty, wait passes."""
    if 'fastrtps' not in os.environ.get('RMW_IMPLEMENTATION', 'rmw_fastrtps_cpp'):
        pytest.skip('the busy-loop is specific to rmw_fastrtps_cpp')
    bad, good = configs[('multi', 'default')], configs[('multi', 'off')]
    if bad['wait_passes_per_sec'] < 5 * good['wait_passes_per_sec']:
        pytest.skip('busy-loop did not reproduce here (rmw_fastrtps fixed upstream, or a '
                    f'different middleware setup): {bad} vs {good}')
    assert bad['empty_ratio'] > 0.9
    assert bad['wait_passes_per_sec'] >= 10 * good['wait_passes_per_sec']
    assert bad['empty_passes_per_sec'] >= 10 * good['empty_passes_per_sec']
    assert bad['passes_per_callback'] >= 10 * good['passes_per_callback']
    assert bad['process_cpu_percent'] > 2 * good['process_cpu_percent']
