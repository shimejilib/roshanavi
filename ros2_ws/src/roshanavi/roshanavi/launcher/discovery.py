"""Workspace discovery: packages, executables and launch files (ament index).

Prefixes are searched in overlay order: the workspace's own ``install/``
(isolated or merged layout) first, then ``AMENT_PREFIX_PATH``. A package found
under ``<workspace>/install`` is ``origin="workspace"``; anything else is
``"system"``. ``sourced`` tells whether its prefix was on ``AMENT_PREFIX_PATH``
when the server started (a freshly built package is not, until re-sourcing).
Source directories come from a ``package.xml`` scan of ``<workspace>/src``.
The result is cached; :meth:`Workspace.refresh` rescans.
"""

import logging
import os
import threading
import time
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from typing import Any, Dict, List, Mapping, Optional, Tuple

from . import validate
from .errors import LauncherError

LOG = logging.getLogger(__name__)

INDEX_DIR = os.path.join('share', 'ament_index', 'resource_index', 'packages')
IGNORE_MARKERS = ('COLCON_IGNORE', 'AMENT_IGNORE', 'CATKIN_IGNORE')
MAX_SRC_DEPTH = 6
MAX_LAUNCH_DEPTH = 2
ORIGIN_WORKSPACE = 'workspace'
ORIGIN_SYSTEM = 'system'


@dataclass(frozen=True)
class PackageInfo:
    name: str
    origin: str
    prefix: Optional[str]
    sourced: bool
    source_dir: Optional[str]
    executables: Tuple[str, ...] = ()
    launch_files: Tuple[str, ...] = ()

    @property
    def built(self) -> bool:
        return self.prefix is not None

    def to_dict(self) -> Dict[str, Any]:
        return {'name': self.name, 'origin': self.origin, 'prefix': self.prefix,
                'sourced': self.sourced, 'built': self.built, 'source_dir': self.source_dir,
                'executables': list(self.executables), 'launch_files': list(self.launch_files)}


def _real(path: str) -> str:
    return os.path.realpath(path)


def workspace_prefixes(root: str) -> List[str]:
    """Install prefixes of the workspace (merged: ``install``; isolated: ``install/<pkg>``)."""
    install = os.path.join(root, 'install')
    if os.path.isdir(os.path.join(install, INDEX_DIR)):
        return [_real(install)]
    if not os.path.isdir(install):
        return []
    prefixes = []
    for name in sorted(os.listdir(install)):
        candidate = os.path.join(install, name)
        if os.path.isdir(os.path.join(candidate, INDEX_DIR)):
            prefixes.append(_real(candidate))
    return prefixes


def env_prefixes(env: Mapping[str, str]) -> List[str]:
    return [_real(p) for p in env.get('AMENT_PREFIX_PATH', '').split(os.pathsep) if p]


def list_executables(prefix: str, package: str) -> Tuple[str, ...]:
    lib = os.path.join(prefix, 'lib', package)
    if not os.path.isdir(lib):
        return ()
    names = []
    for name in sorted(os.listdir(lib)):
        path = os.path.join(lib, name)
        if (os.path.isfile(path) and os.access(path, os.X_OK)
                and validate.EXECUTABLE_RE.match(name) and not name.endswith('.so')):
            names.append(name)
    return tuple(names)


def list_launch_files(prefix: str, package: str) -> Tuple[str, ...]:
    base = os.path.join(prefix, 'share', package, 'launch')
    if not os.path.isdir(base):
        return ()
    names = set()
    for current, dirs, files in os.walk(base):
        depth = os.path.relpath(current, base).count(os.sep)
        if depth >= MAX_LAUNCH_DEPTH:
            dirs[:] = []
        names.update(f for f in files if f.endswith(validate.LAUNCH_EXTS)
                     and validate.LAUNCH_FILE_RE.match(f))
    return tuple(sorted(names))


def _package_name_from_xml(path: str) -> Optional[str]:
    try:
        root = ElementTree.parse(path).getroot()
    except (ElementTree.ParseError, OSError) as exc:
        LOG.warning('cannot parse %s: %s', path, exc)
        return None
    name = (root.findtext('name') or '').strip()
    return name if validate.PACKAGE_RE.match(name) else None


