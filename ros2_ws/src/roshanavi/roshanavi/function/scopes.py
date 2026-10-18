"""Where function / class node code may come from (docs/design/user-code.md).

Three scopes, searched in this order (the first one that has a top-level name wins):

- **A. workspace** (always on): Python packages of the ROS packages in ``<workspace>/src`` — the
  ament_python layout ``<pkg>/<pkg>/__init__.py``, any Python package directly in a ROS package,
  and the directories ament_cmake_python installs (``ament_python_install_package(<name>
  [PACKAGE_DIR <dir>])`` in ``CMakeLists.txt``). Containment root: ``<workspace>/src``.
- **B. code paths** (opt-in, ``code_paths:`` of the project file): plain Python projects. The
  registered directory may be a package itself, hold packages (flat layout) or hold them in
  ``src/`` (src layout). Containment root: the registered directory.
- **C. installed modules** (opt-in, ``installed_modules:``): see :mod:`.installed`.

Nothing here imports user code. Directories named ``.git`` (and every hidden directory) are
never entered.
"""

import os
import re
import sys
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Tuple, Union

from ..launcher.discovery import scan_sources
from ..launcher.errors import LauncherError
from ..launcher.schema import RESERVED_MODULE_TOPS
from ..launcher.validate import CONTROL_RE

SCOPE_WORKSPACE = 'workspace'
SCOPE_CODE_PATH = 'code_path'
SCOPE_INSTALLED = 'installed'

IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
SKIP_DIRS = {'test', 'tests', '__pycache__', 'build', 'install', 'log', 'launch', 'resource'}
CODE_PATH_SKIP_DIRS = SKIP_DIRS | {'dist', 'venv', 'env', 'node_modules', 'site-packages',
                                   'docs', 'doc'}
MAX_CODE_PATHS = 20
MAX_INSTALLED_MODULES = 50

# Top-level names a user package must not take: the node process itself imports these, and the
# loader puts the user's package into ``sys.modules`` under its name (it would replace them).
NODE_RUNTIME_TOPS = frozenset({
    'roshanavi', 'rclpy', 'rpyutils', 'rosidl_runtime_py', 'rosidl_parser', 'rosidl_pycommon',
    'ament_index_python', 'builtin_interfaces', 'std_msgs', 'sensor_msgs', 'rcl_interfaces',
    'action_msgs', 'unique_identifier_msgs', 'service_msgs', 'type_description_interfaces',
    'rosgraph_msgs', 'lifecycle_msgs', 'example_interfaces', 'audio_common_msgs', 'numpy', 'yaml',
    'pydantic', 'pydantic_core', 'typing_extensions', 'PIL', 'launch', 'launch_ros'})

# Directories that are far too broad to register as a code path.
_BROAD_DIRS = ('/', '/bin', '/boot', '/dev', '/etc', '/home', '/lib', '/lib64', '/media', '/mnt',
               '/opt', '/proc', '/root', '/run', '/sbin', '/srv', '/sys', '/tmp', '/usr',
               '/usr/lib', '/usr/local', '/var')

_CMAKE_PROJECT_RE = re.compile(r'project\s*\(\s*([A-Za-z0-9_]+)', re.IGNORECASE)
_CMAKE_INSTALL_RE = re.compile(r'ament_python_install_package\s*\(([^)]*)\)', re.IGNORECASE)


@dataclass(frozen=True)
class PythonPackage:
    """A top-level Python package that function / class nodes can import from source."""

    ros_package: Optional[str]  # A: the ROS package; B: None
    base_dir: str               # the directory that holds the package (for messages)
    top: str                    # the import name
    scope: str = SCOPE_WORKSPACE
    root: str = ''              # containment root (realpath): <workspace>/src or the code path
    source: str = ''            # A: the ROS package's source dir; B: the code path as registered
    dir: str = ''               # the package directory (defaults to base_dir/top)

    @property
    def path(self) -> str:
        return self.dir or os.path.join(self.base_dir, self.top)


@dataclass(frozen=True)
class CodeLocations:
    """The three scopes for one workspace (the project's ``code_paths`` / ``installed_modules``).

    ``search_path`` is where installed modules are looked up: None = this interpreter's
    ``sys.path`` (the node process); the server passes the node interpreter's path.
    """

    workspace: str
    code_paths: Tuple[str, ...] = ()
    installed_modules: Tuple[str, ...] = ()
    search_path: Optional[Tuple[str, ...]] = None
    data_dir: Optional[str] = None

    @classmethod
    def of(cls, value: Union['CodeLocations', str]) -> 'CodeLocations':
        if isinstance(value, CodeLocations):
            return value
        return cls(workspace=os.path.realpath(str(value)))

    @property
    def src(self) -> str:
        return os.path.realpath(os.path.join(self.workspace, 'src'))

    def code_path_real(self, path: str) -> str:
        return os.path.realpath(os.path.join(self.workspace, os.path.expanduser(path)))



def inside(path: str, root: str) -> bool:
    return path == root or path.startswith(os.path.join(root, ''))


def is_reserved_top(top: str) -> bool:
    """A user package (scope A / B) may not be called like the standard library or the node's
    own runtime modules (it would replace them inside the node process)."""
    return top in RESERVED_MODULE_TOPS or top in NODE_RUNTIME_TOPS \
        or top in getattr(sys, 'stdlib_module_names', ())


def _candidate_dir(name: str, skip: Iterable[str]) -> bool:
    return bool(IDENT_RE.match(name)) and name not in skip and not name.startswith('.')


