"""Workspace Python modules for function nodes: listing, resolution and static signatures.

Nothing here imports user code. The server lists modules and their top-level
functions with :mod:`ast` only (docs/design/nodes.md); the function node process
resolves a module name to a file with the same rules before importing it.

Rules (the import containment):

- Only Python packages inside ROS packages of ``<workspace>/src`` (a directory
  with ``__init__.py`` directly in a package's source directory) are offered.
- A module name resolves to ``<source_dir>/<top>/<rest>.py`` (or a package's
  ``__init__.py``); its real path must stay inside ``<workspace>/src`` and
  inside that Python package (no symlink escapes) and be a regular file.
- ``roshanavi`` itself is never offered or resolved.
"""

import ast
import os
import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from ..launcher.discovery import scan_sources
from ..launcher.errors import LauncherError
from ..launcher.schema import MODULE_PATTERN, RESERVED_MODULE_TOPS

IDENT_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
MODULE_RE = re.compile(MODULE_PATTERN)
SKIP_DIRS = {'test', 'tests', '__pycache__', 'build', 'install', 'log', 'launch', 'resource'}
MAX_DEPTH = 3
MAX_MODULES = 500
MAX_SOURCE_BYTES = 1024 * 1024


@dataclass(frozen=True)
class PythonPackage:
    ros_package: str
    base_dir: str   # the ROS package's source directory (parent of ``top``)
    top: str        # the Python package name

    @property
    def path(self) -> str:
        return os.path.join(self.base_dir, self.top)


@dataclass(frozen=True)
class ResolvedModule:
    module: str
    package: PythonPackage
    file: str       # real path of the module's source file


def _src_root(workspace: str) -> str:
    return os.path.realpath(os.path.join(workspace, 'src'))


def _inside(path: str, root: str) -> bool:
    return path == root or path.startswith(os.path.join(root, ''))


def python_packages(workspace: str) -> List[PythonPackage]:
    """Python packages directly inside each ROS package of ``<workspace>/src``."""
    found: Dict[str, PythonPackage] = {}
    src = _src_root(workspace)
    for ros_name, source_dir in sorted(scan_sources(src).items()):
        try:
            entries = sorted(os.listdir(source_dir))
        except OSError:
            continue
        for entry in entries:
            path = os.path.join(source_dir, entry)
            if (entry in SKIP_DIRS or entry.startswith('.') or not IDENT_RE.match(entry)
                    or entry in RESERVED_MODULE_TOPS
                    or not os.path.isfile(os.path.join(path, '__init__.py'))):
                continue
            if not _inside(os.path.realpath(path), src):
                continue
            found.setdefault(entry, PythonPackage(ros_name, source_dir, entry))
    return list(found.values())


def _module_name(package: PythonPackage, rel: str) -> Optional[str]:
    parts = rel[:-3].split(os.sep)
    if parts[-1] == '__init__':
        parts = parts[:-1]
    name = '.'.join([package.top, *parts])
    return name if MODULE_RE.match(name) else None


def list_modules(workspace: str) -> List[Dict[str, Any]]:
    """``[{module, ros_package, file}]`` for every ``.py`` file of the workspace packages."""
    modules: List[Dict[str, Any]] = []
    root = os.path.realpath(workspace)
    for package in python_packages(workspace):
        for current, dirs, files in os.walk(package.path):
            depth = os.path.relpath(current, package.path).count(os.sep)
            dirs[:] = [] if depth >= MAX_DEPTH else sorted(
                d for d in dirs if d not in SKIP_DIRS and not d.startswith('.')
                and os.path.isfile(os.path.join(current, d, '__init__.py')))
            for name in sorted(files):
                if not name.endswith('.py') or name.startswith('.'):
                    continue
                path = os.path.join(current, name)
                module = _module_name(package, os.path.relpath(path, package.path))
                if module is None or not _inside(os.path.realpath(path), package.path):
                    continue
                modules.append({'module': module, 'ros_package': package.ros_package,
                                'file': os.path.relpath(path, root)})
                if len(modules) >= MAX_MODULES:
                    return modules
    return modules


