"""Launcher facade composed by :class:`roshanavi.lab.Lab`.

Owns workspace discovery, the process manager, the build runner, the project
file and the node<->process mapper, and implements the cross-cutting flows
(project load/save, autostart, inject job -> persistent dummy, export).

Every registry change made through this facade (add / update / remove /
persist) is saved to the project file right away (autosave). A project file
that failed to load is never overwritten automatically: autosave stays off
until it is reloaded successfully or saved explicitly.
"""

import logging
import os
import re
import threading
import time
from typing import Any, Dict, Iterable, List, Optional, Sequence, Union

from ..jobs import InjectSpec
from ..process_map import NodeProcessMapper
from ..pydantic_compat import ValidationError
from . import validate
from .build import BuildRunner
from .discovery import Workspace
from .dummy_config import export, format_errors
from .errors import LauncherError
from .manager import ProcessManager
from .proc_record import ProcessRecord, describe, find_leftovers, stop_leftovers
from .project import DEFAULT_FILE_NAME, ProjectStore
from .schema import (ClassSpec, CodeSettings, DummySpec, FunctionSpec, ProjectSpec, QosSpec,
                     TakeoverSpec, TargetSpec, TransformSpec, api_dict)

LOG = logging.getLogger(__name__)

AUTOSTART_DELAY_SEC = 2.0  # let DDS discovery see pre-existing nodes first (baseline)
PERSISTABLE_MODES = ('once', 'periodic', 'stream', 'media')
Spec = Union[TargetSpec, DummySpec, TransformSpec, FunctionSpec, ClassSpec]


def id_from_name(name: str, taken: Iterable[str]) -> str:
    base = re.sub(r'[^a-z0-9_-]', '_', name.lower()).strip('_-') or 'dummy'
    base = base[:56] if validate.TARGET_ID_RE.match(base) else f'd_{base}'[:56]
    candidate, n, used = base, 2, set(taken)
    while candidate in used:
        candidate, n = f'{base}-{n}', n + 1
    return candidate


