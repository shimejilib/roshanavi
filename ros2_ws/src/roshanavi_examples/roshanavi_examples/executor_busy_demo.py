"""executor_busy_demo: see (and fix) the rclpy "executor spins in circles" CPU problem.

The problem in one paragraph
    A Python (rclpy) node that runs a MultiThreadedExecutor on Fast DDS (the default ROS 2
    middleware, ``rmw_fastrtps_cpp``) can burn a whole CPU core while doing almost nothing.
    Every subscription quietly gets "QoS event" handlers (they log a warning such as
    "New publisher discovered on topic ... offering incompatible QoS"). In rmw_fastrtps those
    event handlers wait on the very same "data arrived" flag as the subscription itself. The
    MultiThreadedExecutor takes a subscription out of its wait list while a worker thread runs
    its callback, so a new sample can arrive while the subscription is *not* waited on. The
    event handler then keeps saying "something happened!" but there is nothing to do, wait()
    returns at once, and the executor thread loops thousands of times per second holding
    Python's GIL. Upstream report: https://github.com/ros2/rmw_fastrtps/issues/929
    (related: https://github.com/ros2/rclpy/issues/1223).

What this node does
    Subscribes  /busy_demo/in     std_msgs/msg/String   (parameter ``input_topic``)
    Publishes   /busy_demo/stats  std_msgs/msg/String   (parameter ``stats_topic``), once a
                second, a JSON object such as
        {"executor": "multi", "qos_events": "default", "num_threads": 4, "work_ms": 5.0,
         "wait_passes_per_sec": 8203.4, "empty_passes_per_sec": 8161.0, "empty_ratio": 0.9949,
         "callbacks_per_sec": 41.0, "passes_per_callback": 200.1, "process_cpu_percent": 87.2}
    and logs the same numbers as one line per second.

    The callback only sleeps ``work_ms`` milliseconds (a stand-in for "some light work"), so
    any CPU you see is the executor's own overhead, not your code.

Parameters
    executor     "single" | "multi"      which executor runs the node (default multi)
    qos_events   "default" | "off"       "default": rclpy's normal QoS event handlers
                                         (a bare `off` in YAML is the boolean False; it is accepted)
                                         "off": SubscriptionEventCallbacks(use_default_callbacks=False)
    work_ms      callback work in ms     (default 5)
    num_threads  worker threads for multi (0 = automatic, default 4)
    input_topic, stats_topic             topic names

How to read the numbers
    A healthy executor still wakes up about once or twice per callback (its own internal
    "work is finished" signal), so an empty_ratio around 0.5 and passes_per_callback of 1-3
    are normal. The problem looks like thousands of passes per second, empty_ratio close to 1,
    and a high process_cpu_percent while callbacks_per_sec stays low or even drops.

Things to try (start /busy_demo/driver first, it publishes ~100 messages/s)
    multi  + default : high empty_ratio, a CPU core is gone       <- the problem
    multi  + off     : empty_ratio ~ 0, CPU back to a few percent  <- the workaround
    single + default : empty_ratio ~ 0, too (the callback runs in the waiting thread, so the
                       subscription is always on the wait list)

The trade-off of qos_events:=off
    The same event handlers are what print the helpful "incompatible QoS" warning when a
    publisher and a subscriber cannot talk to each other (for example best effort vs
    reliable). With the handlers off, that warning disappears and you only notice the
    mismatch because no data arrives. Turn them off only for subscriptions where the CPU cost
    matters (high rates + MultiThreadedExecutor), or keep them and use a SingleThreadedExecutor.

How the counting works (no monkeypatching)
    ``Executor.wait_for_ready_callbacks()`` and ``Executor.get_nodes()`` are public methods of
    rclpy's Executor. Each pass of the executor's wait loop calls get_nodes() once at its start,
    and every callback it finds ready is returned from wait_for_ready_callbacks(). So:
        pass = one call of get_nodes();
        empty pass = a pass after which wait_for_ready_callbacks() returned nothing.
    ``PassCounter`` below is a small mixin that overrides those two public methods. The only
    assumption is that one wait-loop pass calls get_nodes() once, which holds for rclpy 7.x
    (Jazzy) and 10.x (Lyrical); the unit tests and the integration test would notice if that stopped being true.

Run:  ros2 run roshanavi_examples executor_busy_demo --ros-args -p executor:=multi -p qos_events:=off
      ros2 launch roshanavi_examples busy_demo.launch.py executor:=multi qos_events:=default
"""

import json
import sys
import threading
import time
from typing import Any, Dict, Optional

