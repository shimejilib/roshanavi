"""Launch decomposition import: source checks, preview cache, commit (docs/design/launcher.md).

Trust model: a Python launch file is code, and evaluating it runs that code.
Only files that ``ros2 launch`` would run for this user anyway are accepted:
launch files of discovered packages (workspace or sourced ROS), or files whose
realpath lies inside the workspace. Nothing under the data dir (where uploads
and recordings live) is ever evaluated. Evaluation happens in a subprocess
with a timeout (:mod:`.runner`); only the JSON result reaches the server.
"""

import os
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Dict, List, Literal, Optional, Sequence, Tuple, Union

import yaml

from ..launcher import validate
from ..launcher.discovery import MAX_LAUNCH_DEPTH
from ..launcher.dummy_config import format_errors, write_atomic
from ..launcher.env import child_env
from ..launcher.errors import LauncherError
from ..launcher.schema import TargetSpec
from ..launcher.service import Launcher, id_from_name
from ..pydantic_compat import StrictModel, ValidationError, constr
from .params_merge import unflatten
from .plan import build_plan, parse_result
from .runner import DEFAULT_TIMEOUT_SEC, run_child

PREVIEW_TTL_SEC = 1800.0
MAX_PREVIEWS = 16
PARAMS_DIR = 'imported_params'
PATH_EXTS = ('.py', '.xml', '.yaml', '.yml')


class _Strict(StrictModel):
    pass


class PackageSource(_Strict):
    kind: Literal['package']
    package: constr(min_length=1, max_length=100)
    launch_file: constr(min_length=1, max_length=128)


class PathSource(_Strict):
    kind: Literal['path']
    path: constr(min_length=1, max_length=1024)


Source = Union[PackageSource, PathSource]


def _inside(path: str, root: str) -> bool:
    root = os.path.realpath(root)
    return os.path.commonpath([root, os.path.realpath(path)]) == root


def find_launch_path(prefix: str, package: str, launch_file: str) -> str:
    """Full path of a discovered launch file (same search depth as discovery)."""
    base = os.path.join(prefix, 'share', package, 'launch')
    for current, dirs, files in os.walk(base):
        if os.path.relpath(current, base).count(os.sep) >= MAX_LAUNCH_DEPTH:
            dirs[:] = []
        if launch_file in files:
            return os.path.join(current, launch_file)
    raise LauncherError('unknown_launch_file', f'{package} has no launch file {launch_file!r}',
                        404)


