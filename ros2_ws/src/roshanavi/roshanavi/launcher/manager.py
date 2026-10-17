"""Registry of launch targets and persistent dummies (the in-memory working set).

Specs are validated against the workspace when added through the API
(``strict=True``: errors are returned to the caller). Specs loaded from the
project file are registered even when they no longer validate, in state
``invalid`` with the reason, so a stale project still opens.
"""

import json
import logging
import os
import shutil
import tempfile
import threading
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..function.core import adopt_topic_types
from . import command
from .discovery import Workspace
from .dummy_config import (config_text, function_config_text, transform_config_text,
                           write_atomic)
from .env import child_env
from .errors import LauncherError
from .process import SIGINT_TIMEOUT_SEC, SIGTERM_TIMEOUT_SEC
from .schema import DummySpec, FunctionSpec, TargetSpec, TransformSpec
from .target import Spec, Target, kind_of, role_of

LOG = logging.getLogger(__name__)

MAX_TARGETS = 200


class ProcessManager:
    def __init__(self, workspace: Workspace, data_dir: str,
                 timeouts: Sequence[float] = (SIGINT_TIMEOUT_SEC, SIGTERM_TIMEOUT_SEC)):
        self.workspace = workspace
        self.data_dir = os.path.realpath(data_dir)
        self._timeouts = tuple(timeouts)
        self._ctx = command.CommandContext(workspace, (workspace.root, self.data_dir))
        self._runtime_dir = tempfile.mkdtemp(prefix='roshanavi-dummies-')
        self._lock = threading.Lock()
        self._targets: Dict[str, Target] = {}
        self._closed = False
        # topic -> its current types (the server's graph); function inputs adopt them
        self.topic_types: Optional[Callable[[str], Sequence[str]]] = None

    # ---- argv / env --------------------------------------------------------
    def _argv(self, spec: Spec) -> List[str]:
        if isinstance(spec, DummySpec):
            command.validate_dummy(spec)
            path = self._write_config(spec.id, config_text(spec, self.data_dir))
            return command.dummy_command(spec, path)
        if isinstance(spec, TransformSpec):
            command.validate_transform(spec)
            path = self._write_config(spec.id, transform_config_text(spec))
            return command.transform_command(spec, path)
        if isinstance(spec, FunctionSpec):
            command.validate_function(spec, self.workspace.root)
            if self.topic_types is not None:
                spec = adopt_topic_types(spec, self.topic_types)
            status = self.status_path(spec.id)
            try:
                os.unlink(status)  # a stale status of the previous run must not show
            except FileNotFoundError:
                pass
            path = self._write_config(spec.id, function_config_text(spec, self.workspace.root,
                                                                    status))
            return command.function_command(spec, path, self.workspace.root)
        return command.target_command(spec, self._ctx)

    def status_path(self, spec_id: str) -> str:
        """Where a function node writes its status (the server's private runtime dir)."""
        return os.path.join(self._runtime_dir, f'{spec_id}.status.json')

    def function_status(self, spec_id: str) -> Optional[Dict[str, Any]]:
        try:
            with open(self.status_path(spec_id), encoding='utf-8') as fh:
                status = json.load(fh)
        except (OSError, ValueError):
            return None
        return status if isinstance(status, dict) else None

    def _write_config(self, spec_id: str, text: str) -> str:
        path = os.path.join(self._runtime_dir, f'{spec_id}.yaml')
        try:
            write_atomic(path, text)
        except OSError as exc:
            raise LauncherError('spawn_failed', f'cannot write node config: {exc}', 500) from exc
        return path

    def _env(self) -> Dict[str, str]:
        return child_env(self.workspace.env, self.workspace.unsourced_prefixes())

    def validate(self, spec: Spec) -> None:
        if isinstance(spec, DummySpec):
            command.validate_dummy(spec)
        elif isinstance(spec, TransformSpec):
            command.validate_transform(spec)
        elif isinstance(spec, FunctionSpec):
            command.validate_function(spec, self.workspace.root)
        else:
            command.target_command(spec, self._ctx)

    # ---- registry ----------------------------------------------------------
    def add(self, spec: Spec, strict: bool = True) -> Dict[str, Any]:
        problem = None
        try:
            self.validate(spec)
        except LauncherError as exc:
            if strict:
                raise
            problem = str(exc)
            LOG.warning('target %s registered as invalid: %s', spec.id, exc)
        target = Target(spec, self._argv, self._env, self.workspace.root, self._timeouts,
                        problem=problem)
        with self._lock:
            if self._closed:
                raise LauncherError('shutting_down', 'server is shutting down', 503)
            if spec.id in self._targets:
                raise LauncherError('duplicate_id', f'id {spec.id!r} is already used', 409)
            if len(self._targets) >= MAX_TARGETS:
                raise LauncherError('too_many_targets', f'at most {MAX_TARGETS} targets', 429)
            self._targets[spec.id] = target
        return target.to_dict()

    def update(self, target_id: str, spec: Spec) -> Dict[str, Any]:
        target = self._get(target_id)
        if spec.id != target_id:
            raise LauncherError('invalid_request', 'the id of a target cannot be changed')
        managed = ('dummy', 'transform', 'function')
        if kind_of(spec) != kind_of(target.spec) and (kind_of(spec) in managed
                                                      or kind_of(target.spec) in managed):
            raise LauncherError('invalid_request', f'cannot turn a {kind_of(target.spec)} '
                                f'into a {kind_of(spec)}')
        self.validate(spec)
        target.update_spec(spec)
        return target.to_dict()

    def remove(self, target_id: str) -> Dict[str, Any]:
        target = self._get(target_id)
        target.stop()
        with self._lock:
            self._targets.pop(target_id, None)
        return target.to_dict()

    def replace_all(self, specs: Sequence[Spec]) -> None:
        """Stop and drop everything, then register ``specs`` (project load)."""
        with self._lock:
            old = list(self._targets.values())
            self._targets = {}
        self._stop_many(old)
        for spec in specs:
            self.add(spec, strict=False)

    def _get(self, target_id: str) -> Target:
        with self._lock:
            target = self._targets.get(target_id)
        if target is None:
            raise LauncherError('not_found', f'no such target: {target_id}', 404)
        return target

    # ---- lifecycle ---------------------------------------------------------
    def start(self, target_id: str) -> Dict[str, Any]:
        target = self._get(target_id)
        target.start()
        return target.to_dict()

    def stop(self, target_id: str) -> Dict[str, Any]:
        target = self._get(target_id)
        target.stop()
        return target.to_dict()

    def restart(self, target_id: str) -> Dict[str, Any]:
        target = self._get(target_id)
        target.restart()
        return target.to_dict()

    def restart_package(self, package: str) -> List[str]:
        """Restart running run/launch targets of ``package`` (after a build)."""
        restarted = []
        for target in self._all():
            if (isinstance(target.spec, TargetSpec) and target.spec.package == package
                    and target.alive()):
                try:
                    target.restart()
                    restarted.append(target.id)
                except LauncherError as exc:
                    LOG.error('restart of %s after build failed: %s', target.id, exc)
        return restarted

    def autostart(self) -> List[str]:
        started = []
        for target in self._all():
            if getattr(target.spec, 'autostart', False) and not target.alive():
                try:
                    target.start()
                    started.append(target.id)
                except LauncherError as exc:
                    LOG.error('autostart of %s failed: %s', target.id, exc)
        return started

    # ---- inspection --------------------------------------------------------
    def _all(self) -> List[Target]:
        with self._lock:
            return list(self._targets.values())

    def _describe(self, target: Target) -> Dict[str, Any]:
        info = target.to_dict()
        if isinstance(target.spec, FunctionSpec):
            status = self.function_status(target.id) if target.alive() else None
            info['function_status'] = status
        return info

    def get(self, target_id: str) -> Dict[str, Any]:
        return self._describe(self._get(target_id))

    def target(self, target_id: str) -> Target:
        return self._get(target_id)

    def list(self) -> List[Dict[str, Any]]:
        return [self._describe(t) for t in self._all()]

    def specs(self) -> Tuple[List[TargetSpec], List[DummySpec]]:
        targets = [t.spec for t in self._all() if isinstance(t.spec, TargetSpec)]
        dummies = [t.spec for t in self._all() if isinstance(t.spec, DummySpec)]
        return targets, dummies

    def transforms(self) -> List[TransformSpec]:
        return [t.spec for t in self._all() if isinstance(t.spec, TransformSpec)]

    def functions(self) -> List[FunctionSpec]:
        return [t.spec for t in self._all() if isinstance(t.spec, FunctionSpec)]

    def roles(self) -> Dict[str, str]:
        return {t.id: role_of(t.spec) for t in self._all()}

    def process_refs(self) -> List[tuple]:
        return [ref for ref in (t.process_ref() for t in self._all()) if ref is not None]

    def logs(self, target_id: str):
        return self._get(target_id).log

    # ---- shutdown ----------------------------------------------------------
    @staticmethod
    def _stop_many(targets: Sequence[Target]) -> None:
        threads = [threading.Thread(target=t.stop, name=f'stop-{t.id}', daemon=True)
                   for t in targets if t.alive()]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()

    def close(self) -> None:
        """Stop every child process (idempotent; used by atexit and server shutdown)."""
        with self._lock:
            if self._closed:
                return
            self._closed = True
            targets = list(self._targets.values())
        self._stop_many(targets)
        shutil.rmtree(self._runtime_dir, ignore_errors=True)
        LOG.info('launcher stopped %d target(s)', len(targets))