EXECUTORS = ('single', 'multi')
QOS_EVENT_MODES = ('default', 'off')
DEFAULT_THREADS = 4
STATS_PERIOD_SEC = 1.0


class BusyStats:
    """Counts executor wait passes and turns them into per-second numbers (pure logic).

    ``record_pass`` is called from the executor thread, ``snapshot`` from the stats timer
    (another thread), so the counters are guarded by a lock.
    """

    def __init__(self, now: float, cpu_seconds: float) -> None:
        self._lock = threading.Lock()
        self._passes = 0
        self._empty = 0
        self._callbacks = 0
        self._last_time = now
        self._last_cpu = cpu_seconds

    def record_pass(self, empty: bool) -> None:
        """One finished pass of the executor's wait loop (empty = nothing was ready)."""
        with self._lock:
            self._passes += 1
            if empty:
                self._empty += 1

    def record_callback(self) -> None:
        """One subscription callback ran (the useful work)."""
        with self._lock:
            self._callbacks += 1

    def snapshot(self, now: float, cpu_seconds: float) -> Dict[str, float]:
        """Numbers since the previous snapshot, then start a new window.

        process_cpu_percent is the CPU time of the whole process (all threads) divided by the
        wall-clock time, so 100 means one full core; it can exceed 100 with several threads.
        """
        with self._lock:
            passes, empty, callbacks = self._passes, self._empty, self._callbacks
            self._passes = self._empty = self._callbacks = 0
            elapsed = now - self._last_time
            cpu = cpu_seconds - self._last_cpu
            self._last_time, self._last_cpu = now, cpu_seconds
        if elapsed <= 0:
            return {'wait_passes_per_sec': 0.0, 'empty_passes_per_sec': 0.0, 'empty_ratio': 0.0,
                    'callbacks_per_sec': 0.0, 'passes_per_callback': 0.0,
                    'process_cpu_percent': 0.0}
        return {
            'wait_passes_per_sec': round(passes / elapsed, 1),
            'empty_passes_per_sec': round(empty / elapsed, 1),
            'empty_ratio': round(empty / passes, 4) if passes else 0.0,
            'callbacks_per_sec': round(callbacks / elapsed, 1),
            'passes_per_callback': round(passes / callbacks, 1) if callbacks else 0.0,
            'process_cpu_percent': round(max(cpu, 0.0) / elapsed * 100.0, 1),
        }


def format_summary(stats: Dict[str, Any]) -> str:
    """The one-line log message (also what the JSON on the stats topic contains)."""
    return (f'executor={stats["executor"]} qos_events={stats["qos_events"]} '
            f'wait passes/s={stats["wait_passes_per_sec"]:.0f} '
            f'empty={stats["empty_ratio"] * 100:.1f}% '
            f'callbacks/s={stats["callbacks_per_sec"]:.0f} '
            f'cpu={stats["process_cpu_percent"]:.0f}%')


