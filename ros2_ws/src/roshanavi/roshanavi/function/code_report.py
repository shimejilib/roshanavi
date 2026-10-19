"""「コードの場所」: what each scope found, and why other code did not become a candidate.

``GET /api/functions/locations`` (docs/design/user-code.md). Everything is read statically:
files are listed and parsed with :mod:`ast`, ``.gitmodules`` is read as text, git is never run
and ``.git`` is never entered. The UI turns each problem ``code`` into a plain-Japanese reason
and the next step; paths are the user's real paths.

Problem codes: ``no_src``, ``no_init``, ``namespace_package``, ``loose_files``, ``not_ros_package``, ``syntax_error``,
``no_members``, ``private_only``, ``submodule_empty``, ``outside_symlink``, ``reserved_name``,
``name_collision``, ``code_path_invalid``, ``code_path_empty``, ``installed_not_found``.
"""

import os
import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from ..launcher.discovery import IGNORE_MARKERS, MAX_SRC_DEPTH, scan_sources
from ..launcher.errors import LauncherError
from ..launcher.schema import RESERVED_MODULE_TOPS
from . import installed
from .modules import _walk_package, installed_entries, search_path_of, source_packages
from .scopes import (CODE_PATH_SKIP_DIRS, IDENT_RE, SCOPE_CODE_PATH, SCOPE_WORKSPACE, SKIP_DIRS,
                     CodeLocations, PythonPackage, check_code_path, cmake_python_packages,
                     code_path_layout, inside, is_reserved_top)
from .signatures import SourceSyntaxError, parse_source, public_members, skipped_members

MAX_PROBLEMS = 200
HOST_SRC_HINT_ENV = 'ROSHANAVI_HOST_SRC_HINT'
MAX_HOST_SRC_HINT = 200
MAX_FILES_CHECKED = 500
_LOOSE_IGNORED = {'setup.py', 'conftest.py', '__init__.py'}
_GITMODULES_PATH_RE = re.compile(r'^\s*path\s*=\s*(.+?)\s*$')
_SUBMODULE_COMMAND = 'git submodule update --init --recursive'


class _Problems:
    def __init__(self) -> None:
        self.items: List[Dict[str, Any]] = []
        self._seen: set = set()

    def add(self, code: str, **fields: Any) -> None:
        key = (code, fields.get('path'), fields.get('file'), fields.get('top'))
        if key in self._seen or len(self.items) >= MAX_PROBLEMS:
            return
        self._seen.add(key)
        self.items.append({'code': code, **fields})


def _listdir(path: str) -> List[str]:
    try:
        return sorted(os.listdir(path))
    except OSError:
        return []


def _has_py(path: str, depth: int = 3, budget: int = 2000) -> bool:
    """Any ``.py`` file within ``depth`` levels (bounded; hidden dirs and .git skipped)."""
    stack = [(path, 0)]
    while stack and budget > 0:
        current, level = stack.pop()
        for entry in _listdir(current):
            budget -= 1
            full = os.path.join(current, entry)
            if entry.endswith('.py') and os.path.isfile(full):
                return True
            if level < depth and not entry.startswith('.') and not os.path.islink(full) \
                    and os.path.isdir(full):
                stack.append((full, level + 1))
    return False


def _direct_py(path: str) -> List[str]:
    return [e for e in _listdir(path) if e.endswith('.py') and os.path.isfile(os.path.join(path, e))]


def _namespace_dir(path: str) -> bool:
    """A directory without ``__init__.py`` that holds packages: a PEP 420 namespace package."""
    if os.path.isfile(os.path.join(path, '__init__.py')):
        return False
    return any(not e.startswith('.') and os.path.isfile(os.path.join(path, e, '__init__.py'))
               for e in _listdir(path))


def _missing_init(path: str, problems: _Problems, **fields: Any) -> bool:
    """Report a directory that would be code but has no ``__init__.py``; True when reported."""
    if os.path.isfile(os.path.join(path, '__init__.py')):
        return False
    if _namespace_dir(path):
        problems.add('namespace_package', path=path, **fields)
        return True
    if _direct_py(path):
        problems.add('no_init', path=path, **fields)
        return True
    return False


