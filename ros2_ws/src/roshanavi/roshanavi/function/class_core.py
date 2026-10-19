"""What a class node does, without rclpy (unit-tested). docs/design/nodes.md.

    receive -> Python value (data_kinds) -> [multi-input: join latest values]
            -> queue a job on the ONE worker thread (serial.SerialExecutor)
    worker  -> instance.method(*args) -> None: nothing is sent
                                      -> exception: counted + reported with file:line
                                      -> value / dict: to messages (data_kinds) -> publish

Everything that runs the user's code happens on that one worker thread, in order: ``__init__``,
processing and action methods, ``on_param_change``, hot reload (a fresh import, the new instance,
state transfer) and ``close()``. The user needs no locks. A failure never stops the node: a
failed ``__init__`` waits for a fix, a failed reload or parameter change keeps the old instance.
"""

import inspect
import logging
import threading
import time
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from .. import data_kinds
from ..launcher.schema import ClassMethodSpec, ClassSpec
from ..transform.pipeline import Joiner
from . import class_params
from .class_params import UNSET, InitParam
from .core import ErrorLog, Port, stamp_of
from .loader import (LoadError, Problem, describe, missing_module_of, required_positional,
                     user_location)
from .class_loader import ClassLoader
from .serial import SerialExecutor

LOG = logging.getLogger('roshanavi.function')
APPLY_TIMEOUT_SEC = 10.0     # a parameter change waits this long for the worker
RELOAD_TIMEOUT_SEC = 60.0
CLOSE_TIMEOUT_SEC = 3.0      # close() of the instance when the node stops
RESULT_TEXT_MAX = 200
CLOSE_HOOKS = ('close', 'shutdown')
CLEARED_ON_RELOAD = ('import', 'init', 'state')

Publish = Callable[[int, int, Any], None]   # (method index, output index, message)


def resolve_binding_ports(method: ClassMethodSpec) -> Tuple[List[Port], List[Port]]:
    return ([Port(i.topic, *data_kinds.resolve(i.kind, i.type, receiving=True))
             for i in method.inputs],
            [Port(o.topic, *data_kinds.resolve(o.kind, o.type)) for o in method.outputs])


@dataclass
class _Binding:
    spec: ClassMethodSpec
    inputs: List[Port]
    outputs: List[Port]
    joiner: Optional[Joiner]
    calls: int = 0

    @property
    def keyed(self) -> bool:
        return bool(self.spec.outputs) and self.spec.outputs[0].key is not None


@dataclass
class ClassStats:
    received: int = 0
    calls: int = 0
    published: int = 0
    skipped: int = 0    # the method returned None (or there was no instance)
    waiting: int = 0    # multi-input: not every input has a value yet
    errors: int = 0
    reloads: int = 0
    dropped: int = 0    # the worker could not keep up: the queue was full
    resets: int = 0     # the instance was created again (reload / parameter change)

    def to_dict(self) -> Dict[str, int]:
        return asdict(self)


@dataclass
class _ActionRecord:
    count: int = 0
    last_at: Optional[float] = None
    ok: Optional[bool] = None
    result: Optional[str] = None
    error: Optional[Dict[str, Any]] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _hook(obj: Any, name: str) -> Optional[Callable[..., Any]]:
    fn = getattr(obj, name, None)
    return fn if callable(fn) else None


def _short(value: Any) -> Optional[str]:
    if value is None:
        return None
    text = repr(value)
    return text if len(text) <= RESULT_TEXT_MAX else text[:RESULT_TEXT_MAX - 1] + '…'


@dataclass
class _State:
    """Fields written on the worker thread and read by ``snapshot``."""

    instance: Any = None
    cls: Any = None
    init_problem: Optional[Problem] = None
    reload_problem: Optional[Problem] = None
    notice: Optional[Dict[str, Any]] = None
    values: Dict[str, Any] = field(default_factory=dict)
    params: List[InitParam] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


