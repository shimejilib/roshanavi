"""A transform node's ROS side: subscriptions, the pipeline and the publisher.

``mode: relay`` subscribes *serialized* (``raw=True``) and publishes the same
bytes, so any type (also images and point clouds) is forwarded without being
deserialized. ``mode: map`` deserializes each input, wraps it in a read-only
:class:`~roshanavi.msg_view.MsgView` and computes the output with the safe
evaluator (:mod:`.compute`).

Callbacks may run on several executor threads at once; the counters and the
pipeline objects are protected by locks.
"""

import logging
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .. import msgutil
from ..launcher.schema import TransformSpec
from ..msg_view import MsgView
from ..ros_runtime import RosRuntime, make_qos
from .compute import Computer, FieldError
from .pipeline import DelayQueue, Gate, Joiner, Stats

LOG = logging.getLogger('roshanavi.transform')

# Inputs are read best effort: it matches reliable and best-effort publishers alike.
INPUT_QOS = {'reliability': 'best_effort', 'durability': 'volatile', 'depth': 10}


class TransformConfigError(ValueError):
    """The spec's expressions do not compile (exit code 2 of the node)."""

    def __init__(self, errors: List[FieldError]):
        super().__init__('; '.join(f'{e.path}: {e.message}' for e in errors))
        self.errors = errors


class TransformRunner:
    def __init__(self, spec: TransformSpec, runtime: RosRuntime,
                 rng: Optional[random.Random] = None,
                 clock: Callable[[], float] = time.monotonic):
        self.spec = spec
        self.stats = Stats()
        self._runtime = runtime
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()
        self._error_logged_at: Optional[float] = None
        rng = rng or random.Random()
        self._computer: Optional[Computer] = None
        if spec.mode == 'map':
            self._computer = Computer(spec, rng=rng)
            if not self._computer.ok:
                raise TransformConfigError(self._computer.compile_errors)
        self._gate = Gate(spec.drop_ratio, spec.throttle_hz, spec.delay, rng)
        self._joiner = Joiner([i.alias or 'msg' for i in spec.inputs], spec.trigger) \
            if len(spec.inputs) > 1 else None
        self._out_type = spec.output.type or spec.inputs[0].type
        self._publisher = runtime.create_publisher(
            msgutil.resolve_type(self._out_type), spec.output.topic,
            make_qos(**spec.output.qos.model_dump()))
        self._delay = DelayQueue(self._publish, self._on_overflow, clock) if spec.delay else None
        self._subscriptions: List[Any] = []
        self._subscribe()

    def _subscribe(self) -> None:
        qos = make_qos(**INPUT_QOS)
        for inp in self.spec.inputs:
            alias = inp.alias or 'msg'
            msg_type = msgutil.resolve_type(inp.type)
            if self.spec.mode == 'relay':
                callback = self.on_raw
            else:
                def callback(msg: Any, alias: str = alias) -> None:
                    self.on_message(alias, msg)
            self._subscriptions.append(self._runtime.create_subscription(
                msg_type, inp.topic, callback, qos, raw=self.spec.mode == 'relay'))

    # ---- callbacks ---------------------------------------------------------
    def on_raw(self, data: bytes) -> None:
        """Relay: forward the serialized message unchanged (after drop / throttle / delay)."""
        self._count('received')
        if self._gate.drop():
            self._count('dropped')
            return
        self._emit(data)

    def on_message(self, alias: str, msg: Any) -> None:
        received = self._count('received')
        values: Optional[Dict[str, MsgView]]
        if self._joiner is None:
            if self._gate.drop():  # before converting: a dropped message costs nothing
                self._count('dropped')
                return
            values = {alias: MsgView.from_message(msg)}
        else:
            state, values = self._joiner.update(alias, MsgView.from_message(msg))
            if state == 'waiting':
                self._count('waiting')
            if values is None:
                return
            if self._gate.drop():
                self._count('dropped')
                return
        variables = {'i': received - 1, 't': self._clock() - self._started, 'now': time.time()}
        outcome = self._computer.compute(values, variables)
        if outcome.errors:
            self._fail('; '.join(f'{e.path}: {e.message}' for e in outcome.errors))
            return
        if not outcome.passed:
            self._count('filtered')
            return
        try:
            out = msgutil.build(self._out_type, outcome.output)
        except msgutil.MsgUtilError as exc:
            self._fail(str(exc))
            return
        self._emit(out)

    def _emit(self, item: Any) -> None:
        if self._gate.throttle(self._clock()):
            self._count('throttled')
            return
        delay = self._gate.delay_sec()
        if self._delay is not None and delay > 0:
            self._delay.put(item, delay)
        else:
            self._publish(item)

    def _publish(self, item: Any) -> None:
        try:
            self._publisher.publish(item)
        except Exception as exc:  # rclpy raises several types (context shut down, ...)
            self._fail(f'publish failed: {exc}')
            return
        self._count('published')

    # ---- bookkeeping -------------------------------------------------------
    def _count(self, name: str) -> int:
        with self._lock:
            value = getattr(self.stats, name) + 1
            setattr(self.stats, name, value)
            return value

    def _on_overflow(self) -> None:
        self._count('overflow')

    def _fail(self, message: str) -> None:
        now = self._clock()
        with self._lock:
            self.stats.errors += 1
            self.stats.last_error = message
            log_it = self._error_logged_at is None or now - self._error_logged_at > 10.0
            if log_it:
                self._error_logged_at = now
        if log_it:  # at most one error line per 10 s (a bad field fails every message)
            LOG.error('cannot transform a message: %s', message)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self.stats.to_dict()

    def close(self) -> None:
        if self._delay is not None:
            self._delay.close()
        for sub in self._subscriptions:
            self._runtime.destroy_subscription(sub)
        self._subscriptions = []
        self._runtime.destroy_publisher(self._publisher)