class LaunchImporter:
    def __init__(self, launcher: Launcher, data_dir: str,
                 timeout_sec: float = DEFAULT_TIMEOUT_SEC, clock=time.monotonic):
        self._launcher = launcher
        self._data_dir = os.path.realpath(data_dir)
        self._timeout = timeout_sec
        self._clock = clock
        self._lock = threading.Lock()
        self._previews: 'OrderedDict[str, Tuple[float, Dict[str, Any]]]' = OrderedDict()

    # ---- source ------------------------------------------------------------
    def resolve(self, source: Source) -> Tuple[str, str, Optional[Dict[str, Any]]]:
        """(file path, origin label, whole-launch target spec or None)."""
        workspace = self._launcher.workspace
        if isinstance(source, PackageSource):
            info = workspace.require_launch_file(source.package, source.launch_file)
            if info.prefix is None:
                raise LauncherError('not_built', f'{source.package} is not built yet', 409)
            path = find_launch_path(info.prefix, source.package, source.launch_file)
            whole = {'kind': 'launch', 'package': source.package,
                     'launch_file': source.launch_file}
            origin = f'{source.package}/{source.launch_file}'
        else:
            path = validate.contained_file(source.path, [workspace.root], PATH_EXTS)
            whole, origin = None, os.path.relpath(path, workspace.root)
        if _inside(path, self._data_dir):
            raise LauncherError('forbidden_path', 'files in the data dir (uploads, '
                                'recordings) are never evaluated', 403)
        return os.path.realpath(path), origin, whole

    # ---- preview -----------------------------------------------------------
    def _validate(self, spec: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        try:
            self._launcher.manager.validate(TargetSpec(**spec))
        except ValidationError as exc:
            return 'invalid_request', format_errors(exc)
        except LauncherError as exc:
            return exc.code, str(exc)
        return None

    def evaluate(self, path: str, args: Dict[str, str]) -> Dict[str, Any]:
        workspace = self._launcher.workspace
        env = child_env(workspace.env, workspace.unsourced_prefixes())
        return run_child({'path': path, 'args': args}, env, workspace.root, self._timeout)

    def preview(self, source: Source, args: Dict[str, str]) -> Dict[str, Any]:
        pairs = dict(validate.launch_args(args))
        path, origin, whole = self.resolve(source)
        result = parse_result(self.evaluate(path, pairs))
        plan = build_plan(result, origin, self._launcher.targets(), self._validate)
        if whole is not None:
            whole = {**whole, 'args': [f'{k}:={v}' for k, v in pairs.items()]}
        plan.update(origin=origin, args=pairs, whole=whole,
                    whole_reason=None if whole else 'not_in_package')
        plan['preview_id'] = self._remember(plan)
        return plan

    def _remember(self, plan: Dict[str, Any]) -> str:
        preview_id = uuid.uuid4().hex
        now = self._clock()
        with self._lock:
            for key in [k for k, (t, _) in self._previews.items() if now - t > PREVIEW_TTL_SEC]:
                del self._previews[key]
            self._previews[preview_id] = (now, plan)
            while len(self._previews) > MAX_PREVIEWS:
                self._previews.popitem(last=False)
        return preview_id

    def _plan(self, preview_id: str) -> Dict[str, Any]:
        with self._lock:
            entry = self._previews.get(preview_id)
        if entry is None or self._clock() - entry[0] > PREVIEW_TTL_SEC:
            raise LauncherError('preview_expired', 'the preview expired; analyse the launch '
                                'file again', 404)
        return entry[1]

    # ---- commit ------------------------------------------------------------
    def _write_params(self, target_id: str, values: Dict[str, Any]) -> str:
        path = os.path.join(self._data_dir, PARAMS_DIR, f'{target_id}.yaml')
        os.makedirs(os.path.dirname(path), exist_ok=True)
        text = ('# generated by roshanavi from a launch file (launch decomposition import)\n'
                + yaml.safe_dump({'/**': {'ros__parameters': unflatten(values)}},
                                 sort_keys=False))
        try:
            write_atomic(path, text)
        except OSError as exc:
            raise LauncherError('save_failed', f'cannot write {path}: {exc}', 500) from exc
        return path

    def _import_node(self, node: Dict[str, Any], role: str, autostart: bool) -> Dict[str, Any]:
        spec = dict(node['spec'], role=role, autostart=autostart)
        taken = [t['id'] for t in self._launcher.targets()]
        if spec['id'] in taken:
            spec['id'] = id_from_name(spec['id'], taken)
        if node['file_params']:
            spec['params_file'] = self._write_params(spec['id'], node['file_params'])
        try:
            return self._launcher.add(TargetSpec(**spec))
        except ValidationError as exc:
            raise LauncherError('invalid_request', format_errors(exc)) from exc

    def commit(self, preview_id: str, mode: str, indices: Sequence[int], role: str,
               autostart: bool = False) -> Dict[str, Any]:
        plan = self._plan(preview_id)
        if mode == 'whole':
            return {'created': [self._import_whole(plan, role, autostart)], 'errors': []}
        created: List[Dict[str, Any]] = []
        errors: List[Dict[str, Any]] = []
        for index in indices:
            if not 0 <= index < len(plan['nodes']):
                raise LauncherError('invalid_request', f'no node #{index} in this preview')
            node = plan['nodes'][index]
            if not node['importable']:
                errors.append({'index': index, **node['problem']})
                continue
            try:
                created.append(self._import_node(node, role, autostart))
            except LauncherError as exc:
                errors.append({'index': index, 'code': exc.code, 'message': str(exc)})
        return {'created': created, 'errors': errors}

    def _import_whole(self, plan: Dict[str, Any], role: str, autostart: bool) -> Dict[str, Any]:
        whole = plan.get('whole')
        if not whole:
            raise LauncherError('whole_unavailable', 'only launch files of a package can be '
                                'imported as a whole', 400)
        taken = [t['id'] for t in self._launcher.targets()]
        stem = whole['launch_file'].split('.')[0]
        spec = {**whole, 'id': id_from_name(stem, taken), 'role': role, 'autostart': autostart,
                'imported_from': plan['origin']}
        try:
            return self._launcher.add(TargetSpec(**spec))
        except ValidationError as exc:
            raise LauncherError('invalid_request', format_errors(exc)) from exc
