"""Build button: ``colcon build --packages-select <pkg> --symlink-install``.

One build at a time, run in the workspace root, output streamed into a
:class:`LogBuffer` (log id ``_build``). On success the discovery cache is
refreshed and, optionally, running targets of that package are restarted.
A package that was not on ``AMENT_PREFIX_PATH`` when the server started is
reported with ``needs_resource``: targets started from roshanavi still find it
(see :mod:`.env`), but other terminals must re-source ``install/setup.bash``.
"""

import logging
import re
import shutil
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from .discovery import ORIGIN_WORKSPACE, Workspace
from .env import child_env
from .errors import LauncherError
from .logbuf import LogBuffer
from .process import ProcessRunner

LOG = logging.getLogger(__name__)

BUILD_LOG_ID = '_build'
MAX_ERROR_LINES = 12
CONTEXT_LINES = 4
ERROR_PATTERNS = [re.compile(p) for p in (
    r'\berror\b:',             # gcc / clang: file:line:col: error: ...
    r'^CMake Error',           # CMake configure errors
    r'^\s*File ".*", line \d+',  # Python tracebacks (setup.py)
    r'\b\w*Error\b: ',         # SyntaxError: ..., ModuleNotFoundError: ...
    r'^Traceback \(most recent call last\)',
    r'^Failed\s+<<<',          # colcon summary
    r'fatal error',
)]


NOTHING_BUILT = (re.compile(r'ignoring unknown package'),
                 re.compile(r'^Summary: 0 packages finished'))


def build_succeeded(code: int, lines: List[str]) -> bool:
    """colcon exits 0 when the package could not even be identified (e.g. a broken
    setup.py); treat "nothing was built" as a failure too."""
    return code == 0 and not any(p.search(ln) for p in NOTHING_BUILT for ln in lines)


def extract_errors(lines: List[str], limit: int = MAX_ERROR_LINES) -> List[str]:
    """First compiler/tool error lines plus a few lines of context (pure)."""
    for index, line in enumerate(lines):
        if any(p.search(line) for p in ERROR_PATTERNS):
            return [ln for ln in lines[index:index + limit] if ln.strip()][:limit]
    return [ln for ln in lines[-CONTEXT_LINES:] if ln.strip()]


class BuildRunner:
    def __init__(self, workspace: Workspace,
                 restart_package: Callable[[str], List[str]]):
        self._workspace = workspace
        self._restart_package = restart_package
        self.log = LogBuffer()
        self._lock = threading.Lock()
        self._runner: Optional[ProcessRunner] = None
        self._status: Dict[str, Any] = {'state': 'idle'}
        self._seq_start = 0

    def status(self) -> Dict[str, Any]:
        with self._lock:
            return dict(self._status)

    def start(self, package: str, restart_running: bool = True) -> Dict[str, Any]:
        info = self._workspace.package(package)
        if info.origin != ORIGIN_WORKSPACE or not info.source_dir:
            raise LauncherError('not_buildable', f'{package} is not a package in '
                                f'{self._workspace.root}/src', 400)
        colcon = shutil.which('colcon')
        if colcon is None:
            raise LauncherError('colcon_not_found', 'colcon is not installed', 500)
        argv = [colcon, 'build', '--packages-select', package, '--symlink-install',
                '--event-handlers', 'console_direct+']
        with self._lock:
            if self._runner is not None and self._runner.alive():
                raise LauncherError('build_running', 'another build is running', 409)
            self.log.clear()
            _, self._seq_start = self.log.since(0)
            was_sourced = info.sourced
            runner = ProcessRunner(argv, child_env(self._workspace.env), self._workspace.root,
                                   self.log, on_exit=lambda code: self._finished(
                                       package, code, restart_running, was_sourced))
            self._status = {'state': 'running', 'package': package, 'exit_code': None,
                            'started_at': time.time(), 'finished_at': None,
                            'error_lines': [], 'needs_resource': False, 'restarted': [],
                            'log_id': BUILD_LOG_ID}
            self._runner = runner
            runner.start()
        LOG.info('build of %s started', package)
        return self.status()

    def _finished(self, package: str, code: int, restart_running: bool,
                  was_sourced: bool) -> None:
        lines, _ = self.log.since(self._seq_start)
        texts = [ln['text'] for ln in lines if ln['stream'] != 'system']
        ok = build_succeeded(code, texts)
        restarted: List[str] = []
        if ok:
            self._workspace.refresh()
            if restart_running:
                restarted = self._restart_package(package)
        with self._lock:
            self._status = {**self._status, 'state': 'succeeded' if ok else 'failed',
                            'exit_code': code, 'finished_at': time.time(),
                            'error_lines': [] if ok else extract_errors(texts),
                            'needs_resource': ok and not was_sourced,
                            'restarted': restarted}
        (LOG.info if ok else LOG.warning)('build of %s finished with %s', package, code)

    def cancel(self) -> Dict[str, Any]:
        with self._lock:
            runner = self._runner
        if runner is None or not runner.alive():
            raise LauncherError('not_found', 'no build is running', 404)
        runner.stop()
        return self.status()

    def close(self) -> None:
        with self._lock:
            runner = self._runner
        if runner is not None and runner.alive():
            runner.stop()
