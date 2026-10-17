"""Composition root: runtime + graph + traffic + injector + echo.

A single 1 s housekeeping timer (executor thread) collects the ROS graph,
updates the graph snapshot, syncs traffic subscriptions and ticks the hz
history. Everything the API serves is read from those cached snapshots.
"""

import logging
import time
from typing import Any, Callable, Optional, Sequence

from . import graph
from .echo import EchoManager
from .injector import Injector
from .ros_runtime import RosRuntime
from .traffic import DEFAULT_WINDOW_SEC, TrafficMonitor

LOG = logging.getLogger(__name__)

HOUSEKEEPING_PERIOD_SEC = 1.0


class Lab:
    def __init__(self, data_dir: str = '/data', show_self: bool = False,
                 node_name: str = 'roshanavi', window_sec: float = DEFAULT_WINDOW_SEC,
                 traffic_exclude: Sequence[str] = (), monitor_heavy: bool = False,
                 period_sec: float = HOUSEKEEPING_PERIOD_SEC,
                 clock: Callable[[], float] = time.monotonic):
        self.data_dir = data_dir
        self.runtime = RosRuntime(node_name)
        self.graph = graph.GraphMonitor(show_self=show_self)
        self.traffic = TrafficMonitor(self.runtime, window_sec=window_sec,
                                      exclude=traffic_exclude, clock=clock,
                                      monitor_heavy=monitor_heavy)
        self.injector = Injector(self.runtime, data_dir, clock=clock)
        self.echo = EchoManager(self.runtime)
        self._period = period_sec
        self._timer: Any = None
        self.housekeeping_runs = 0

    def start(self) -> 'Lab':
        self.runtime.start()
        self._timer = self.runtime.create_timer(self._period, self.housekeeping)
        return self

    def housekeeping(self) -> None:
        """Executor-thread callback; never raises (a crash would kill the timer)."""
        try:
            raw = graph.collect(self.runtime)
            self.graph.update(raw, self.injector.list())
            self.traffic.sync(raw)
            self.traffic.tick()
            self.housekeeping_runs += 1
        except Exception:  # keep the loop alive but make failures visible
            LOG.exception('housekeeping failed')

    def stop(self) -> None:
        if not self.runtime.running:
            return
        if self._timer is not None:
            self.runtime.destroy_timer(self._timer)
            self._timer = None
        self.injector.close()
        self.echo.close()
        self.traffic.close()
        self.runtime.stop()

    def __enter__(self) -> 'Lab':
        return self.start()

    def __exit__(self, *exc: Optional[Any]) -> None:
        self.stop()
