"""A function node's ROS side: subscriptions, the periodic thread and the publisher."""

import json
import logging
import os
import threading
import time
from typing import Any, Callable, List, Optional

from .. import msgutil
from ..launcher.dummy_config import write_atomic
from ..launcher.schema import FunctionSpec
from ..ros_runtime import RosRuntime, make_qos
from .core import FunctionCore
from .loader import FunctionLoader

LOG = logging.getLogger('roshanavi.function')

# Inputs are read best effort: it matches reliable and best-effort publishers alike.
INPUT_QOS = {'reliability': 'best_effort', 'durability': 'volatile', 'depth': 10}


def periodic_loop(stop: threading.Event, rate_hz: float, tick: Callable[[], None]) -> None:
    """Call ``tick`` at ``rate_hz`` until ``stop`` is set (skips ahead when it falls behind)."""
    period = 1.0 / rate_hz
    due = time.monotonic() + period
    while not stop.wait(max(0.0, due - time.monotonic())):
        tick()
        due += period
        if due < time.monotonic() - period:  # fell far behind (slow function): skip ahead
            due = time.monotonic() + period


class FunctionRunner:
    def __init__(self, spec: FunctionSpec, runtime: RosRuntime, loader: FunctionLoader):
        self.spec = spec
        self._runtime = runtime
        self._publisher: Any = None
        self.core = FunctionCore(spec, loader, self._send)
        # An empty topic is a port that is not wired yet (map wiring): no publisher / subscription.
        if spec.output.topic:
            self._publisher = runtime.create_publisher(
                msgutil.resolve_type(self.core.output.type), spec.output.topic,
                make_qos(**spec.output.qos.model_dump()))
        self._subscriptions: List[Any] = []
        qos = make_qos(**INPUT_QOS)
        for index, port in enumerate(self.core.inputs):
            if not port.topic:
                continue
            def callback(msg: Any, index: int = index) -> None:
                self.core.on_message(index, msg)
            self._subscriptions.append(runtime.create_subscription(
                msgutil.resolve_type(port.type), port.topic, callback, qos))
        self._stop = threading.Event()
        self._timer: Optional[threading.Thread] = None
        if spec.call == 'periodic':
            self._timer = threading.Thread(target=self._periodic, name='function-periodic',
                                           daemon=True)
            self._timer.start()

    def _send(self, msg: Any) -> None:
        self._publisher.publish(msg)

    def _periodic(self) -> None:
        periodic_loop(self._stop, float(self.spec.rate_hz or 1.0), self.core.tick)

    def close(self) -> None:
        self._stop.set()
        if self._timer is not None:
            self._timer.join(timeout=2.0)
        for sub in self._subscriptions:
            self._runtime.destroy_subscription(sub)
        self._subscriptions = []
        if self._publisher is not None:
            self._runtime.destroy_publisher(self._publisher)


class StatusFile:
    """The node's status as JSON, read by the server for the UI (written when it changes)."""

    def __init__(self, path: Optional[str]):
        self.path = path
        self._last: Optional[str] = None

    def write(self, status: dict) -> None:
        if not self.path:
            return
        text = json.dumps({**status, 'pid': os.getpid()}, sort_keys=True, ensure_ascii=False)
        if text == self._last:
            return
        try:
            write_atomic(self.path, text)
            self._last = text
        except OSError as exc:
            LOG.warning('cannot write the status file %s: %s', self.path, exc)
