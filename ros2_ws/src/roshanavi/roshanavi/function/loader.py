"""Import a user's function from the workspace source tree, and re-import it on save.

Hot reload design (docs/design/nodes.md): a *fresh import* inside the running node,
not ``importlib.reload`` and not a process restart.

- Every module of the user's Python package is dropped from ``sys.modules``
  and the package is imported again from its source directory, so helper
  modules of the same package are reloaded too (``importlib.reload`` only
  re-runs one module and leaves stale references in the others).
- If the new import fails (syntax error, exception at import time, the
  function was renamed), the old modules are put back and the old function
  keeps running; the error is reported with file:line. Fixing the file loads it.
- The node, its subscriptions and publisher stay up: no rediscovery gap, no
  lost "latest value" of a multi-input join, and it is fast (milliseconds).
  A process restart would cost ~1 s of rclpy start-up plus DDS discovery on
  every save.
- Files are polled (mtime + size, every 0.5 s): inotify does not reach
  through every bind mount / WSL path and would need a new dependency.
- Bytecode is neither read nor written (``pycache_prefix`` points at an empty
  private directory): a quick edit within the same second and the same size
  can never load a stale ``.pyc``, and nothing is written into the source tree.

Limits: module-level state starts over on each reload; C extensions and
modules outside the user's package are not reloaded (libraries the node imported from a
registered code path - scope B, ``code_imports`` - count as the user's own and are reloaded
with it). Installed modules (scope C,
docs/design/user-code.md) are imported normally from the node's Python environment and are
never reloaded (reinstall, then restart the node).
"""

import importlib
import importlib.machinery
import importlib.util
import inspect
import os
import sys
import tempfile
import threading
import time
import traceback
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from ..launcher.errors import LauncherError
from . import code_imports, node_env
from .modules import ResolvedModule, resolve_module
from .scopes import SCOPE_INSTALLED, CodeLocations
from .signatures import imports_of, parse_source

POLL_SEC = 0.5
SLOW_IMPORT_SEC = 1.0   # 「モジュールの読み込み時に時間がかかっています」


@dataclass(frozen=True)
class Problem:
    """An error in the user's code: what happened and where (``logic.py:12``)."""

    kind: str          # 'import' | 'call' | 'convert' | 'publish' (class nodes: 'init' | 'state' |
    #                    'param' | 'action' | 'close')
    message: str
    location: Optional[str]
    missing_module: Optional[str] = None   # ModuleNotFoundError of a dependency (not the user's)

    def to_dict(self) -> Dict[str, Any]:
        out = {'kind': self.kind, 'message': self.message, 'location': self.location}
        if self.missing_module:
            out['missing_module'] = self.missing_module
        return out

    def text(self) -> str:
        return f'{self.location}: {self.message}' if self.location else self.message


class LoadError(Exception):
    def __init__(self, problem: Problem):
        super().__init__(problem.text())
        self.problem = problem


def _relative(path: str, base: str) -> str:
    real = os.path.realpath(path)
    return os.path.relpath(real, base) if real.startswith(os.path.join(base, '')) else \
        os.path.basename(path)


def user_location(exc: BaseException, package_dir: str, base_dir: str) -> Optional[str]:
    """``pkg/logic.py:12 (shout)``: the deepest traceback frame inside the user's package."""
    if isinstance(exc, SyntaxError) and exc.filename:
        return f'{_relative(exc.filename, base_dir)}:{exc.lineno}'
    root = os.path.join(os.path.realpath(package_dir), '')
    for frame in reversed(traceback.extract_tb(exc.__traceback__)):
        if os.path.realpath(frame.filename).startswith(root):
            return f'{_relative(frame.filename, base_dir)}:{frame.lineno} ({frame.name})'
    return None