class ClassCore:
    def __init__(self, spec: ClassSpec, loader: ClassLoader, publish: Publish,
                 clock: Callable[[], float] = time.monotonic,
                 executor: Optional[SerialExecutor] = None,
                 on_change: Optional[Callable[[], None]] = None):
        self.spec = spec
        self.loader = loader
        self.executor = executor or SerialExecutor()
        self.bindings: List[_Binding] = []
        for method in spec.methods:
            inputs, outputs = resolve_binding_ports(method)
            joiner = Joiner([p.topic for p in inputs], method.trigger) \
                if method.call == 'multi_input' else None
            self.bindings.append(_Binding(method, inputs, outputs, joiner))
        self.stats = ClassStats()
        self.last_error: Optional[Dict[str, Any]] = None
        self.actions: Dict[str, _ActionRecord] = {a: _ActionRecord() for a in spec.actions}
        # Called (from any thread) when the declared parameters changed after a hot reload.
        self.on_signature: Optional[Callable[[List[Tuple[InitParam, Any]]], None]] = None
        self.on_change = on_change
        self._publish = publish
        self._clock = clock
        self._started = clock()
        self._lock = threading.Lock()       # stats / last_error / actions
        self._errors = ErrorLog(clock)
        self._closing = False
        self._pending_ticks: set = set()
        self._ignored_keys: Dict[int, List[str]] = {}
        self._s = _State()
        self._sync_params(initial=True)

    # ---- parameters (the __init__ arguments) ---------------------------------------------
    def _sync_params(self, initial: bool = False) -> None:
        """Re-read the ``__init__`` signature; keep the values of arguments that still exist."""
        s = self._s
        old = {p.name: p for p in s.params}
        params = class_params.init_params(self.loader.signature)
        values: Dict[str, Any] = {}
        warnings: List[str] = []
        for p in params:
            before = old.get(p.name)
            if before is not None and before.kind == p.kind and p.name in s.values:
                values[p.name] = s.values[p.name]
                continue
            values[p.name] = self._start_value(p, warnings)
        if self.loader.function is not None:
            known = {p.name for p in params}
            warnings += [f'params の {name} は {self.spec.class_name}.__init__ の引数にありません'
                         for name in self.spec.params if name not in known]
        s.params, s.values, s.warnings = params, values, warnings
        if not initial and self.on_signature is not None:
            self.on_signature(self.declarations())

    def _start_value(self, p: InitParam, warnings: List[str]) -> Any:
        if p.kind is None:
            return UNSET   # not a parameter: Python's default applies
        if p.name in self.spec.params:
            try:
                return class_params.spec_value(p.kind, self.spec.params[p.name], p.name)
            except ValueError as exc:
                warnings.append(f'params: {exc}')
        if p.has_default and p.default is not None:
            try:
                return class_params.from_default(p.kind, p.default)
            except ValueError as exc:
                warnings.append(f'{p.name} の既定値を使えません: {exc}')
        return UNSET

    def declarations(self) -> List[Tuple[InitParam, Any]]:
        """``[(argument, value or UNSET)]`` for the arguments that become ROS parameters."""
        return [(p, self._s.values.get(p.name, UNSET)) for p in self._s.params
                if p.kind is not None]

    def adopt_declared(self, values: Dict[str, Any]) -> None:
        """Use the values ROS declared them with (command-line overrides win)."""
        for name, value in values.items():
            if name in self._s.values:
                self._s.values[name] = value

    def in_worker(self) -> bool:
        return self.executor.on_worker()

    # ---- instance --------------------------------------------------------------------------
    def start(self) -> None:
        """Create the first instance on the worker (does not wait: ``__init__`` may be slow)."""
        self.executor.submit(self._start_job)

    def _start_job(self) -> None:
        if self._closing or self.loader.function is None:
            return
        try:
            self._s.instance = self._construct(self.loader.function, self._s.values)
            self._s.cls = self.loader.function
            self._s.init_problem = None
            LOG.info('クラスを初期化しました / created %s', self.spec.class_name)
        except Exception as exc:
            self._s.init_problem = self._init_problem(exc)
            self.report(self._s.init_problem)
        self._changed()

    def _construct(self, cls: Any, values: Dict[str, Any]) -> Any:
        kwargs = {}
        for p in self._s.params:
            value = values.get(p.name, UNSET)
            if value is not UNSET:
                kwargs[p.name] = value
            elif p.required:
                hint = f'パラメータ {p.name} を設定してください' if p.kind else \
                    f'{p.name} は ROS のパラメータにできない型なので既定値が必要です'
                raise _InitValueError(f'__init__ の引数 {p.name} の値がありません。{hint}')
        return cls(**kwargs)

    def _init_problem(self, exc: BaseException) -> Problem:
        resolved = self.loader.resolved
        where = user_location(exc, resolved.package.path, resolved.package.base_dir) \
            if resolved and not isinstance(exc, _InitValueError) else None
        text = str(exc) if isinstance(exc, _InitValueError) else describe(exc)
        return Problem('init', f'初期化に失敗しました: {text}', where or
                       self.loader.location_of_function(),
                       missing_module_of(exc, resolved.package.top if resolved else None))

    def _close_instance(self, instance: Any) -> None:
        """``close()`` (or ``shutdown()``) of an instance; an error is reported, not raised."""
        for name in CLOSE_HOOKS:
            fn = _hook(instance, name)
            if fn is None:
                continue
            try:
                fn()
            except Exception as exc:
                self.report(Problem('close', f'{name}() でエラーが起きました: {describe(exc)}',
                                    self._where(exc)))
            return

    def _where(self, exc: BaseException) -> Optional[str]:
        resolved = self.loader.resolved
        return user_location(exc, resolved.package.path, resolved.package.base_dir) \
            if resolved else None

    # ---- messages ---------------------------------------------------------------------------
    def on_message(self, binding: int, index: int, msg: Any) -> None:
        self._count('received')
        b = self.bindings[binding]
        port = b.inputs[index]
        try:
            value = data_kinds.to_python(port.kind, msg, port.type)
        except (data_kinds.KindError, ValueError, TypeError) as exc:
            self.report(Problem('convert', f'{port.topic}: {exc}', None))
            return
        stamp = stamp_of(msg)
        if b.joiner is None:
            self._enqueue(binding, [value], stamp)
            return
        state, latest = b.joiner.update(port.topic, value)
        if state == 'waiting':
            self._count('waiting')
        if latest is not None:
            self._enqueue(binding, [latest[p.topic] for p in b.inputs], stamp)

    def tick(self, binding: int) -> None:
        """Periodic call: queue one (at most one waits in the queue per method)."""
        with self._lock:
            if binding in self._pending_ticks:
                return
            self._pending_ticks.add(binding)
        if not self.executor.submit(lambda: self._tick_job(binding)):
            with self._lock:
                self._pending_ticks.discard(binding)
            self._count('dropped')

    def _tick_job(self, binding: int) -> None:
        with self._lock:
            self._pending_ticks.discard(binding)
        fn = self._method(binding)
        if fn is None:
            return
        try:
            signature = inspect.signature(fn)
        except (TypeError, ValueError):
            signature = None
        required, maximum = required_positional(signature)
        if required > 1:
            self.report(Problem('call', f'{self.bindings[binding].spec.method} needs {required} '
                                'arguments; a periodic method takes none (or the elapsed '
                                'seconds)', self.loader.location_of_function()))
            return
        args = [] if required == 0 and maximum == 0 else [self._clock() - self._started]
        self._call(binding, fn, args, None)

    def _enqueue(self, binding: int, args: Sequence[Any], stamp: Any) -> None:
        if not self.executor.submit(lambda: self._invoke(binding, list(args), stamp)):
            self._count('dropped')

    def _method(self, binding: int) -> Optional[Callable[..., Any]]:
        if self._closing:
            return None
        name = self.bindings[binding].spec.method
        instance = self._s.instance
        if instance is None:
            self._count('skipped')   # __init__ failed: the problem is in the status
            return None
        fn = _hook(instance, name)
        if fn is None:
            self.report(Problem('call', f'{self.spec.class_name} に {name} というメソッドがありません',
                                self.loader.location_of_function()))
        return fn

    def _invoke(self, binding: int, args: List[Any], stamp: Any) -> None:
        fn = self._method(binding)
        if fn is not None:
            self._call(binding, fn, args, stamp)

    def _call(self, binding: int, fn: Callable[..., Any], args: List[Any], stamp: Any) -> None:
        self._count('calls')
        self.bindings[binding].calls += 1
        try:
            result = fn(*args)
        except Exception as exc:  # the user's bug: report it, keep the node running
            self.report(Problem('call', describe(exc), self._where(exc), missing_module_of(
                exc, self.loader.resolved.package.top if self.loader.resolved else None)))
            return
        self._send_result(binding, result, stamp)

    def _send_result(self, binding: int, result: Any, stamp: Any) -> None:
        b = self.bindings[binding]
        if not b.outputs:
            return   # a method with side effects only
        if result is None:
            self._count('skipped')
            return
        pairs: List[Tuple[int, Any]]
        if b.keyed:
            if not isinstance(result, dict):
                self.report(Problem('convert', f'{b.spec.method} は dict を返す必要があります '
                                    '(出力が key ごとに分かれているため)。返した値: '
                                    f'{type(result).__name__}', self.loader.location_of_function()))
                return
            outputs = {o.key: i for i, o in enumerate(b.spec.outputs)}
            self._ignored_keys[binding] = sorted(k for k in result if k not in outputs)[:8]
            pairs = [(i, result[key]) for key, i in outputs.items()
                     if result.get(key) is not None]
            if not pairs:
                self._count('skipped')
                return
        else:
            pairs = [(0, result)]
        for index, value in pairs:
            self._publish_one(binding, index, value, stamp)

    def _publish_one(self, binding: int, index: int, value: Any, stamp: Any) -> None:
        port = self.bindings[binding].outputs[index]
        if not port.topic:  # this output is not wired yet (map wiring): nothing to send
            return
        try:
            msg = data_kinds.from_python(port.kind, value, port.type, stamp)
        except data_kinds.KindError as exc:
            self.report(Problem('convert', f'{port.topic}: {exc}',
                                self.loader.location_of_function()))
            return
        try:
            self._publish(binding, index, msg)
        except Exception as exc:  # rclpy raises several types (context shut down, ...)
            self.report(Problem('publish', f'publish failed: {exc}', None))
            return
        self._count('published')

    # ---- action methods ---------------------------------------------------------------------
    def call_action(self, method: str) -> bool:
        """Queue a call of an action method (button, topic or scenario step)."""
        if method not in self.actions:
            return False
        if self.executor.submit(lambda: self._action_job(method)):
            return True
        self._count('dropped')
        return False

    def _action_job(self, method: str) -> None:
        if self._closing:
            return
        started = time.time()
        error: Optional[Problem] = None
        result: Any = None
        instance = self._s.instance
        fn = _hook(instance, method) if instance is not None else None
        if instance is None:
            error = Problem('action', 'インスタンスがありません (初期化に失敗しています)',
                            self.loader.location_of_function())
        elif fn is None:
            error = Problem('action', f'{self.spec.class_name} に {method} というメソッドがありません',
                            self.loader.location_of_function())
        else:
            try:
                result = fn()
            except Exception as exc:
                error = Problem('action', f'{method}() でエラーが起きました: {describe(exc)}',
                                self._where(exc))
        if error is not None:
            self.report(error)
        with self._lock:
            record = self.actions[method]
            record.count += 1
            record.last_at, record.ok = started, error is None
            record.result = _short(result) if error is None else None
            record.error = {**error.to_dict(), 'at': started} if error else None
        self._changed()

    # ---- parameter changes ------------------------------------------------------------------
    def apply_params(self, changes: Dict[str, Any]) -> Tuple[bool, str]:
        """Apply new parameter values (Python values); ``(False, reason)`` when refused."""
        try:
            return self.executor.run(lambda: self._apply_job(changes), APPLY_TIMEOUT_SEC)
        except TimeoutError:
            return False, 'クラスの処理が終わらないため、パラメータを反映できませんでした'

    def _apply_job(self, changes: Dict[str, Any]) -> Tuple[bool, str]:
        s = self._s
        instance = s.instance
        hook = _hook(instance, 'on_param_change') if instance is not None else None
        if hook is not None:
            for name, value in changes.items():
                try:
                    hook(name, value)
                except Exception as exc:
                    problem = Problem('param', f'on_param_change({name}) でエラーが起きました: '
                                      f'{describe(exc)}', self._where(exc))
                    self.report(problem)
                    return False, problem.message
                s.values[name] = value
            self._changed()
            return True, ''
        values = {**s.values, **changes}
        try:
            new = self._construct(self.loader.function, values)
        except Exception as exc:
            problem = self._init_problem(exc)
            problem = Problem('param', problem.message, problem.location)
            self.report(problem)
            return False, problem.message
        old, s.instance, s.cls, s.values = s.instance, new, self.loader.function, values
        s.init_problem = None
        if old is not None:
            self._close_instance(old)
        self._reset('param')
        return True, ''

    # ---- hot reload -------------------------------------------------------------------------
    def reload(self) -> None:
        """Fresh import + new instance on the worker (raises LoadError; the old one then runs on)."""
        try:
            self.executor.run(self._reload_job, RELOAD_TIMEOUT_SEC)
        except TimeoutError:
            raise LoadError(Problem('import', 'クラスの処理が終わらないため、読み直せません',
                                    None)) from None
        except LoadError:
            raise
        except Exception as exc:  # a bug here must not end the file watcher
            raise LoadError(Problem('import', f'読み直しに失敗しました: {describe(exc)}', None)) from exc

    def _reload_job(self) -> None:
        s = self._s
        self.loader.load()   # LoadError: modules and class are put back, nothing else changes
        new_cls = self.loader.function
        self._sync_params()
        old = s.instance
        transfer = old is not None and _hook(old, 'get_state') is not None \
            and _hook(new_cls, 'set_state') is not None
        try:
            state = old.get_state() if transfer else None
        except Exception as exc:
            self._fail_reload('state', f'get_state() でエラーが起きました (古い状態のまま動き続けます): '
                              f'{describe(exc)}', exc)
        try:
            new = self._construct(new_cls, s.values)
        except Exception as exc:
            problem = self._init_problem(exc)
            self._fail_reload('init', problem.message + ' (古いインスタンスのまま動き続けます)',
                              exc, problem.location)
        if transfer:
            try:
                new.set_state(state)
            except Exception as exc:
                self._close_instance(new)
                self._fail_reload('state', f'set_state() でエラーが起きました (古いインスタンスのまま'
                                  f'動き続けます): {describe(exc)}', exc)
        s.instance, s.cls = new, new_cls
        s.reload_problem = s.init_problem = None
        if old is not None:
            self._close_instance(old)
            self._reset('reload', kept=transfer)
        self._changed()

    def _fail_reload(self, kind: str, message: str, exc: BaseException,
                     location: Optional[str] = None) -> None:
        problem = Problem(kind, message, location or self._where(exc))
        self._s.reload_problem = problem
        raise LoadError(problem) from exc

    def _reset(self, reason: str, kept: bool = False) -> None:
        with self._lock:
            self.stats.resets += 0 if kept else 1
            self._s.notice = {'kind': 'kept' if kept else 'reset', 'reason': reason,
                              'at': time.time()}
        LOG.info('状態を引き継ぎました / state kept (%s)' if kept else
                 '状態をリセットしました / state reset (%s)', reason)
        self._changed()

    def on_reload(self, problem: Optional[Problem]) -> None:
        if problem is not None:
            self.report(problem)
            return
        with self._lock:
            self.stats.reloads += 1
            if self.last_error and self.last_error.get('kind') in CLEARED_ON_RELOAD:
                self.last_error = None
        LOG.info('クラスを読み直しました / reloaded %s.%s', self.spec.module, self.spec.class_name)

    # ---- stop ---------------------------------------------------------------------------------
    def close(self) -> None:
        """``close()`` / ``shutdown()`` of the instance (bounded wait), then stop the worker."""
        if self._closing:
            return
        self._closing = True
        try:
            self.executor.run(self._close_job, CLOSE_TIMEOUT_SEC)
        except TimeoutError:
            LOG.error('close() が %g 秒で終わりませんでした / close() did not finish in %g s; '
                      'stopping anyway', CLOSE_TIMEOUT_SEC, CLOSE_TIMEOUT_SEC)
        finally:
            self.executor.stop()

    def _close_job(self) -> None:
        instance, self._s.instance = self._s.instance, None
        if instance is not None:
            self._close_instance(instance)

    # ---- bookkeeping --------------------------------------------------------------------------
    def _changed(self) -> None:
        if self.on_change is not None:
            try:
                self.on_change()
            except Exception:  # the status file must never break a call
                LOG.exception('status update failed')

    def _count(self, name: str) -> None:
        with self._lock:
            setattr(self.stats, name, getattr(self.stats, name) + 1)

    def report(self, problem: Problem) -> None:
        """Count an error, keep it for the UI and log it (at most one line per 5 s)."""
        with self._lock:
            if problem.kind != 'import':
                self.stats.errors += 1
            self.last_error = {**problem.to_dict(), 'at': time.time()}
        self._errors.emit('クラスでエラーが起きました / the class failed', problem.text())

    def snapshot(self) -> Dict[str, Any]:
        s, loader = self._s, self.loader
        problem = loader.problem or s.reload_problem or s.init_problem
        if self._closing:
            state = 'stopped'
        elif loader.function is None:
            state = 'import_error'
        elif s.instance is None:
            state = 'init_error' if s.init_problem is not None else 'starting'
        elif loader.problem is not None or s.reload_problem is not None:
            state = 'reload_error'
        else:
            state = 'running'
        with self._lock:
            return {
                'kind': 'class', 'state': state,
                'class': f'{self.spec.module}.{self.spec.class_name}',
                'signature': f'{self.spec.class_name}{loader.signature}'
                if loader.signature is not None else None,
                'location': loader.location_of_function(), 'loads': loader.loads,
                'problem': problem.to_dict() if problem else None,
                'stats': self.stats.to_dict(), 'last_error': self.last_error,
                'params': [{'name': p.name, 'kind': p.kind, 'annotation': p.annotation,
                            'required': p.required, 'value': _jsonable(s.values.get(p.name, UNSET))}
                           for p in s.params],
                'warnings': list(s.warnings),
                'methods': [{'method': b.spec.method, 'call': b.spec.call, 'calls': b.calls,
                             'inputs': [asdict(p) for p in b.inputs],
                             'outputs': [asdict(p) for p in b.outputs],
                             'ignored_keys': self._ignored_keys.get(i, [])}
                            for i, b in enumerate(self.bindings)],
                'actions': {name: {**rec.to_dict(), 'topic': f'~/{name}'}
                            for name, rec in self.actions.items()},
                'notice': s.notice,
                'environment': loader.environment, 'notices': loader.notices,
                'import_seconds': loader.import_seconds,
                'hooks': {name: s.instance is not None and _hook(s.instance, name) is not None
                          for name in ('close', 'shutdown', 'get_state', 'set_state',
                                       'on_param_change')}}


class _InitValueError(Exception):
    """A required ``__init__`` argument has no value (a message for the user, not a traceback)."""


def _jsonable(value: Any) -> Any:
    return None if value is UNSET else value