def scan_sources(src: str) -> Dict[str, str]:
    """``{package name: source dir}`` from package.xml files under ``src``."""
    found: Dict[str, str] = {}
    if not os.path.isdir(src):
        return found
    for current, dirs, files in os.walk(src, followlinks=False):
        if any(marker in files for marker in IGNORE_MARKERS):
            dirs[:] = []
            continue
        if 'package.xml' in files:
            name = _package_name_from_xml(os.path.join(current, 'package.xml'))
            if name and name not in found:
                found[name] = _real(current)
            dirs[:] = []
            continue
        depth = os.path.relpath(current, src).count(os.sep)
        dirs[:] = [] if depth >= MAX_SRC_DEPTH else sorted(d for d in dirs if not d.startswith('.'))
    return found


def scan(root: str, env: Mapping[str, str]) -> Dict[str, PackageInfo]:
    ws_prefixes = workspace_prefixes(root)
    sourced = set(env_prefixes(env))
    install_root = _real(os.path.join(root, 'install'))
    sources = scan_sources(os.path.join(root, 'src'))
    packages: Dict[str, PackageInfo] = {}
    for prefix in ws_prefixes + [p for p in env_prefixes(env) if p not in ws_prefixes]:
        index = os.path.join(prefix, INDEX_DIR)
        if not os.path.isdir(index):
            continue
        in_ws = os.path.commonpath([install_root, prefix]) == install_root
        for name in sorted(os.listdir(index)):
            if name in packages or not validate.PACKAGE_RE.match(name):
                continue
            packages[name] = PackageInfo(
                name=name, origin=ORIGIN_WORKSPACE if in_ws else ORIGIN_SYSTEM, prefix=prefix,
                sourced=prefix in sourced, source_dir=sources.get(name),
                executables=list_executables(prefix, name),
                launch_files=list_launch_files(prefix, name))
    for name, source_dir in sources.items():
        if name not in packages:
            packages[name] = PackageInfo(name=name, origin=ORIGIN_WORKSPACE, prefix=None,
                                         sourced=False, source_dir=source_dir)
    return packages


class Workspace:
    """Cached discovery over one workspace root."""

    def __init__(self, root: str, env: Optional[Mapping[str, str]] = None):
        self.root = _real(root)
        self._env = dict(os.environ if env is None else env)
        self._lock = threading.Lock()
        self._packages: Dict[str, PackageInfo] = {}
        self._scanned_at = 0.0
        self.refresh()

    @property
    def env(self) -> Dict[str, str]:
        return dict(self._env)

    def refresh(self) -> Dict[str, Any]:
        started = time.monotonic()
        packages = scan(self.root, self._env)
        with self._lock:
            self._packages = packages
            self._scanned_at = time.time()
        LOG.info('workspace %s: %d packages (%.0f ms)', self.root, len(packages),
                 (time.monotonic() - started) * 1000)
        return self.to_dict()

    def to_dict(self) -> Dict[str, Any]:
        with self._lock:
            packages = sorted(self._packages.values(),
                              key=lambda p: (p.origin != ORIGIN_WORKSPACE, p.name))
            scanned_at = self._scanned_at
        return {'root': self.root, 'scanned_at': scanned_at,
                'packages': [p.to_dict() for p in packages]}

    def package(self, name: str) -> PackageInfo:
        validate.package_name(name)
        with self._lock:
            info = self._packages.get(name)
        if info is None:
            raise LauncherError('unknown_package', f'package {name!r} not found in the '
                                'workspace or the sourced ROS environment', 404)
        return info

    def require_executable(self, package: str, executable: str) -> PackageInfo:
        validate.executable_name(executable)
        info = self.package(package)
        if executable not in info.executables:
            raise LauncherError('unknown_executable',
                                f'{package} has no executable {executable!r}', 404)
        return info

    def require_launch_file(self, package: str, launch_file: str) -> PackageInfo:
        validate.launch_file_name(launch_file)
        info = self.package(package)
        if launch_file not in info.launch_files:
            raise LauncherError('unknown_launch_file',
                                f'{package} has no launch file {launch_file!r}', 404)
        return info

    def unsourced_prefixes(self) -> List[str]:
        """Workspace prefixes that child processes need overlaid onto their environment."""
        with self._lock:
            return sorted({p.prefix for p in self._packages.values()
                           if p.prefix and p.origin == ORIGIN_WORKSPACE and not p.sourced})