def _has_init(path: str) -> bool:
    return os.path.isfile(os.path.join(path, '__init__.py'))


def _read_small(path: str, limit: int = 256 * 1024) -> str:
    try:
        with open(path, encoding='utf-8', errors='replace') as fh:
            return fh.read(limit)
    except OSError:
        return ''


def cmake_python_packages(source_dir: str) -> List[Tuple[str, str]]:
    """``[(import name, directory)]`` from ``ament_python_install_package`` in CMakeLists.txt."""
    text = _read_small(os.path.join(source_dir, 'CMakeLists.txt'))
    if not text:
        return []
    text = re.sub(r'#[^\n]*', '', text)
    project = _CMAKE_PROJECT_RE.search(text)
    project_name = project.group(1) if project else ''
    found = []
    for match in _CMAKE_INSTALL_RE.finditer(text):
        args = match.group(1).replace('${PROJECT_NAME}', project_name).split()
        if not args:
            continue
        name, rel = args[0].strip('"'), args[0].strip('"')
        if 'PACKAGE_DIR' in args[1:-1]:
            rel = args[args.index('PACKAGE_DIR') + 1].strip('"')
        for var in ('${CMAKE_CURRENT_SOURCE_DIR}', '${CMAKE_CURRENT_LIST_DIR}',
                    '${PROJECT_SOURCE_DIR}'):
            rel = rel.replace(var + '/', '').replace(var, '.')
        if '$' in rel or not IDENT_RE.match(name):
            continue  # another CMake variable: cannot know statically
        found.append((name, os.path.normpath(os.path.join(source_dir, rel))))
    return found


def workspace_packages(locations: CodeLocations) -> List[PythonPackage]:
    """Scope A: Python packages inside each ROS package of ``<workspace>/src``."""
    found: Dict[str, PythonPackage] = {}
    src = locations.src
    for ros_name, source_dir in sorted(scan_sources(src).items()):
        if not inside(os.path.realpath(source_dir), src):
            continue
        candidates: List[Tuple[str, str]] = []
        try:
            entries = sorted(os.listdir(source_dir))
        except OSError:
            entries = []
        candidates += [(entry, os.path.join(source_dir, entry)) for entry in entries
                       if _candidate_dir(entry, SKIP_DIRS)]
        candidates += cmake_python_packages(source_dir)
        for top, path in candidates:
            real = os.path.realpath(path)
            if top in found or is_reserved_top(top) or not _has_init(path) \
                    or not inside(real, src):
                continue
            found[top] = PythonPackage(ros_name, os.path.dirname(path), top, SCOPE_WORKSPACE,
                                       src, source_dir, path)
    return list(found.values())


def code_path_layout(real: str) -> List[Tuple[str, str, str]]:
    """``[(top, package dir, layout)]`` of one registered directory (flat / src / package)."""
    if _has_init(real):
        top = os.path.basename(real)
        return [(top, real, 'package')] if IDENT_RE.match(top) else []
    out = []
    for parent, layout in ((real, 'flat'), (os.path.join(real, 'src'), 'src')):
        try:
            entries = sorted(os.listdir(parent))
        except OSError:
            continue
        for entry in entries:
            path = os.path.join(parent, entry)
            if _candidate_dir(entry, CODE_PATH_SKIP_DIRS) and _has_init(path):
                out.append((entry, path, layout))
    return out


def code_path_packages(locations: CodeLocations,
                       taken: Iterable[str] = ()) -> List[PythonPackage]:
    """Scope B: packages of every registered code path that still checks out."""
    used = set(taken)
    found: List[PythonPackage] = []
    for path in locations.code_paths:
        try:
            real = check_code_path(path, locations)
        except LauncherError:
            continue
        for top, pkg_dir, _layout in code_path_layout(real):
            if top in used or is_reserved_top(top) \
                    or not inside(os.path.realpath(pkg_dir), real):
                continue
            used.add(top)
            found.append(PythonPackage(None, os.path.dirname(pkg_dir), top, SCOPE_CODE_PATH,
                                       real, path, pkg_dir))
    return found


def source_packages(locations: CodeLocations) -> List[PythonPackage]:
    """Scopes A then B (a top-level name is taken by the first scope that has it)."""
    a = workspace_packages(locations)
    return a + code_path_packages(locations, [p.top for p in a])


# ---- registering code paths and installed modules -----------------------------------------------
def check_code_path(path: str, locations: CodeLocations) -> str:
    """The realpath of a registered code path, or LauncherError(``invalid_code_path``) why not."""
    if not isinstance(path, str) or not path.strip() or len(path) > 1024 \
            or CONTROL_RE.search(path):
        raise LauncherError('invalid_code_path', 'a code path must be a non-empty string without '
                            'control characters (at most 1024 characters)')
    real = locations.code_path_real(path.strip())
    if '.git' in real.split(os.sep):
        raise LauncherError('invalid_code_path', f'{path}: the inside of .git cannot be a code '
                            'path')
    if real in _BROAD_DIRS or real == os.path.realpath(os.path.expanduser('~')):
        raise LauncherError('invalid_code_path', f'{path}: this directory is too broad; register '
                            'the folder of your project instead')
    if locations.data_dir:
        data = os.path.realpath(locations.data_dir)
        if inside(real, data) or inside(data, real):
            raise LauncherError('invalid_code_path', f'{path}: the data folder (uploads, '
                                'recordings) cannot be a code path')
    if not os.path.isdir(real):
        raise LauncherError('invalid_code_path', f'{path}: no such directory ({real})', 404)
    return real