def missing_module_of(exc: BaseException, own_top: Optional[str]) -> Optional[str]:
    """The dependency a ModuleNotFoundError is about (``numpy``), or None (the user's own
    package or another error). Follows one ``raise ImportError(...) from`` wrapper."""
    for candidate in (exc, exc.__cause__, exc.__context__):
        if isinstance(candidate, ModuleNotFoundError) and candidate.name:
            name = candidate.name
            return None if own_top and name.split('.')[0] == own_top else name
    return None


def describe(exc: BaseException) -> str:
    text = str(exc)
    return f'{type(exc).__name__}: {text}' if text else type(exc).__name__


class FunctionLoader:
    member_label = 'function'   # what is looked up in the module (class nodes: 'class')

    def __init__(self, workspace: Union[str, CodeLocations], module: str, function: str):
        self.locations = CodeLocations.of(workspace)
        self.workspace = os.path.realpath(self.locations.workspace)
        self.module = module
        self.function_name = function
        self.function: Optional[Callable[..., Any]] = None
        self.resolved: Optional[ResolvedModule] = None
        self.signature: Optional[inspect.Signature] = None
        self.loads = 0
        self.problem: Optional[Problem] = None
        self._stamps: Dict[str, Tuple[int, int]] = {}
        self._lock = threading.Lock()
        self.import_seconds: Optional[float] = None
        self.environment: Dict[str, Any] = {'python': node_env.python_info()}
        self.notices: List[Dict[str, Any]] = []
        sys.dont_write_bytecode = True
        sys.pycache_prefix = tempfile.mkdtemp(prefix='roshanavi-function-pyc-')
        # Scope B folders are libraries too (``import simple_pid`` from a package of scope A).
        # Node process only: the server never constructs a loader (docs/design/user-code.md).
        self._code_imports = code_imports.install(self.locations)

    # ---- import -----------------------------------------------------------------
    def _package_modules(self, top: str) -> Dict[str, Any]:
        return {name: mod for name, mod in sys.modules.items()
                if name == top or name.startswith(top + '.')}

    def _dependency_modules(self) -> Dict[str, Any]:
        """Modules the node imported from registered code paths as libraries (scope B)."""
        return self._code_imports.served_modules() if self._code_imports else {}

    def _owned_modules(self, top: str) -> Dict[str, Any]:
        """What a (re)load drops: the target package and the code-path libraries it imported."""
        return {**self._dependency_modules(), **self._package_modules(top)}

    def _import(self, resolved: ResolvedModule) -> Callable[..., Any]:
        if resolved.scope == SCOPE_INSTALLED:
            module = importlib.import_module(resolved.module)  # the node's own environment
        else:
            module = self._import_source(resolved)
        function = getattr(module, self.function_name, None)
        if function is None:
            raise AttributeError(f'{resolved.module} has no {self.member_label} '
                                 f'{self.function_name!r}')
        self._check_member(function, resolved.module)
        return function

    def _import_source(self, resolved: ResolvedModule) -> Any:
        top = resolved.package.top
        init = os.path.join(resolved.package.path, '__init__.py')
        spec = importlib.util.spec_from_file_location(
            top, init, submodule_search_locations=[resolved.package.path])
        if spec is None or spec.loader is None:
            raise ImportError(f'cannot load package {top} from {resolved.package.path}')
        package = importlib.util.module_from_spec(spec)
        setattr(package, USER_MARK, True)
        sys.modules[top] = package
        spec.loader.exec_module(package)
        module = package if resolved.module == top else importlib.import_module(resolved.module)
        loaded_from = os.path.realpath(getattr(module, '__file__', '') or '')
        if loaded_from != resolved.file:  # never run code from anywhere else
            raise ImportError(f'{resolved.module} was loaded from {loaded_from}, '
                              f'not {resolved.file}')
        return module

    def _check_member(self, member: Any, module: str) -> None:
        # builtin: a function of an extension module (scope C, typed by hand)
        if not (inspect.isfunction(member) or inspect.isbuiltin(member)):
            raise TypeError(f'{module}.{self.function_name} is not a function')

    def load(self) -> Callable[..., Any]:
        """(Re)import; on failure the previous function and modules stay (raises LoadError)."""
        with self._lock:
            try:
                resolved = resolve_module(self.locations, self.module)
            except LauncherError as exc:
                self.problem = Problem('import', str(exc), None)
                self._stamps = {path: _stamp(path) for path in self._stamps}  # no retry loop
                raise LoadError(self.problem) from exc
            if resolved.scope == SCOPE_INSTALLED and self.function is not None:
                return self.function   # installed modules are not reloaded
            top = resolved.package.top
            saved = self._owned_modules(top) if resolved.scope != SCOPE_INSTALLED else {}
            if saved and not _same_package(saved.get(top), resolved):
                self.problem = Problem('import', f'the name {top!r} is already used inside the '
                                       'node (a library roshanavi imports); rename your package',
                                       None)
                raise LoadError(self.problem)
            for name in saved:
                del sys.modules[name]
            importlib.invalidate_caches()
            started = time.monotonic()
            try:
                function = self._import(resolved)
            except BaseException as exc:  # SystemExit / anything raised by user code at import
                if isinstance(exc, KeyboardInterrupt):
                    raise
                if resolved.scope != SCOPE_INSTALLED:
                    for name in list(self._owned_modules(top)):
                        del sys.modules[name]
                    sys.modules.update(saved)
                self.problem = Problem('import', describe(exc),
                                       user_location(exc, resolved.package.path,
                                                     resolved.package.base_dir),
                                       missing_module_of(exc, top))
                self._after_load(resolved, time.monotonic() - started)
                raise LoadError(self.problem) from exc
            self.function, self.resolved = function, resolved
            self.signature = _signature(function)
            self.loads += 1
            self.problem = None
            self._after_load(resolved, time.monotonic() - started)
            return function

    def _after_load(self, resolved: ResolvedModule, seconds: float) -> None:
        self.import_seconds = round(seconds, 3)
        self._watch(resolved)
        self.environment = environment_of(resolved, self.workspace)
        self.notices = self._notices(resolved, seconds)

    def _notices(self, resolved: ResolvedModule, seconds: float) -> List[Dict[str, Any]]:
        notices: List[Dict[str, Any]] = []
        if seconds >= SLOW_IMPORT_SEC:
            notices.append({'code': 'slow_import', 'seconds': round(seconds, 1)})
        if resolved.scope == SCOPE_INSTALLED:
            notices.append({'code': 'no_hot_reload_installed'})
        if resolved.kind == 'extension':
            notices.append({'code': 'extension_module'})
        files = self.watched_files
        if any('rclpy' in _imports(path) for path in files if path.endswith('.py')):
            notices.append({'code': 'imports_rclpy'})
        extensions = sorted(os.path.basename(p) for p in files
                            if p.endswith(tuple(importlib.machinery.EXTENSION_SUFFIXES)))
        if extensions and resolved.scope != SCOPE_INSTALLED:
            notices.append({'code': 'extension_no_reload', 'files': extensions[:10]})
        return notices

    # ---- watching ---------------------------------------------------------------
    def _watch(self, resolved: ResolvedModule) -> None:
        if resolved.scope == SCOPE_INSTALLED:
            self._stamps = {}   # installed modules are not reloaded
            return
        pkg_dir = os.path.join(resolved.package.path, '')
        real_dir = os.path.join(os.path.realpath(resolved.package.path), '')
        root = os.path.join(resolved.package.root, '') if resolved.package.root else real_dir
        files = {resolved.file, os.path.realpath(os.path.join(resolved.package.path,
                                                              '__init__.py'))}
        for mod in self._package_modules(resolved.package.top).values():
            path = getattr(mod, '__file__', None)
            if not path:
                continue
            real = os.path.realpath(path)
            # siblings of the same package (also an inward symlink to elsewhere in the root)
            if (real.startswith(real_dir) or path.startswith(pkg_dir)) and real.startswith(root):
                files.add(real)
        # code-path libraries imported by the package (scope B): edited -> same fresh import
        for mod in self._dependency_modules().values():
            path = getattr(mod, '__file__', None)
            if path:
                files.add(os.path.realpath(path))
        self._stamps = {path: _stamp(path) for path in sorted(f for f in files if f)}

    @property
    def watched_files(self) -> List[str]:
        return list(self._stamps)

    def changed(self) -> bool:
        """True when a watched file's mtime or size changed since the last (re)load."""
        return any(_stamp(path) != stamp for path, stamp in list(self._stamps.items()))

    def location_of_function(self) -> Optional[str]:
        if self.function is None or self.resolved is None:
            return None
        code = getattr(self.function, '__code__', None)
        if code is None:  # a builtin of an extension module
            return _relative(self.resolved.file or '', self.resolved.package.base_dir)
        return f'{_relative(code.co_filename, self.resolved.package.base_dir)}:' \
               f'{code.co_firstlineno}'