# ---- git submodules (read .gitmodules only) ------------------------------------------------------
def gitmodule_paths(root: str) -> List[str]:
    """``path = ...`` entries of ``<root>/.gitmodules`` (absolute, contained in ``root``)."""
    text = ''
    try:
        with open(os.path.join(root, '.gitmodules'), encoding='utf-8', errors='replace') as fh:
            text = fh.read(256 * 1024)
    except OSError:
        return []
    out = []
    real_root = os.path.realpath(root)
    for line in text.splitlines():
        match = _GITMODULES_PATH_RE.match(line)
        if not match:
            continue
        rel = match.group(1).strip().strip('"')
        full = os.path.normpath(os.path.join(real_root, rel))
        if inside(full, real_root) and full != real_root:
            out.append(full)
    return out


def _empty_dir(path: str) -> bool:
    return not os.path.isdir(path) or not [e for e in _listdir(path) if e != '.git']


def _submodules(roots: Iterable[str], problems: _Problems) -> List[str]:
    """Report unsynced submodules; return their paths (to skip other checks there)."""
    empty = []
    for root in roots:
        for path in gitmodule_paths(root):
            if _empty_dir(path):
                empty.append(path)
                problems.add('submodule_empty', path=path, root=root, command=_SUBMODULE_COMMAND)
    return empty


# ---- scope A ---------------------------------------------------------------------------------
def _walk_src(src: str, problems: _Problems) -> List[str]:
    """Symlinks that leave ``<workspace>/src``; returns directories that hold a .gitmodules."""
    git_roots = []
    for current, dirs, files in os.walk(src, followlinks=False):
        depth = os.path.relpath(current, src).count(os.sep)
        if '.gitmodules' in files:
            git_roots.append(current)
        if any(marker in files for marker in IGNORE_MARKERS):
            dirs[:] = []
            continue
        for entry in [*dirs, *files]:
            full = os.path.join(current, entry)
            if os.path.islink(full) and not inside(os.path.realpath(full), src):
                problems.add('outside_symlink', path=full, target=os.path.realpath(full))
        if 'package.xml' in files:
            dirs[:] = []   # inside a ROS package: its Python packages are checked on their own
            continue
        dirs[:] = [] if depth >= MAX_SRC_DEPTH else sorted(
            d for d in dirs if not d.startswith('.') and not os.path.islink(os.path.join(current, d)))
    return git_roots


def _check_ros_package(ros_name: str, source_dir: str, src: str, problems: _Problems) -> None:
    loose = [f for f in _direct_py(source_dir) if f not in _LOOSE_IGNORED]
    if loose:
        problems.add('loose_files', path=source_dir, files=loose[:10], package=ros_name)
    declared = {os.path.realpath(path) for _top, path in cmake_python_packages(source_dir)}
    for entry in _listdir(source_dir):
        full = os.path.join(source_dir, entry)
        if entry.startswith('.') or entry in SKIP_DIRS or not os.path.isdir(full) \
                or os.path.islink(full) and not inside(os.path.realpath(full), src):
            continue
        if os.path.realpath(full) not in declared:
            _missing_init(full, problems, package=ros_name)


def _check_package_tree(package: PythonPackage, problems: _Problems) -> None:
    """Inside one Python package: sub-directories without ``__init__.py``, outward symlinks."""
    for current, dirs, files in os.walk(package.path, followlinks=False):
        depth = os.path.relpath(current, package.path).count(os.sep)
        for entry in [*dirs, *files]:
            full = os.path.join(current, entry)
            if os.path.islink(full) and not inside(os.path.realpath(full), package.root):
                problems.add('outside_symlink', path=full, target=os.path.realpath(full),
                             scope=package.scope)
        keep = []
        for d in sorted(dirs):
            full = os.path.join(current, d)
            if d.startswith('.') or d in SKIP_DIRS or os.path.islink(full):
                continue
            if os.path.isfile(os.path.join(full, '__init__.py')):
                keep.append(d)
            elif _direct_py(full):
                problems.add('no_init', path=full, scope=package.scope)
        dirs[:] = keep if depth < 3 else []


