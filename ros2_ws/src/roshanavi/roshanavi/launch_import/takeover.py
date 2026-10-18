"""Launch takeover: run an existing launch file under roshanavi (docs/design/integration.md).

``--launch <package> <launch file> [name:=value ...]`` (or ``POST /api/takeover/start``)
evaluates the file in the sandboxed child (:mod:`.runner`, exactly as the decomposition
import does), registers the targets (:mod:`.takeover_plan`) and starts them. The launch
file is the source of truth: the project only remembers *which* file and arguments
(``takeover:``) and marks the targets it owns (``takeover: true``).

* Restart: when the project already holds targets taken over from the same file and
  arguments, they are reused (same ids, the roles the user chose), never duplicated. If the
  file changed while roshanavi was not running, the difference waits for the user's OK.
* Change detection: every launch file read (main + includes) and every parameter file is
  polled by ``stat`` (the server never opens them; their contents are only read by the
  sandboxed child). A change re-evaluates the file in the child; a real difference
  becomes ``pending`` (the UI banner 「launch ファイルが変更されました…」), an identical
  result (e.g. a rebuild that copied the same file) just becomes the new baseline.
* Apply: added targets are registered and started, removed ones are stopped and dropped,
  changed ones are updated and restarted when they were running; nothing else is touched.
"""

import logging
import os
import threading
import time
import uuid
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

import yaml

from ..launcher import validate
from ..launcher.dummy_config import format_errors
from ..launcher.errors import LauncherError
from ..launcher.schema import TakeoverSpec, TargetSpec, clean_dict
from ..pydantic_compat import ValidationError
from . import takeover_plan as tp
from .importer import PARAMS_DIR, LaunchImporter, PackageSource
from .params_merge import unflatten
from .plan import build_plan, parse_result

LOG = logging.getLogger(__name__)

POLL_SEC = 2.0
FileStat = Tuple[int, int, int]  # mtime_ns, size, inode


def _stat(path: str) -> Optional[FileStat]:
    try:
        st = os.stat(path)
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size, st.st_ino