def resolve_module(workspace: str, module: str) -> ResolvedModule:
    """The source file of ``module`` inside the workspace, or LauncherError (never imports)."""
    if not isinstance(module, str) or not MODULE_RE.match(module):
        raise LauncherError('invalid_module', f'invalid module name: {module!r}')
    top, *rest = module.split('.')
    if top in RESERVED_MODULE_TOPS:
        raise LauncherError('invalid_module', 'roshanavi itself cannot be a function module')
    package = next((p for p in python_packages(workspace) if p.top == top), None)
    if package is None:
        raise LauncherError('unknown_module', f'no Python package {top!r} in the workspace '
                            f'({os.path.join(workspace, "src")})', 404)
    base = os.path.join(package.path, *rest)
    candidates = [base + '.py', os.path.join(base, '__init__.py')] if rest else \
        [os.path.join(package.path, '__init__.py')]
    for candidate in candidates:
        real = os.path.realpath(candidate)
        if os.path.isfile(candidate) and _inside(real, os.path.realpath(package.path)) \
                and _inside(real, _src_root(workspace)):
            return ResolvedModule(module, package, real)
    raise LauncherError('unknown_module', f'module {module!r} not found in the workspace', 404)


# ---- static signatures (no import) -------------------------------------------------------
_KIND_HINTS = {
    'str': 'string', 'float': 'float', 'int': 'int', 'bool': 'bool', 'bytes': 'bytes',
    'bytearray': 'bytes', 'dict': 'json', 'Dict': 'json', 'Mapping': 'json',
    'list': 'numbers', 'List': 'numbers', 'Sequence': 'numbers', 'tuple': 'numbers',
    'ndarray': 'image', 'np.ndarray': 'image', 'numpy.ndarray': 'image',
    'NDArray': 'image', 'npt.NDArray': 'image',
}


def suggest_kind(annotation: Optional[str]) -> Optional[str]:
    """A data kind for a type annotation (``str`` -> string, ``np.ndarray`` -> image ...)."""
    if not annotation:
        return None
    text = annotation.strip().strip('\'"')
    if text.startswith('Optional[') and text.endswith(']'):
        text = text[len('Optional['):-1]
    head = text.split('[', 1)[0].strip()
    return _KIND_HINTS.get(head) or _KIND_HINTS.get(head.rsplit('.', 1)[-1])


def _annotation(node: Optional[ast.AST]) -> Optional[str]:
    return ast.unparse(node) if node is not None else None


def _params(fn: ast.FunctionDef) -> List[Dict[str, Any]]:
    args = fn.args
    positional = [*args.posonlyargs, *args.args]
    defaults = [None] * (len(positional) - len(args.defaults)) + list(args.defaults)
    params = []
    for arg, default in zip(positional, defaults):
        annotation = _annotation(arg.annotation)
        params.append({'name': arg.arg, 'annotation': annotation,
                       'kind': suggest_kind(annotation), 'optional': default is not None})
    return params


def _signature_text(fn: ast.FunctionDef) -> str:
    returns = f' -> {_annotation(fn.returns)}' if fn.returns is not None else ''
    return f'{fn.name}({ast.unparse(fn.args)}){returns}'


def list_functions(path: str) -> List[Dict[str, Any]]:
    """Top-level public ``def`` functions of a source file, parsed with :mod:`ast` only."""
    try:
        if os.path.getsize(path) > MAX_SOURCE_BYTES:
            raise LauncherError('module_too_large', f'{path} is larger than 1 MB')
        with open(path, encoding='utf-8') as fh:
            tree = ast.parse(fh.read(), filename=path)
    except SyntaxError as exc:
        raise LauncherError('module_syntax_error', f'{os.path.basename(path)}:{exc.lineno}: '
                            f'{exc.msg}') from exc
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LauncherError('module_unreadable', f'cannot read {path}: {exc}') from exc
    functions = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef) or node.name.startswith('_'):
            continue
        params = _params(node)
        returns = _annotation(node.returns)
        functions.append({
            'name': node.name, 'line': node.lineno, 'signature': _signature_text(node),
            'params': params, 'required': sum(1 for p in params if not p['optional']),
            'returns': returns, 'returns_kind': suggest_kind(returns),
            'doc': (ast.get_docstring(node) or '').strip().split('\n\n')[0][:500],
            'varargs': node.args.vararg is not None})
    return functions


def describe_module(workspace: str, module: str) -> Dict[str, Any]:
    resolved = resolve_module(workspace, module)
    return {'module': module, 'ros_package': resolved.package.ros_package,
            'file': os.path.relpath(resolved.file, os.path.realpath(workspace)),
            'functions': list_functions(resolved.file)}
