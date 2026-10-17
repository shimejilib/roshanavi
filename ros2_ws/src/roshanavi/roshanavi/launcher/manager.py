"""Registry of launch targets and persistent dummies (the in-memory working set).

Specs are validated against the workspace when added through the API
(``strict=True``: errors are returned to the caller). Specs loaded from the
project file are registered even when they no longer validate, in state
``invalid`` with the reason, so a stale project still opens.
"""

import logging
import os
import shutil
import tempfile
import threading
from typing import Any, Dict, List, Sequence, Tuple

from . import command
from .discovery import Workspace
from .dummy_config import config_text, write_atomic
from .env import child_env
from .errors import LauncherError
from .process import SIGINT_TIMEOUT_SEC, SIGTERM_TIMEOUT_SEC
from .schema import DummySpec, TargetSpec
from .target import Spec, Target, kind_of

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

    # ---- argv / env --------------------------------------------------------
    def _argv(self, spec: Spec) -> List[str]:
        if isinstance(spec, DummySpec):
            command.validate_dummy(spec)
            path = os.path.join(self._runtime_dir, f'{spec.id}.yaml')
            try:
                write_atomic(path, config_text(spec, self.data_dir))
            except OSError as exc:
                raise LauncherError('spawn_failed', f'cannot write dummy config: {exc}',
                                    500) from exc
            return command.dummy_command(spec, path)
        return command.target_command(spec, self._ctx)

    def _env(self) -> Dict[str, str]:
        return child_env(self.workspace.env, self.workspace.unsourced_prefixes())

    def validate(self, spec: Spec) -> None:
        if isinstance(spec, DummySpec):
            command.validate_dummy(spec)
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
        if (kind_of(spec) == 'dummy') != (kind_of(target.spec) == 'dummy'):
            raise LauncherError('invalid_request', 'cannot turn a dummy into a target')
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

    def get(self, target_id: str) -> Dict[str, Any]:
        return self._get(target_id).to_dict()

    def target(self, target_id: str) -> Target:
        return self._get(target_id)

    def list(self) -> List[Dict[str, Any]]:
        return [t.to_dict() for t in self._all()]

    def specs(self) -> Tuple[List[TargetSpec], List[DummySpec]]:
        targets = [t.spec for t in self._all() if isinstance(t.spec, TargetSpec)]
        dummies = [t.spec for t in self._all() if isinstance(t.spec, DummySpec)]
        return targets, dummies

    def roles(self) -> Dict[str, str]:
        return {t.id: ('dummy' if isinstance(t.spec, DummySpec) else t.spec.role)
                for t in self._all()}

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

