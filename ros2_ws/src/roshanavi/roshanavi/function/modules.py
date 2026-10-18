"""User modules for function / class nodes: listing, resolution and static signatures.

Nothing here imports user code. The server lists modules and their top-level functions with
:mod:`ast` only (docs/design/user-code.md); the node process resolves a module name to a file
with the same rules before importing it.

Scopes (:mod:`.scopes`): A = the ROS packages of ``<workspace>/src`` (always), B = the project's
``code_paths`` and C = its ``installed_modules`` (both opt-in). A top-level name is taken by the
first scope that has it (A, then B, then C).

Containment (A / B): a module name resolves to ``<package dir>/<rest>.py`` (or a package's
``__init__.py``); its real path must stay inside the scope's root (``<workspace>/src`` or the
registered directory: inward symlinks work, outward ones are refused) and be a regular file.
``roshanavi`` itself and names of the standard library / the node's runtime are never offered.
C: only the registered module names (and their submodules), found on the node interpreter's
search path (:mod:`.installed`).
"""

import os
import re
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union

from ..launcher.errors import LauncherError
from ..launcher.schema import MODULE_PATTERN, RESERVED_MODULE_TOPS
from . import installed
from .scopes import (SCOPE_CODE_PATH, SCOPE_INSTALLED, SCOPE_WORKSPACE, SKIP_DIRS,  # noqa: F401
                     CodeLocations, IDENT_RE, PythonPackage, inside, source_packages)
from .signatures import (MAX_SOURCE_BYTES, _annotation, imports_of, list_functions,  # noqa: F401
                         parse_source, skipped_members, suggest_kind)

MODULE_RE = re.compile(MODULE_PATTERN)
MAX_DEPTH = 3
MAX_MODULES = 500
Locations = Union[CodeLocations, str]


@dataclass(frozen=True)
class ResolvedModule:
    module: str
    package: PythonPackage
    file: Optional[str]     # real path of the module's file (None: namespace package)
    kind: str = installed.KIND_SOURCE   # source | extension (scope C only)

    @property
    def scope(self) -> str:
        return self.package.scope

    @property
    def listable(self) -> bool:
        return self.file is not None and self.kind != installed.KIND_EXTENSION


def python_packages(workspace: Locations) -> List[PythonPackage]:
    """Scope A and B packages (kept for callers that only need the source packages)."""
    return source_packages(CodeLocations.of(workspace))


def _module_name(top: str, rel: str) -> Optional[str]:
    parts = rel[:-3].split(os.sep)
    if parts[-1] == '__init__':
        parts = parts[:-1]
    name = '.'.join([top, *parts])
    return name if MODULE_RE.match(name) else None


def display_path(path: str, locations: CodeLocations) -> str:
    """Workspace-relative inside the workspace, else the absolute path (the user's real path)."""
    real_ws = os.path.realpath(locations.workspace)
    return os.path.relpath(path, real_ws) if inside(path, real_ws) else path


def _walk_package(package: PythonPackage):
    """``(path, rel)`` of every ``.py`` file of a source package (bounded, never into .git)."""
    for current, dirs, files in os.walk(package.path):
        depth = os.path.relpath(current, package.path).count(os.sep)
        dirs[:] = [] if depth >= MAX_DEPTH else sorted(
            d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')
            and os.path.isfile(os.path.join(current, d, '__init__.py')))
        for name in sorted(files):
            if name.endswith('.py') and not name.startswith('.'):
                path = os.path.join(current, name)
                yield path, os.path.relpath(path, package.path)


def _source_entries(locations: CodeLocations) -> List[Dict[str, Any]]:
    modules: List[Dict[str, Any]] = []
    for package in source_packages(locations):
        for path, rel in _walk_package(package):
            module = _module_name(package.top, rel)
            real = os.path.realpath(path)
            if module is None or not inside(real, package.root) or not os.path.isfile(real):
                continue
            modules.append({'module': module, 'ros_package': package.ros_package,
                            'file': display_path(path, locations), 'scope': package.scope,
                            'source': package.source, 'listable': True})
            if len(modules) >= MAX_MODULES:
                return modules
    return modules


