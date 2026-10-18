"""Lifecycle of one launch target: start / stop / restart / optional auto-restart.

States: ``stopped`` (never started or stopped by the user), ``starting``
(first few seconds after spawn), ``running``, ``exited`` (code 0 on its own),
``crashed`` (non-zero on its own), ``invalid`` (the spec no longer validates,
e.g. the package disappeared). Each spawn has a generation number so a late
exit callback of an old process never overwrites the state of a new one.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Union

from .env import LOG_ENV
from .errors import LauncherError
from .logbuf import LogBuffer
from .process import ProcessRunner
from .schema import ClassSpec, DummySpec, FunctionSpec, TargetSpec, TransformSpec, clean_dict

LOG = logging.getLogger(__name__)

STARTING_SEC = 2.0
BACKOFF_BASE_SEC = 1.0
BACKOFF_MAX_SEC = 30.0
HEALTHY_RUN_SEC = 30.0

Spec = Union[TargetSpec, DummySpec, TransformSpec, FunctionSpec, ClassSpec]


def kind_of(spec: Spec) -> str:
    if isinstance(spec, DummySpec):
        return 'dummy'
    if isinstance(spec, TransformSpec):
        return 'transform'
    if isinstance(spec, FunctionSpec):
        return 'function'
    if isinstance(spec, ClassSpec):
        return 'class'
    return spec.kind


def role_of(spec: Spec) -> str:
    """Map role: dummy (input node), transform (変換ノード), function (関数ノード; class nodes
    share this role and colour), or the target's mine / dependency."""
    if isinstance(spec, ClassSpec):
        return 'function'
    if isinstance(spec, (DummySpec, TransformSpec, FunctionSpec)):
        return kind_of(spec)
    return spec.role


class Target:
    def __init__(self, spec: Spec, build_argv: Callable[[Spec], List[str]],
                 env: Callable[[], Dict[str, str]], cwd: str,
                 timeouts: Sequence[float], problem: Optional[str] = None):
        self.spec = spec
        self.log = LogBuffer()
        self.problem = problem
        self._build_argv = build_argv
        self._env = env
        self._cwd = cwd
        self._timeouts = timeouts
        self._lock = threading.RLock()
        self._runner: Optional[ProcessRunner] = None
        self._generation = 0
        self._state = 'invalid' if problem else 'stopped'
        self._exit_code: Optional[int] = None
        self._started_wall: Optional[float] = None
        self._restart_count = 0
        self._crash_streak = 0
        self._pending: Optional[threading.Timer] = None
        self._stale_spec = False

    @property
    def id(self) -> str:
        return self.spec.id

    # ---- lifecycle -------------------------------------------------------
    def start(self) -> None:
        with self._lock:
            if self._runner is not None and self._runner.alive():
                raise LauncherError('already_running', f'{self.id} is already running', 409)
            self._cancel_pending()
            try:
                argv = self._build_argv(self.spec)
            except LauncherError as exc:
                self.problem, self._state = str(exc), 'invalid'
                raise
            self.problem = None
            self._generation += 1
            generation = self._generation
            runner = ProcessRunner(argv, self._spec_env(), self._cwd, self.log,
                                   on_exit=lambda code: self._on_exit(generation, code),
                                   timeouts=self._timeouts)
            runner.start()
            self._runner, self._state, self._exit_code = runner, 'running', None
            self._started_wall, self._stale_spec = time.time(), False
        LOG.info('target %s started (pid %s)', self.id, runner.pid)

    def _spec_env(self) -> Dict[str, str]:
        """The launcher's child environment plus the target's own ``env`` (validated when the
        command was built; roshanavi's logging settings stay as they are)."""
        env = self._env()
        extra = getattr(self.spec, 'env', None) or {}
        return {**env, **extra, **{k: env[k] for k in LOG_ENV if k in env}} if extra else env

    def stop(self) -> None:
        with self._lock:
            self._cancel_pending()
            runner = self._runner
            self._generation += 1  # the exit of this runner is "requested"
            if self._state != 'invalid':
                self._state = 'stopped'
        if runner is not None and runner.alive():
            code = runner.stop()
            with self._lock:
                self._exit_code = code
            LOG.info('target %s stopped (exit %s)', self.id, code)

    def restart(self) -> None:
        self.stop()
        self.start()
        with self._lock:
            self._restart_count += 1

    def update_spec(self, spec: Spec) -> None:
        with self._lock:
            self.spec = spec
            self._stale_spec = self._runner is not None and self._runner.alive()
            if self._state == 'invalid':
                self._state, self.problem = 'stopped', None

    def _on_exit(self, generation: int, code: int) -> None:
        with self._lock:
            if generation != self._generation:
                return  # stopped by us or superseded by a newer process
            self._exit_code = code
            self._state = 'exited' if code == 0 else 'crashed'
            ran = time.monotonic() - (self._runner.started_at if self._runner else 0.0)
            self._crash_streak = 0 if ran > HEALTHY_RUN_SEC else self._crash_streak + 1
            if self._state == 'crashed' and getattr(self.spec, 'auto_restart', False):
                delay = min(BACKOFF_MAX_SEC, BACKOFF_BASE_SEC * 2 ** (self._crash_streak - 1))
                self.log.append('system', f'[crashed; restarting in {delay:.0f} s]')
                self._pending = threading.Timer(delay, self._auto_restart, args=(generation,))
                self._pending.daemon = True
                self._pending.start()
        if code:
            LOG.warning('target %s exited with %s', self.id, code)

    def _auto_restart(self, generation: int) -> None:
        with self._lock:
            if generation != self._generation or self._state != 'crashed':
                return
            self._pending = None
            try:
                self.start()
                self._restart_count += 1
            except LauncherError as exc:
                LOG.error('auto-restart of %s failed: %s', self.id, exc)
                self.log.append('system', f'[auto-restart failed: {exc}]')

    def _cancel_pending(self) -> None:
        if self._pending is not None:
            self._pending.cancel()
            self._pending = None

    # ---- inspection ------------------------------------------------------
    def alive(self) -> bool:
        with self._lock:
            return self._runner is not None and self._runner.alive()

    def process_ref(self) -> Optional[tuple]:
        """(target id, started_at monotonic, root pid) while alive, for node mapping."""
        with self._lock:
            runner = self._runner
            if runner is None or not runner.alive():
                return None
            return self.id, runner.started_at, runner.pid

    def status(self) -> str:
        with self._lock:
            if self._state == 'running' and self._runner is not None:
                if time.monotonic() - self._runner.started_at < STARTING_SEC:
                    return 'starting'
            return self._state

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            runner = self._runner
            alive = runner is not None and runner.alive()
            return {'id': self.id, 'kind': kind_of(self.spec), 'role': role_of(self.spec),
                    'spec': clean_dict(self.spec), 'status': self.status(),
                    'exit_code': self._exit_code, 'problem': self.problem,
                    'pid': runner.pid if alive else None,
                    'pids': runner.tree_pids() if alive else [],
                    'command': runner.argv if runner else None,
                    'started_at': self._started_wall if alive else None,
                    'uptime_sec': (time.monotonic() - runner.started_at) if alive else None,
                    'restart_count': self._restart_count,
                    'pending_restart': self._stale_spec}