def _check_files(packages: List[PythonPackage], problems: _Problems) -> None:
    checked = 0
    for package in packages:
        for path, rel in _walk_package(package):
            if checked >= MAX_FILES_CHECKED:
                return
            checked += 1
            if not inside(os.path.realpath(path), package.root):
                continue
            try:
                tree = parse_source(path)
            except SourceSyntaxError as exc:
                problems.add('syntax_error', file=path, line=exc.line, message=exc.detail)
                continue
            except LauncherError as exc:
                problems.add('syntax_error', file=path, line=None, message=str(exc))
                continue
            if os.path.basename(path) == '__init__.py':
                continue
            functions, classes = public_members(tree)
            if functions or classes:
                continue
            private = [s['name'] for s in skipped_members(tree) if s['reason'] == 'private']
            if private:
                problems.add('private_only', file=path, names=private[:10])
            else:
                problems.add('no_members', file=path,
                             skipped=[s['name'] for s in skipped_members(tree)][:10])


def _workspace(locations: CodeLocations, problems: _Problems) -> Tuple[List[str], List[str]]:
    """Scope A checks; returns (unsynced submodule dirs, .gitmodules roots)."""
    src = locations.src
    if not os.path.isdir(src):
        problems.add('no_src', path=src)
        return [], []
    git_roots = _walk_src(src, problems)
    sources = scan_sources(src)
    empty = _submodules([locations.workspace, src, *git_roots], problems)
    for entry in _listdir(src):
        full = os.path.join(src, entry)
        if entry.startswith('.') or os.path.islink(full) or not os.path.isdir(full) \
                or full in empty or any(m in _listdir(full) for m in IGNORE_MARKERS):
            continue
        real = os.path.realpath(full)
        if not any(inside(d, real) for d in sources.values()) and _has_py(full):
            problems.add('not_ros_package', path=full)
    seen: Dict[str, str] = {}
    for ros_name, source_dir in sorted(sources.items()):
        _check_ros_package(ros_name, source_dir, src, problems)
        candidates = [(e, os.path.join(source_dir, e)) for e in _listdir(source_dir)
                      if IDENT_RE.match(e) and e not in SKIP_DIRS]
        for top, path in candidates + cmake_python_packages(source_dir):
            if not os.path.isfile(os.path.join(path, '__init__.py')) \
                    or top in RESERVED_MODULE_TOPS:   # roshanavi's own source: not user code
                continue
            if is_reserved_top(top):
                problems.add('reserved_name', path=path, top=top)
            elif top in seen and seen[top] != path:
                problems.add('name_collision', top=top, kept=seen[top], ignored=path,
                             kept_scope=SCOPE_WORKSPACE, ignored_scope=SCOPE_WORKSPACE)
            else:
                seen[top] = path
    return empty, git_roots


# ---- scope B ---------------------------------------------------------------------------------
def _code_path_status(locations: CodeLocations, path: str, taken: Dict[str, Tuple[str, str]],
                      problems: _Problems) -> Dict[str, Any]:
    try:
        real = check_code_path(path, locations)
    except LauncherError as exc:
        problems.add('code_path_invalid', path=path, message=str(exc))
        return {'path': path, 'real': None, 'status': 'invalid', 'error': str(exc),
                'packages': []}
    _submodules([real], problems)
    layout = code_path_layout(real)
    packages = []
    for top, pkg_dir, kind in layout:
        if is_reserved_top(top):
            problems.add('reserved_name', path=pkg_dir, top=top)
            continue
        if top in taken:
            problems.add('name_collision', top=top, kept=taken[top][1], ignored=pkg_dir,
                         kept_scope=taken[top][0], ignored_scope=SCOPE_CODE_PATH)
            continue
        taken[top] = (SCOPE_CODE_PATH, pkg_dir)
        packages.append({'top': top, 'dir': pkg_dir, 'layout': kind})
    reported = False
    if not os.path.isfile(os.path.join(real, '__init__.py')):
        roots = [real, os.path.join(real, 'src')]
        dirs = [os.path.join(r, e) for r in roots for e in _listdir(r)
                if not e.startswith('.') and e not in CODE_PATH_SKIP_DIRS
                and os.path.isdir(os.path.join(r, e))]
        for d in dirs:
            reported = _missing_init(d, problems, scope=SCOPE_CODE_PATH) or reported
        if not layout and not reported and _direct_py(real):
            problems.add('no_init', path=real, scope=SCOPE_CODE_PATH)
            reported = True
    if not layout and not reported:
        problems.add('code_path_empty', path=real)
    return {'path': path, 'real': real, 'status': 'ok', 'packages': packages}


