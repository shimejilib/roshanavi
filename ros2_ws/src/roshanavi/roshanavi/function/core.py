"""What a function node does with each message, without rclpy (unit-tested).

    receive -> to a Python value (data_kinds) -> [multi-input: join latest values]
            -> call the function -> None: nothing is sent
                                 -> exception: counted + reported with file:line, node keeps going
                                 -> value: to a message (data_kinds) -> publish

Calls are serialized (user code need not be thread-safe). The function object
is read from the loader at every call, so a hot reload applies to the next
message.
"""

import logging
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import data_kinds
from ..launcher.schema import FunctionSpec
from ..transform.pipeline import Joiner
from .loader import FunctionLoader, Problem, describe, required_positional, user_location

LOG = logging.getLogger('roshanavi.function')
ERROR_LOG_EVERY_SEC = 5.0


@dataclass(frozen=True)
class Port:
    topic: str
    kind: str
    type: str


def resolve_ports(spec: FunctionSpec) -> Tuple[List[Port], Port]:
    """Input / output ports with the ROS type each kind resolves to (data_kinds)."""
    inputs = [Port(i.topic, *data_kinds.resolve(i.kind, i.type)) for i in spec.inputs]
    out = spec.output
    return inputs, Port(out.topic, *data_kinds.resolve(out.kind, out.type))


@dataclass
class FunctionStats:
    received: int = 0
    calls: int = 0
    published: int = 0
    skipped: int = 0    # the function returned None
    waiting: int = 0    # multi-input: not every input has a value yet
    errors: int = 0
    reloads: int = 0

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


def _stamp_of(msg: Any) -> Any:
    header = getattr(msg, 'header', None)
    stamp = getattr(header, 'stamp', None)
    return stamp if stamp is not None and (stamp.sec or stamp.nanosec) else None


class FunctionCore:
    def __init__(self, spec: FunctionSpec, loader: FunctionLoader,
                 publish: Callable[[Any], None], clock: Callable[[], float] = time.monotonic,
                 ports: Optional[Tuple[List[Port], Port]] = None):
        self.spec = spec
        self.loader = loader
        self.inputs, self.output = ports or resolve_ports(spec)
        self.stats = FunctionStats()
        self.last_error: Optional[Dict[str, Any]] = None
        self._publish = publish
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()       # stats
        self._call_lock = threading.Lock()  # one call at a time
        self._logged_at: Optional[float] = None
        self._suppressed = 0
        self._joiner = Joiner([p.topic for p in self.inputs], spec.trigger) \
            if spec.call == 'multi_input' else None

    # ---- entry points -------------------------------------------------------------
    def on_message(self, index: int, msg: Any) -> None:
        self._count('received')
        port = self.inputs[index]
        try:
            value = data_kinds.to_python(port.kind, msg, port.type)
        except (data_kinds.KindError, ValueError, TypeError) as exc:
            self.report(Problem('convert', f'{port.topic}: {exc}', None))
            return
        stamp = _stamp_of(msg)
        if self._joiner is None:
            self._invoke([value], stamp)
            return
        state, latest = self._joiner.update(port.topic, value)
        if state == 'waiting':
            self._count('waiting')
        if latest is not None:
            self._invoke([latest[p.topic] for p in self.inputs], stamp)

    def tick(self) -> None:
        """Periodic call: no argument, or the seconds since start when it takes one."""
        required, maximum = required_positional(self.loader.signature)
        args: List[Any] = [] if required == 0 and maximum == 0 else [self._clock() - self._started]
        if required > 1:
            self.report(Problem('call', f'{self.spec.function} needs {required} arguments; a '
                                'periodic function takes none (or the elapsed seconds)',
                                self.loader.location_of_function()))
            return
        self._invoke(args, None)

    # ---- the call --------------------------------------------------------------------
    def _invoke(self, args: Sequence[Any], stamp: Any) -> None:
        function = self.loader.function
        if function is None:
            return  # not imported yet (the import error is in the status)
        resolved = self.loader.resolved
        with self._call_lock:
            self._count('calls')
            try:
                result = function(*args)
            except Exception as exc:  # the user's bug: report it, keep the node running
                where = user_location(exc, resolved.package.path, resolved.package.base_dir) \
                    if resolved else None
                self.report(Problem('call', describe(exc), where))
                return
        if result is None:
            self._count('skipped')
            return
        try:
            msg = data_kinds.from_python(self.output.kind, result, self.output.type, stamp)
        except data_kinds.KindError as exc:
            self.report(Problem('convert', str(exc), self.loader.location_of_function()))
            return
        try:
            self._publish(msg)
        except Exception as exc:  # rclpy raises several types (context shut down, ...)
            self.report(Problem('publish', f'publish failed: {exc}', None))
            return
        self._count('published')

    # ---- bookkeeping -------------------------------------------------------------
    def _count(self, name: str) -> None:
        with self._lock:
            setattr(self.stats, name, getattr(self.stats, name) + 1)

    def report(self, problem: Problem) -> None:
        """Count an error, keep it for the UI and log it (at most one line per 5 s)."""
        now = self._clock()
        with self._lock:
            if problem.kind != 'import':
                self.stats.errors += 1
            self.last_error = {**problem.to_dict(), 'at': time.time()}
            log_it = self._logged_at is None or now - self._logged_at >= ERROR_LOG_EVERY_SEC
            suppressed, self._suppressed = (self._suppressed, 0) if log_it else \
                (0, self._suppressed + 1)
            if log_it:
                self._logged_at = now
        if log_it:
            more = f' (+{suppressed} more since the last report)' if suppressed else ''
            LOG.error('関数でエラーが起きました / the function failed: %s%s', problem.text(), more)

    def on_reload(self, problem: Optional[Problem]) -> None:
        if problem is not None:
            self.report(problem)
            return
        with self._lock:
            self.stats.reloads += 1
            if self.last_error and self.last_error.get('kind') == 'import':
                self.last_error = None
        LOG.info('関数を読み直しました / reloaded %s.%s', self.spec.module, self.spec.function)

    def snapshot(self) -> Dict[str, Any]:
        loader = self.loader
        state = 'running' if loader.function is not None else 'import_error'
        if loader.problem is not None and loader.function is not None:
            state = 'reload_error'  # the old function keeps running
        with self._lock:
            return {'state': state, 'function': f'{self.spec.module}.{self.spec.function}',
                    'signature': f'{self.spec.function}{loader.signature}'
                    if loader.signature is not None else None,
                    'location': loader.location_of_function(), 'loads': loader.loads,
                    'problem': loader.problem.to_dict() if loader.problem else None,
                    'stats': self.stats.to_dict(), 'last_error': self.last_error,
                    'inputs': [asdict(p) for p in self.inputs], 'output': asdict(self.output)}