def environment_of(resolved: ResolvedModule, workspace: str) -> Dict[str, Any]:
    """The interpreter, and requirements.txt next to the code compared with what is installed."""
    package = resolved.package
    if resolved.scope == SCOPE_INSTALLED:
        directories: List[str] = []
    else:
        # A: the ROS package's directory; B: the registered directory; both: the package's parent
        directories = [d for d in (package.source if package.ros_package else package.root,
                                   package.base_dir) if d]
    return {'python': node_env.python_info(), 'scope': resolved.scope,
            'loaded_from': resolved.file,
            'requirements': node_env.check_requirements(directories, workspace)}


def _imports(path: str) -> List[str]:
    try:
        return imports_of(parse_source(path))
    except LauncherError:
        return []


USER_MARK = '__roshanavi_user_package__'


def _same_package(module: Any, resolved: ResolvedModule) -> bool:
    """``sys.modules[top]`` is a user package a loader imported from source (an earlier load),
    not a library of the node with the same name (that one must never be replaced)."""
    return module is None or bool(getattr(module, USER_MARK, False))


def _stamp(path: str) -> Tuple[int, int]:
    try:
        st = os.stat(path)
    except OSError:
        return (-1, -1)
    return (st.st_mtime_ns, st.st_size)


def _signature(function: Callable[..., Any]) -> Optional[inspect.Signature]:
    try:
        return inspect.signature(function)
    except (TypeError, ValueError):
        return None