# ---- scope C ---------------------------------------------------------------------------------
def _installed_status(locations: CodeLocations, taken: Dict[str, Tuple[str, str]],
                      problems: _Problems) -> List[Dict[str, Any]]:
    out = []
    search = search_path_of(locations)
    for entry in locations.installed_modules:
        top = entry.split('.')[0]
        if top in taken:
            problems.add('name_collision', top=top, kept=taken[top][1], ignored=entry,
                         kept_scope=taken[top][0], ignored_scope='installed')
            out.append({'module': entry, 'status': 'shadowed', 'file': None, 'listable': False,
                        'shadowed_by': taken[top][1]})
            continue
        located = installed.locate(entry, search)
        if located is None:
            problems.add('installed_not_found', module=entry)
            out.append({'module': entry, 'status': 'not_found', 'file': None, 'listable': False})
            continue
        status = {installed.KIND_EXTENSION: 'extension',
                  installed.KIND_NAMESPACE: 'namespace'}.get(located.kind, 'found')
        out.append({'module': entry, 'status': status, 'file': located.file,
                    'listable': located.listable})
    return out


def host_src_hint() -> Optional[str]:
    """Free text from ``$ROSHANAVI_HOST_SRC_HINT``: where ``src`` is on the user's PC (Docker, where
    the server only sees ``/ws/src``). Control characters are dropped and the length is capped; the
    UI shows it as plain text, never as HTML or a link."""
    text = ''.join(ch for ch in os.environ.get(HOST_SRC_HINT_ENV, '') if ch.isprintable())
    return text.strip()[:MAX_HOST_SRC_HINT] or None


def report(locations: CodeLocations, python: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """The whole 「コードの場所」 panel: scopes, problems and where to put code."""
    problems = _Problems()
    _workspace(locations, problems)
    packages = source_packages(locations)
    a = [p for p in packages if p.scope == SCOPE_WORKSPACE]
    taken: Dict[str, Tuple[str, str]] = {p.top: (SCOPE_WORKSPACE, p.path) for p in a}
    code_paths = [_code_path_status(locations, p, taken, problems) for p in locations.code_paths]
    for package in packages:
        _check_package_tree(package, problems)
    _check_files(packages, problems)
    installed_status = _installed_status(locations, taken, problems)
    src = locations.src
    return {
        'workspace': locations.workspace, 'src': src, 'src_exists': os.path.isdir(src),
        'src_writable': os.path.isdir(src) and os.access(src, os.W_OK),
        'host_src_hint': host_src_hint(),
        'scopes': {
            'workspace': {'root': src, 'packages': [
                {'top': p.top, 'ros_package': p.ros_package, 'dir': p.path} for p in a]},
            'code_paths': code_paths,
            'installed_modules': installed_status,
        },
        'installed_listed': len(installed_entries(locations, list(taken))),
        'problems': problems.items,
        'place_here': [{'scope': SCOPE_WORKSPACE, 'root': src}] + [
            {'scope': SCOPE_CODE_PATH, 'root': c['real']} for c in code_paths if c['real']],
        'python': python,
    }