def installed_entries(locations: CodeLocations, taken: List[str]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    search = search_path_of(locations)
    for entry in locations.installed_modules:
        top = entry.split('.')[0]
        if top in taken or top in RESERVED_MODULE_TOPS:
            continue
        located = installed.locate(entry, search)
        if located is None:
            continue
        for item in installed.submodules(located):
            if item.kind == installed.KIND_NAMESPACE:
                continue
            out.append({'module': item.name, 'ros_package': None,
                        'file': item.file, 'scope': SCOPE_INSTALLED, 'source': entry,
                        'listable': item.listable})
    return out


def search_path_of(locations: CodeLocations) -> List[str]:
    return list(locations.search_path) if locations.search_path is not None else list(sys.path)


def list_modules(workspace: Locations) -> List[Dict[str, Any]]:
    """``[{module, ros_package, file, scope, source, listable}]`` of every scope."""
    locations = CodeLocations.of(workspace)
    modules = _source_entries(locations)
    taken = sorted({m['module'].split('.')[0] for m in modules}
                   | {p.top for p in source_packages(locations)})
    seen = {m['module'] for m in modules}
    for item in installed_entries(locations, taken):
        if item['module'] not in seen and len(modules) < MAX_MODULES * 2:
            seen.add(item['module'])
            modules.append(item)
    return modules


def _resolve_source(package: PythonPackage, module: str, rest: List[str]) -> ResolvedModule:
    base = os.path.join(package.path, *rest)
    candidates = [base + '.py', os.path.join(base, '__init__.py')] if rest else \
        [os.path.join(package.path, '__init__.py')]
    for candidate in candidates:
        real = os.path.realpath(candidate)
        if os.path.isfile(candidate) and os.path.isfile(real) and inside(real, package.root):
            return ResolvedModule(module, package, real)
    raise LauncherError('unknown_module', f'module {module!r} not found in '
                        f'{package.path}', 404)


def _resolve_installed(locations: CodeLocations, module: str) -> ResolvedModule:
    entry = next((e for e in locations.installed_modules
                  if module == e or module.startswith(e + '.')), None)
    if module.split('.')[0] in getattr(sys, 'stdlib_module_names', ()):
        entry = None   # never the standard library (the schema refuses it too)
    if entry is None:
        raise LauncherError('unknown_module', f'no module {module!r} in the workspace '
                            f'({locations.src}), the code paths or the installed modules', 404)
    located = installed.locate(module, search_path_of(locations))
    if located is None:
        raise LauncherError('unknown_module', f'installed module {module!r} is not found in the '
                            "node's Python environment", 404)
    if located.kind == installed.KIND_NAMESPACE:
        raise LauncherError('unknown_module', f'{module!r} is a namespace package (it has no '
                            'file of its own); choose one of its modules', 404)
    top = module.split('.')[0]
    top_dir = os.path.join(located.site, top)
    package = PythonPackage(None, located.site, top, SCOPE_INSTALLED, '', entry,
                            top_dir if os.path.isdir(top_dir) else (located.file or top_dir))
    return ResolvedModule(module, package, os.path.realpath(located.file or ''), located.kind)


def resolve_module(workspace: Locations, module: str) -> ResolvedModule:
    """The file of ``module`` in scope A, B or C, or LauncherError (never imports)."""
    locations = CodeLocations.of(workspace)
    if not isinstance(module, str) or not MODULE_RE.match(module):
        raise LauncherError('invalid_module', f'invalid module name: {module!r}')
    top, *rest = module.split('.')
    if top in RESERVED_MODULE_TOPS:
        raise LauncherError('invalid_module', 'roshanavi itself cannot be a function module')
    package = next((p for p in source_packages(locations) if p.top == top), None)
    if package is not None:
        return _resolve_source(package, module, rest)
    if locations.installed_modules:
        return _resolve_installed(locations, module)
    raise LauncherError('unknown_module', f'no Python package {top!r} in the workspace '
                        f'({locations.src})', 404)


def static_notices(resolved: ResolvedModule, tree: Any = None) -> List[Dict[str, Any]]:
    """What to tell before running it: rclpy used inside, extension module, no hot reload."""
    notices: List[Dict[str, Any]] = []
    if resolved.kind == installed.KIND_EXTENSION:
        notices.append({'code': 'extension_module'})
    if resolved.scope == SCOPE_INSTALLED:
        notices.append({'code': 'no_hot_reload_installed'})
    if tree is not None and 'rclpy' in imports_of(tree):
        notices.append({'code': 'imports_rclpy'})
    return notices


def describe_module(workspace: Locations, module: str) -> Dict[str, Any]:
    locations = CodeLocations.of(workspace)
    resolved = resolve_module(locations, module)
    info: Dict[str, Any] = {
        'module': module, 'ros_package': resolved.package.ros_package,
        'file': display_path(resolved.file, locations) if resolved.file else None,
        'scope': resolved.scope, 'source': resolved.package.source,
        'listable': resolved.listable, 'functions': [], 'skipped': []}
    tree = None
    if resolved.listable:
        tree = parse_source(resolved.file)
        info['functions'] = list_functions(resolved.file)
        info['skipped'] = skipped_members(tree)
    info['notices'] = static_notices(resolved, tree)
    return info