class PassCounter:
    """Mixin for an rclpy Executor: counts wait passes and how many of them found nothing.

    Put it *before* the real executor class: ``class X(PassCounter, MultiThreadedExecutor)``.
    Only public Executor methods are overridden (see the module docstring).
    """

    def __init__(self, *args: Any, stats: BusyStats, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._busy_stats = stats
        self._pass_open = False        # a pass has started and is not closed yet
        self._pass_got_work = False    # ... and has returned at least one callback so far

    def get_nodes(self):
        # Called once at the start of every pass of the wait loop, so it also marks the end of
        # the previous pass.
        if self._pass_open:
            self._busy_stats.record_pass(empty=not self._pass_got_work)
        self._pass_open = True
        self._pass_got_work = False
        return super().get_nodes()

    def wait_for_ready_callbacks(self, *args: Any, **kwargs: Any):
        work = super().wait_for_ready_callbacks(*args, **kwargs)  # raises when nothing to run
        self._pass_got_work = True
        return work


def make_executor(kind: str, stats: BusyStats, num_threads: int = DEFAULT_THREADS, **kwargs: Any):
    """A Single/MultiThreadedExecutor that reports its passes to ``stats``.

    ``kwargs`` (for example ``context=``) go to the executor's constructor.
    """
    from rclpy.executors import MultiThreadedExecutor, SingleThreadedExecutor

    if kind == 'single':
        class CountingSingle(PassCounter, SingleThreadedExecutor):
            pass
        return CountingSingle(stats=stats, **kwargs)
    if kind == 'multi':
        class CountingMulti(PassCounter, MultiThreadedExecutor):
            pass
        return CountingMulti(num_threads=num_threads or None, stats=stats, **kwargs)
    raise ValueError(f'executor must be one of {EXECUTORS}, got {kind!r}')


def normalize_qos_events(value: Any) -> str:
    """Turn the parameter value into "default" or "off".

    Beginner trap: in YAML 1.1 (``ros2 param``, launch files, PyYAML) a bare ``off`` is the
    boolean False, so ``-p qos_events:=off`` arrives as a bool. Accept that too.
    """
    if value is False:
        return 'off'
    if value is True:
        return 'default'
    return str(value).strip().lower()


def validate_options(executor: str, qos_events: str, work_ms: float, num_threads: int) -> None:
    if executor not in EXECUTORS:
        raise ValueError(f'executor must be one of {EXECUTORS}, got {executor!r}')
    if qos_events not in QOS_EVENT_MODES:
        raise ValueError(f'qos_events must be one of {QOS_EVENT_MODES}, got {qos_events!r}')
    if work_ms < 0:
        raise ValueError(f'work_ms must be >= 0, got {work_ms}')
    if num_threads < 0:
        raise ValueError(f'num_threads must be >= 0, got {num_threads}')


def main(args: Optional[list] = None) -> int:
    import rclpy
    from rcl_interfaces.msg import ParameterDescriptor
    from rclpy.callback_groups import MutuallyExclusiveCallbackGroup
    from rclpy.executors import ExternalShutdownException
    from rclpy.event_handler import SubscriptionEventCallbacks
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from std_msgs.msg import String

    class BusyDemoNode(Node):
        def __init__(self, stats: BusyStats) -> None:
            super().__init__('executor_busy_demo')
            self.executor_kind = str(self.declare_parameter('executor', 'multi').value)
            self.qos_events = normalize_qos_events(self.declare_parameter(
                'qos_events', 'default', ParameterDescriptor(dynamic_typing=True)).value)
            # dynamic_typing: `-p work_ms:=5` arrives as an integer; accept it as a number.
            self.work_sec = float(self.declare_parameter(
                'work_ms', 5.0, ParameterDescriptor(dynamic_typing=True)).value) / 1000.0
            self.num_threads = int(self.declare_parameter('num_threads', DEFAULT_THREADS).value)
            input_topic = str(self.declare_parameter('input_topic', '/busy_demo/in').value)
            stats_topic = str(self.declare_parameter('stats_topic', '/busy_demo/stats').value)
            validate_options(self.executor_kind, self.qos_events, self.work_sec * 1000.0,
                             self.num_threads)
            self.stats = stats

            # The one line this whole example is about. rclpy registers QoS event handlers on
            # every subscription unless told not to; "off" is the upstream workaround.
            if self.qos_events == 'off':
                event_callbacks = SubscriptionEventCallbacks(use_default_callbacks=False)
            else:
                event_callbacks = None  # rclpy's normal behaviour (default handlers)
            self.create_subscription(
                String, input_topic, self.on_message,
                QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE),
                event_callbacks=event_callbacks)

            self.pub = self.create_publisher(String, stats_topic, 10)
            # Its own callback group, so the report is not queued behind the subscription's
            # callback (the default group runs one callback at a time).
            self.create_timer(STATS_PERIOD_SEC, self.report,
                              callback_group=MutuallyExclusiveCallbackGroup())
            self.get_logger().info(
                f'executor_busy_demo: executor={self.executor_kind} qos_events={self.qos_events} '
                f'work_ms={self.work_sec * 1000.0:g} num_threads={self.num_threads}; '
                f'subscribing {input_topic}, reporting on {stats_topic}')

        def on_message(self, _msg: String) -> None:
            time.sleep(self.work_sec)  # "light work": sleeping uses no CPU, so CPU = overhead
            self.stats.record_callback()

        def report(self) -> None:
            numbers = self.stats.snapshot(time.monotonic(), time.process_time())
            payload = {'executor': self.executor_kind, 'qos_events': self.qos_events,
                       'num_threads': self.num_threads, 'work_ms': self.work_sec * 1000.0,
                       **numbers}
            self.pub.publish(String(data=json.dumps(payload)))
            self.get_logger().info(format_summary(payload))

    rclpy.init(args=args)
    stats = BusyStats(time.monotonic(), time.process_time())
    try:
        node = BusyDemoNode(stats)
    except ValueError as exc:
        print(f'executor_busy_demo: {exc}', file=sys.stderr)
        rclpy.try_shutdown()
        return 1
    executor = make_executor(node.executor_kind, stats, node.num_threads)
    executor.add_node(node)
    try:
        executor.spin()
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        executor.shutdown()
        node.destroy_node()
        rclpy.try_shutdown()
    return 0
