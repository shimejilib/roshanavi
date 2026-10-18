"""Static signatures of a user module: top-level functions read with :mod:`ast` only (no import).

The server lists what a function / class node can use without ever importing user code
(docs/design/security.md). Parsed trees are cached by (path, mtime, size), so the "コードの場所"
report and the module list can parse every candidate file without re-reading unchanged ones.
"""

import ast
import os
import threading
from typing import Any, Dict, List, Optional, Tuple

from ..launcher.errors import LauncherError

MAX_SOURCE_BYTES = 1024 * 1024
_CACHE_SIZE = 512

_KIND_HINTS = {
    'str': 'string', 'float': 'float', 'int': 'int', 'bool': 'bool', 'bytes': 'bytes',
    'bytearray': 'bytes', 'dict': 'json', 'Dict': 'json', 'Mapping': 'json',
    'list': 'numbers', 'List': 'numbers', 'Sequence': 'numbers', 'tuple': 'numbers',
    'ndarray': 'image', 'np.ndarray': 'image', 'numpy.ndarray': 'image',
    'NDArray': 'image', 'npt.NDArray': 'image',
}

_cache: Dict[str, Tuple[Tuple[int, int], Any]] = {}
_cache_lock = threading.Lock()


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


def _stamp(path: str) -> Tuple[int, int]:
    st = os.stat(path)
    return (st.st_mtime_ns, st.st_size)


class SourceSyntaxError(LauncherError):
    """A syntax error in a user file (``line`` / ``detail`` for the 「見つからない理由」 list)."""

    def __init__(self, path: str, line: Optional[int], detail: str):
        super().__init__('module_syntax_error', f'{os.path.basename(path)}:{line}: {detail}')
        self.line = line
        self.detail = detail


def parse_source(path: str) -> ast.Module:
    """The parsed module (cached while the file is unchanged); LauncherError when it cannot be."""
    try:
        stamp = _stamp(path)
        with _cache_lock:
            hit = _cache.get(path)
        if hit is None or hit[0] != stamp:
            if stamp[1] > MAX_SOURCE_BYTES:
                raise LauncherError('module_too_large', f'{path} is larger than 1 MB')
            with open(path, encoding='utf-8') as fh:
                text = fh.read()
            try:
                parsed: Any = ast.parse(text, filename=path)
            except SyntaxError as exc:
                parsed = (exc.lineno, exc.msg)
            hit = (stamp, parsed)
            with _cache_lock:
                if len(_cache) >= _CACHE_SIZE:
                    _cache.clear()
                _cache[path] = hit
    except (OSError, UnicodeDecodeError, ValueError) as exc:
        raise LauncherError('module_unreadable', f'cannot read {path}: {exc}') from exc
    if isinstance(hit[1], tuple):
        raise SourceSyntaxError(path, *hit[1])
    return hit[1]


def _main_guard(node: ast.stmt) -> bool:
    """``if __name__ == '__main__':``"""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    test = node.test
    names = [test.left, *test.comparators]
    return any(isinstance(n, ast.Name) and n.id == '__name__' for n in names)


def skipped_members(tree: ast.Module) -> List[Dict[str, Any]]:
    """Definitions that are not offered, with the reason (shown as 「候補にならなかったもの」)."""
    skipped: List[Dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) \
                and node.name.startswith('_'):
            skipped.append({'name': node.name, 'line': node.lineno, 'reason': 'private'})
        elif isinstance(node, ast.AsyncFunctionDef):
            skipped.append({'name': node.name, 'line': node.lineno, 'reason': 'async'})
        elif _main_guard(node):
            for inner in ast.walk(node):
                if isinstance(inner, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    skipped.append({'name': inner.name, 'line': inner.lineno,
                                    'reason': 'main_guard'})
    return skipped


def public_members(tree: ast.Module) -> Tuple[int, int]:
    """(public top-level functions, public top-level classes)."""
    functions = sum(1 for n in tree.body if isinstance(n, ast.FunctionDef)
                    and not n.name.startswith('_'))
    classes = sum(1 for n in tree.body if isinstance(n, ast.ClassDef)
                  and not n.name.startswith('_'))
    return functions, classes


def imports_of(tree: ast.Module) -> List[str]:
    """Top-level names of every module the file imports (anywhere in the file)."""
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split('.')[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            names.add(node.module.split('.')[0])
    return sorted(names)


def list_functions(path: str) -> List[Dict[str, Any]]:
    """Top-level public ``def`` functions of a source file, parsed with :mod:`ast` only."""
    tree = parse_source(path)
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