def required_positional(signature: Optional[inspect.Signature]) -> Tuple[int, int]:
    """(required, maximum) positional arguments; maximum -1 = *args."""
    if signature is None:
        return 0, -1
    required = maximum = 0
    for param in signature.parameters.values():
        if param.kind == param.VAR_POSITIONAL:
            return required, -1
        if param.kind in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD):
            maximum += 1
            if param.default is param.empty:
                required += 1
    return required, maximum


class Watcher:
    """Polls the loader's files and reloads after a change (debounced: the file is stable)."""

    def __init__(self, loader: FunctionLoader, on_reload: Callable[[Optional[Problem]], None],
                 poll_sec: float = POLL_SEC, reload_fn: Optional[Callable[[], Any]] = None):
        self._loader = loader
        # How a changed file is reloaded; raises LoadError (class nodes reload on their own
        # worker thread so that user code only ever runs there).
        self._reload = reload_fn or loader.load
        self._on_reload = on_reload
        self._poll = poll_sec
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name='function-watch', daemon=True)

    def start(self) -> None:
        self._thread.start()

    def _run(self) -> None:
        while not self._stop.wait(self._poll):
            if not self._loader.changed():
                continue
            # Editors write in steps (truncate, write, rename): wait until it settles.
            before = [_stamp(p) for p in self._loader.watched_files]
            if self._stop.wait(min(self._poll, 0.2)):
                return
            if [_stamp(p) for p in self._loader.watched_files] != before:
                continue
            try:
                self._reload()
                self._on_reload(None)
            except LoadError as exc:
                self._on_reload(exc.problem)

    def close(self) -> None:
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout=2.0)