class TakeoverService:
    def __init__(self, importer: LaunchImporter, data_dir: str, poll_sec: float = POLL_SEC,
                 autostart: bool = True):
        self._importer = importer
        self._launcher = importer.launcher
        self._data_dir = os.path.realpath(data_dir)
        self._poll = poll_sec
        self._autostart = autostart
        self._lock = threading.RLock()  # short: state fields (status() never waits long)
        self._work = threading.RLock()  # evaluate / apply, one at a time (may take seconds)
        self._stop = threading.Event()
        self._settled = threading.Event()  # the startup finished (ready or error)
        self._thread: Optional[threading.Thread] = None
        self.config: Optional[TakeoverSpec] = None
        self.mine: List[str] = []
        self.state = 'off'  # off | starting | ready | error | inactive
        self.error: Optional[Dict[str, Any]] = None
        self.report: Optional[Dict[str, Any]] = None
        self.pending: Optional[Dict[str, Any]] = None
        self._pending_desired: List[tp.Desired] = []
        self._files: Dict[str, Optional[FileStat]] = {}
        self.started_ids: List[str] = []

    # ---- configuration ---------------------------------------------------------
    def configure(self, package: str, launch_file: str, args: Mapping[str, str],
                  mode: str = 'node', mine: Sequence[str] = (), wait: bool = False) -> None:
        """Take over ``package/launch_file`` (validated here) and start it in the background."""
        validate.package_name(package)
        validate.launch_file_name(launch_file)
        pairs = dict(validate.launch_args(dict(args)))
        if mode not in ('node', 'whole'):
            raise LauncherError('invalid_request', f'unknown takeover mode {mode!r}')
        config = TakeoverSpec(package=package, launch_file=launch_file,
                              args=[f'{k}:={v}' for k, v in sorted(pairs.items())], mode=mode)
        self.stop_watching()
        with self._lock:
            self.config, self.mine = config, [m for m in mine if m]
            self.state, self.error, self.pending, self.report = 'starting', None, None, None
        self._stop.clear()
        self._settled.clear()
        self._thread = threading.Thread(target=self._run, name='launch-takeover', daemon=True)
        self._thread.start()
        if wait:
            self._settled.wait()

    def fail(self, exc: LauncherError) -> None:
        """``--launch`` was rejected before anything started (shown in the UI)."""
        with self._lock:
            self.state, self.error = 'error', {'code': exc.code, 'message': str(exc)}

    def args(self) -> Dict[str, str]:
        assert self.config is not None
        return dict(item.split(':=', 1) for item in self.config.args)

    # ---- evaluation ------------------------------------------------------------
    def _evaluate(self) -> Tuple[Dict[str, Any], List[tp.Desired], List[str]]:
        config = self.config
        assert config is not None
        source = PackageSource(kind='package', package=config.package,
                               launch_file=config.launch_file)
        path, origin, _whole = self._importer.resolve(source)
        result = parse_result(self._importer.evaluate(path, self.args()))
        if result.missing_args:
            raise LauncherError('missing_args', 'the launch file needs arguments: '
                                + ', '.join(result.missing_args), 400)
        plan = build_plan(result, origin, [], self._importer.validate_spec)
        desired, notes = tp.desired_targets(plan, config.package, config.launch_file,
                                            self.args(), config.mode)
        return plan, desired, notes

    def _existing(self) -> List[Dict[str, Any]]:
        return [t for t in self._launcher.targets()
                if t['kind'] in ('run', 'launch') and t['spec'].get('takeover')]

    def _plan_now(self) -> Tuple[Dict[str, Any], List[tp.Desired], Dict[str, Any],
                                 Dict[str, Any]]:
        plan, desired, notes = self._evaluate()
        existing = self._existing()
        taken = [t['id'] for t in self._launcher.targets()
                 if t['id'] not in {e['id'] for e in existing}]
        desired = tp.assign(desired, existing, taken, self.mine)
        changes = tp.diff(desired, existing, self._file_params_of)
        return plan, desired, changes, tp.report(plan, desired, self.config.mode, notes)

    def _file_params_of(self, spec: Mapping[str, Any]) -> Optional[Dict[str, Any]]:
        """Values of a parameter file roshanavi wrote at import (data_dir/imported_params)."""
        path = spec.get('params_file')
        root = os.path.join(self._data_dir, PARAMS_DIR)
        if not path or os.path.dirname(os.path.realpath(path)) != root:
            return None
        try:
            with open(path, encoding='utf-8') as handle:
                data = yaml.safe_load(handle) or {}
            values = data.get('/**', {}).get('ros__parameters', {})
        except (OSError, yaml.YAMLError, AttributeError):
            return None
        return _flatten(values) if isinstance(values, dict) else None

    # ---- startup -----------------------------------------------------------------
    def _run(self) -> None:
        try:
            self._startup()
        except LauncherError as exc:
            LOG.error('launch takeover failed: %s', exc)
            with self._lock:
                self.state, self.error = 'error', {'code': exc.code, 'message': str(exc)}
            return
        except Exception as exc:  # never let the thread die silently
            LOG.exception('launch takeover failed')
            with self._lock:
                self.state, self.error = 'error', {'code': 'takeover_failed', 'message': str(exc)}
            return
        finally:
            self._settled.set()
        self._watch_loop()

    def _startup(self) -> None:
        with self._work:
            plan, desired, changes, report = self._plan_now()
            same = _same(self._launcher.takeover, self.config)
            had_targets = bool(self._existing())
            if had_targets and same and not tp.is_empty(changes):
                # changed while roshanavi was not running: ask first, run what is registered
                self._set_pending(desired, changes, report, 'changed_since_last', [])
                LOG.warning('the launch file changed since it was taken over; the UI asks '
                            'whether to import it again')
            elif not tp.is_empty(changes):
                self._apply(desired, changes, start_added=False)
            self._launcher.takeover = self.config
            self._launcher.autosave()
            self.report = report
            self._remember_files(plan)
            started = self._start_all() if self._autostart else []
            self.started_ids = started
            self.state = 'ready'
        _log_report(self.config, report, started)

    def _start_all(self) -> List[str]:
        started = []
        for target in self._existing():
            if target['status'] in ('running', 'starting') or target['status'] == 'invalid':
                continue
            try:
                self._launcher.manager.start(target['id'])
                started.append(target['id'])
            except LauncherError as exc:
                LOG.error('takeover: cannot start %s: %s', target['id'], exc)
        return started

    # ---- change detection ----------------------------------------------------------
    def _remember_files(self, plan: Mapping[str, Any]) -> None:
        paths = list(plan.get('files') or [])
        for node in plan.get('nodes', []):
            paths += [p for p in node.get('param_files') or [] if p]
        self._files = {os.path.realpath(p): _stat(os.path.realpath(p)) for p in dict.fromkeys(paths)}

    def changed_files(self) -> List[str]:
        return [path for path, old in self._files.items() if _stat(path) != old]

    def _watch_loop(self) -> None:
        seen: List[str] = []
        while not self._stop.wait(self._poll):
            with self._lock:
                if not _same(self._launcher.takeover, self.config):
                    self.state = 'inactive'  # another project was opened
                    continue
                if self.state == 'inactive':
                    self.state = 'ready'
            changed = self.changed_files()
            if not changed:
                seen = []
                continue
            if changed != seen:  # wait one more poll: an editor may still be writing
                seen = changed
                continue
            seen = []
            try:
                self.check(reason='file_changed', files=changed)
            except LauncherError as exc:
                LOG.warning('takeover: re-evaluating the changed launch file failed: %s', exc)
                with self._lock:
                    self.error = {'code': exc.code, 'message': str(exc)}
                    self._files.update({p: _stat(p) for p in changed})

    def check(self, reason: str = 'manual', files: Sequence[str] = ()) -> Dict[str, Any]:
        """Evaluate again now; a difference becomes ``pending`` (nothing is applied)."""
        with self._work:
            if self.config is None:
                raise LauncherError('no_takeover', 'no launch file is taken over', 409)
            plan, desired, changes, report = self._plan_now()
            self._remember_files(plan)
            self.error = None
            if tp.is_empty(changes):
                self.pending, self._pending_desired = None, []
                self.report = report
            else:
                self._set_pending(desired, changes, report, reason, files)
            return self.status()

    def _set_pending(self, desired: List[tp.Desired], changes: Dict[str, Any],
                     report: Dict[str, Any], reason: str, files: Sequence[str]) -> None:
        root = self._launcher.workspace.root
        shown = [os.path.relpath(f, root) if f.startswith(root + os.sep) else f for f in files]
        self._pending_desired = desired
        self.pending = {'preview_id': uuid.uuid4().hex, 'reason': reason, 'files': shown,
                        **changes, 'report': report}

    # ---- apply -----------------------------------------------------------------------
    def apply(self, preview_id: str) -> Dict[str, Any]:
        with self._work:
            if not self.pending or self.pending['preview_id'] != preview_id:
                raise LauncherError('preview_expired', 'this change was already applied or '
                                    'replaced; check the launch file again', 404)
            desired = self._pending_desired
            # The registry may have changed since the check (the user deleted a node ...).
            changes = tp.diff(desired, self._existing(), self._file_params_of)
            result = self._apply(desired, changes, start_added=True)
            self.report = self.pending['report']
            self.pending, self._pending_desired = None, []
            return {**result, 'status': self.status()}

    def dismiss(self, preview_id: str) -> Dict[str, Any]:
        with self._work:
            if self.pending and self.pending['preview_id'] == preview_id:
                self.pending, self._pending_desired = None, []
            return self.status()

    def _apply(self, desired: List[tp.Desired], changes: Dict[str, Any],
               start_added: bool) -> Dict[str, Any]:
        by_id = {d['spec']['id']: d for d in desired}
        errors: List[Dict[str, str]] = []
        restarted: List[str] = []
        for entry in changes['removed']:
            self._try(errors, entry['id'], lambda e=entry: self._launcher.remove(e['id']))
        for entry in changes['added']:
            item = by_id[entry['id']]
            self._try(errors, entry['id'], lambda i=item: self._add(i, start_added))
        for entry in changes['changed']:
            item = by_id[entry['id']]
            if self._try(errors, entry['id'], lambda i=item: self._update(i)):
                restarted.append(entry['id'])
        return {'added': [e['id'] for e in changes['added']],
                'removed': [e['id'] for e in changes['removed']],
                'changed': [e['id'] for e in changes['changed']],
                'restarted': restarted, 'errors': errors}

    @staticmethod
    def _try(errors: List[Dict[str, str]], target_id: str, action) -> bool:
        """Run ``action``; its truth value, or False (error recorded) when it failed."""
        try:
            return bool(action())
        except LauncherError as exc:
            errors.append({'id': target_id, 'code': exc.code, 'message': str(exc)})
            LOG.error('takeover: %s: %s', target_id, exc)
            return False

    def _spec(self, item: tp.Desired) -> TargetSpec:
        spec = dict(item['spec'])
        if item['file_params']:
            spec['params_file'] = self._importer.write_params(spec['id'], item['file_params'])
        try:
            return TargetSpec(**spec)
        except ValidationError as exc:
            raise LauncherError('invalid_request', format_errors(exc)) from exc

    def _add(self, item: tp.Desired, start: bool) -> str:
        self._launcher.add(self._spec(item), start=start)
        return item['spec']['id']

    def _update(self, item: tp.Desired) -> bool:
        """Update a changed target; True when it was running and has been restarted."""
        target_id = item['spec']['id']
        current = self._launcher.manager.get(target_id)
        spec = self._spec({**item, 'spec': {**item['spec'],
                                            'autostart': current['spec'].get('autostart',
                                                                             False)}})
        was_running = self._launcher.manager.target(target_id).alive()
        self._launcher.update(target_id, spec)
        if was_running:
            self._launcher.manager.restart(target_id)  # only the changed ones restart
        return was_running

    # ---- status ------------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        with self._lock:
            config = self.config
            return {'active': config is not None, 'state': self.state,
                    'package': config.package if config else None,
                    'launch_file': config.launch_file if config else None,
                    'args': self.args() if config else {},
                    'mode': config.mode if config else None, 'mine': list(self.mine),
                    'error': self.error, 'report': self.report, 'pending': self.pending,
                    'targets': [t['id'] for t in self._existing()] if config else [],
                    'watched': len(self._files)}

    def stop_watching(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=30)
        self._thread = None

    def close(self) -> None:
        self.stop_watching()