class Launcher:
    def __init__(self, workspace_root: str, data_dir: str, project_path: Optional[str] = None,
                 autostart: bool = True, timeouts: Optional[Sequence[float]] = None,
                 clock=time.monotonic):
        self.workspace = Workspace(workspace_root)
        kwargs = {'timeouts': timeouts} if timeouts else {}
        self.manager = ProcessManager(self.workspace, data_dir, **kwargs)
        self.builder = BuildRunner(self.workspace, self.manager.restart_package)
        self.project = ProjectStore(project_path or os.path.join(self.workspace.root,
                                                                 DEFAULT_FILE_NAME))
        self.mapper = NodeProcessMapper(clock=clock)
        # #12: what this server started (for cleanup after a SIGKILL), and what a previous,
        # force-killed server left running (the leftover banner).
        self.records = ProcessRecord(data_dir)
        self.leftovers = find_leftovers(data_dir)
        if self.leftovers:
            LOG.warning('%d process(es) left by a previous roshanavi run are still running '
                        '(stop them from the banner or with `ros2 run roshanavi cleanup`)',
                        len(self.leftovers))
        self._clock = clock
        self._created = clock()
        self._autostart_pending = autostart
        self._watch_topics: List[str] = []
        self.takeover: Optional[TakeoverSpec] = None  # set by the launch takeover
        self.load_error: Optional[str] = None
        self.save_error: Optional[str] = None
        self._autosave_blocked = False
        self.reload_project()

    # ---- project -----------------------------------------------------------
    def reload_project(self) -> Dict[str, Any]:
        try:
            spec = self.project.load()
        except LauncherError as exc:
            self.load_error = str(exc)
            self._autosave_blocked = True
            LOG.error('project not loaded (autosave is off until it loads): %s', exc)
            return self.project_state()
        self.load_error = None
        self._autosave_blocked = False
        self._set_code(spec)
        self.manager.replace_all([*spec.targets, *spec.dummies, *spec.transforms,
                                  *spec.functions, *spec.classes])
        self._watch_topics = list(spec.watch_topics)
        self.takeover = spec.takeover
        return self.project_state()

    def _set_code(self, spec: Union[ProjectSpec, CodeSettings]) -> None:
        # Before the targets: function / class nodes resolve their modules with these.
        self.manager.code = CodeSettings(code_paths=list(spec.code_paths),
                                         installed_modules=list(spec.installed_modules))

    def open_project(self, path: str) -> Dict[str, Any]:
        """Switch to another project file: stop everything, load it, autostart its targets."""
        self.project = ProjectStore(path)
        state = self.reload_project()
        # Only after the new targets are registered: the housekeeping thread may run
        # _maybe_autostart at any moment and must not see the old registry.
        self._created = self._clock() - AUTOSTART_DELAY_SEC  # no DDS warm-up needed any more
        self._autostart_pending = True
        LOG.info('project switched to %s', self.project.path)
        return state

    def current_project(self) -> ProjectSpec:
        targets, dummies = self.manager.specs()
        return ProjectSpec(targets=targets, dummies=dummies,
                           transforms=self.manager.transforms(),
                           functions=self.manager.functions(),
                           classes=self.manager.classes(),
                           watch_topics=self._watch_topics,
                           code_paths=list(self.manager.code.code_paths),
                           installed_modules=list(self.manager.code.installed_modules),
                           takeover=self.takeover)

    def project_state(self) -> Dict[str, Any]:
        current = self.current_project()
        return {'path': self.project.path, 'exists': self.project.exists(),
                'dirty': self.project.is_dirty(current), 'error': self.load_error,
                'save_error': self.save_error, 'autosave': not self._autosave_blocked,
                'project': api_dict(current)}

    def put_project(self, spec: ProjectSpec) -> Dict[str, Any]:
        self._set_code(spec)
        self.manager.replace_all([*spec.targets, *spec.dummies, *spec.transforms,
                                  *spec.functions, *spec.classes])
        self._watch_topics = list(spec.watch_topics)
        self.takeover = spec.takeover
        return self.save_project()

    def save_project(self) -> Dict[str, Any]:
        self.project.save(self.current_project())
        self.load_error = self.save_error = None
        self._autosave_blocked = False
        return self.project_state()

    def autosave(self) -> None:
        """Save after a change; failures are reported in the project state, not raised."""
        if self._autosave_blocked:
            return
        try:
            self.project.save(self.current_project())
            self.save_error = None
        except LauncherError as exc:
            self.save_error = str(exc)
            LOG.error('autosave failed: %s', exc)

    # ---- registry (autosaved) ------------------------------------------------
    def add(self, spec: Spec, start: bool = False) -> Dict[str, Any]:
        result = self.manager.add(spec)
        self.autosave()
        return self.manager.start(spec.id) if start else result

    def update(self, target_id: str, spec: Spec) -> Dict[str, Any]:
        result = self.manager.update(target_id, spec)
        self.autosave()
        return result

    def remove(self, target_id: str) -> Dict[str, Any]:
        result = self.manager.remove(target_id)
        self.autosave()
        return result

    def set_code_settings(self, settings: CodeSettings) -> CodeSettings:
        """Change scope B / C (autosaved). Running nodes keep what they loaded; a restart picks
        up the new places."""
        self._set_code(settings)
        self.autosave()
        return self.manager.code

    def set_watch_topics(self, topics: Sequence[str]) -> None:
        self._watch_topics = list(topics)

    # ---- graph integration (housekeeping thread) ---------------------------
    def observe(self, node_ids: Iterable[str]) -> Dict[str, Dict[str, Any]]:
        """Map graph nodes to targets; returns ``{node id: role info}`` for the graph."""
        refs = self.manager.process_refs()
        mapping = self.mapper.update(node_ids, refs)
        self.records.update(refs)
        roles = self.manager.roles()
        self._maybe_autostart()
        return {node: {'role': roles.get(m.target_id, 'other'), 'target_id': m.target_id,
                       'confidence': m.confidence, 'pid': m.pid}
                for node, m in mapping.items()}

    def _maybe_autostart(self) -> None:
        if not self._autostart_pending or self._clock() - self._created < AUTOSTART_DELAY_SEC:
            return
        self._autostart_pending = False
        threading.Thread(target=self._autostart, name='launcher-autostart', daemon=True).start()

    def _autostart(self) -> None:
        started = self.manager.autostart()
        if started:
            LOG.info('autostarted: %s', ', '.join(started))

    def node_info(self) -> Dict[str, List[Dict[str, Any]]]:
        """``{target id: [{node, confidence, pid}]}`` from the latest mapping."""
        result: Dict[str, List[Dict[str, Any]]] = {}
        for mapping in self.mapper.mapping().values():
            result.setdefault(mapping.target_id, []).append(
                {'node': mapping.node, 'confidence': mapping.confidence, 'pid': mapping.pid})
        return result

    def targets(self) -> List[Dict[str, Any]]:
        """Targets with their mapped nodes. A target whose node is already on the map is
        ``running``: the fixed ``starting`` window only covers the time before that."""
        nodes = self.node_info()
        result = []
        for target in self.manager.list():
            mapped = sorted(nodes.get(target['id'], []), key=lambda n: n['node'])
            status = 'running' if mapped and target['status'] == 'starting' else target['status']
            result.append({**target, 'status': status, 'nodes': mapped})
        return result

    # ---- dummies -----------------------------------------------------------
    def persist_job(self, spec: InjectSpec, name: str, namespace: Optional[str] = None,
                    dummy_id: Optional[str] = None, autostart: bool = False) -> Dict[str, Any]:
        """Turn an inject job's settings into a running persistent dummy node."""
        if spec.mode not in PERSISTABLE_MODES:
            raise LauncherError('invalid_request', f'mode {spec.mode!r} cannot become a '
                                'persistent node (use once / periodic / stream / media)')
        validate.node_name(name)
        taken = [t['id'] for t in self.manager.list()]
        try:
            dummy = DummySpec(id=dummy_id or id_from_name(name, taken), name=name,
                              namespace=namespace or None, topic=spec.topic, type=spec.type,
                              mode=spec.mode, payload=spec.payload, rate_hz=spec.rate_hz,
                              count=spec.count, source=spec.source, loop=spec.loop,
                              qos=QosSpec(**(spec.qos or {})), media=spec.media,
                              autostart=autostart)
        except ValidationError as exc:
            raise LauncherError('invalid_request', format_errors(exc)) from exc
        return self.add(dummy, start=True)

    def export_dummies(self, directory: str, ids: Sequence[str] = ()) -> Dict[str, Any]:
        target_dir = validate.contained_dir(directory, self.workspace.root)
        _, dummies = self.manager.specs()
        transforms = self.manager.transforms()
        functions = self.manager.functions()
        classes = self.manager.classes()
        if ids:
            unknown = set(ids) - {d.id for d in [*dummies, *transforms, *functions, *classes]}
            if unknown:
                raise LauncherError('not_found', 'no such dummy / transform / function / class: '
                                    f'{sorted(unknown)}', 404)
            dummies = [d for d in dummies if d.id in set(ids)]
            transforms = [d for d in transforms if d.id in set(ids)]
            functions = [d for d in functions if d.id in set(ids)]
            classes = [d for d in classes if d.id in set(ids)]
        return export(dummies, target_dir, self.manager.data_dir, transforms, functions,
                      self.workspace.root, classes, self.manager.code)

    # ---- leftovers of a force-killed previous server (#12) -------------------
    def leftover_state(self) -> Dict[str, Any]:
        return describe(self.leftovers)

    def stop_leftovers(self) -> Dict[str, Any]:
        result = stop_leftovers(self.leftovers, report=LOG.info)
        self.leftovers = []
        return result

    def close(self) -> None:
        self.builder.close()
        self.manager.close()
        self.records.close()