def _same(a: Optional[TakeoverSpec], b: Optional[TakeoverSpec]) -> bool:
    """Same file / arguments / mode (by value: pydantic's == also compares which fields
    were set explicitly in some versions)."""
    if a is None or b is None:
        return a is b
    return clean_dict(a) == clean_dict(b)


def _flatten(values: Mapping[str, Any], prefix: str = '') -> Dict[str, Any]:
    flat: Dict[str, Any] = {}
    for key, value in values.items():
        name = f'{prefix}{key}'
        if isinstance(value, dict):
            flat.update(_flatten(value, f'{name}.'))
        else:
            flat[name] = value
    return flat


def _log_report(config: Optional[TakeoverSpec], report: Optional[Mapping[str, Any]],
                started: Sequence[str]) -> None:
    if config is None or report is None:
        return
    LOG.info('launch takeover of %s/%s (%s mode): started %s', config.package,
             config.launch_file, config.mode, ', '.join(started) or 'nothing')
    for item in report.get('carried', []):
        LOG.info('takeover carried over %s for %s %s', item['code'], ', '.join(item['nodes']),
                 item.get('detail') or '')
    for item in report.get('lost', []):
        LOG.warning('takeover (per-node) does not keep %s %s %s', item['code'],
                    ', '.join(item.get('nodes') or []), item.get('detail') or '')
    if report.get('suggest_whole'):
        LOG.warning('some launch behaviour is lost when nodes run one by one; '
                    '--launch-mode whole runs the launch file as it is')
