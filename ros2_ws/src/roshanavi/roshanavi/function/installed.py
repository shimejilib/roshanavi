"""Scope C: modules installed in the node's Python environment, located **without importing**.

``importlib.util.find_spec('a.b')`` would import ``a`` (and run its ``__init__``), so the server
walks the search path itself, the way the default path finder does: in each directory of the
path, a package directory with ``__init__.py`` first, then an extension module (``.so``), then
``<name>.py``; a directory without ``__init__.py`` is a namespace-package portion (PEP 420) used
only when no directory has a regular package or module. Editable installs of setuptools
(``__editable___<dist>_finder.py`` with a literal ``MAPPING``) are read as a last resort, like
their finder (appended to ``sys.meta_path``).

The found file is parsed with :mod:`ast` (static listing). An extension module cannot be parsed:
it is reported as not listable and the function name is typed by hand.
"""

import ast
import importlib.machinery
import os
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Tuple

from .scopes import IDENT_RE

KIND_PACKAGE = 'package'
KIND_SOURCE = 'source'
KIND_EXTENSION = 'extension'
KIND_NAMESPACE = 'namespace'
MAX_LISTED_PER_ENTRY = 200
MAX_LIST_DEPTH = 3
_EDITABLE_PREFIX = '__editable___'


@dataclass(frozen=True)
class Located:
    name: str
    kind: str                      # package | source | extension | namespace
    file: Optional[str]            # __init__.py / <name>.py / <name>.so (None: namespace)
    search_dirs: Tuple[str, ...]   # where its submodules are (package / namespace)
    site: str                      # the search-path entry it was found under

    @property
    def listable(self) -> bool:
        return self.kind in (KIND_PACKAGE, KIND_SOURCE)


def _dirs(search_path: Sequence[str]) -> List[str]:
    return [entry for entry in search_path if entry and os.path.isdir(entry)]


def _module_file(directory: str, part: str) -> Optional[Tuple[str, str]]:
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        path = os.path.join(directory, part + suffix)
        if os.path.isfile(path):
            return KIND_EXTENSION, path
    path = os.path.join(directory, part + '.py')
    return (KIND_SOURCE, path) if os.path.isfile(path) else None


def _find_part(name: str, part: str, dirs: Sequence[str], site: Optional[str]) -> Optional[Located]:
    portions: List[str] = []
    for directory in dirs:
        candidate = os.path.join(directory, part)
        if os.path.isdir(candidate) and os.path.isfile(os.path.join(candidate, '__init__.py')):
            return Located(name, KIND_PACKAGE, os.path.join(candidate, '__init__.py'),
                           (candidate,), site or directory)
        found = _module_file(directory, part)
        if found is not None:
            return Located(name, found[0], found[1], (), site or directory)
        if os.path.isdir(candidate):
            portions.append(candidate)
    if portions:
        return Located(name, KIND_NAMESPACE, None, tuple(portions), site or portions[0])
    return None


def editable_mappings(search_path: Sequence[str]) -> Dict[str, str]:
    """``{top: package dir}`` of setuptools' editable installs (their finder's ``MAPPING``)."""
    mapping: Dict[str, str] = {}
    for directory in _dirs(search_path):
        try:
            names = sorted(os.listdir(directory))
        except OSError:
            continue
        for fname in names:
            if not (fname.startswith(_EDITABLE_PREFIX) and fname.endswith('_finder.py')):
                continue
            path = os.path.join(directory, fname)
            try:
                if os.path.getsize(path) > 256 * 1024:
                    continue
                with open(path, encoding='utf-8') as fh:
                    tree = ast.parse(fh.read())
            except (OSError, SyntaxError, UnicodeDecodeError, ValueError):
                continue
            for node in tree.body:
                if isinstance(node, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == 'MAPPING' for t in node.targets):
                    try:
                        value = ast.literal_eval(node.value)
                    except (ValueError, SyntaxError, TypeError):
                        continue
                    if isinstance(value, dict):
                        for top, target in value.items():
                            if isinstance(top, str) and isinstance(target, str):
                                mapping.setdefault(top, target)
    return mapping


def locate(name: str, search_path: Sequence[str]) -> Optional[Located]:
    """Where ``name`` (``a.b.c``) would be imported from, or None. Never imports anything."""
    parts = name.split('.')
    if not all(IDENT_RE.match(p) for p in parts):
        return None
    dirs = _dirs(search_path)
    found = _find_part(parts[0], parts[0], dirs, None)
    if found is None:
        target = editable_mappings(search_path).get(parts[0])
        if target and os.path.isfile(os.path.join(target, '__init__.py')):
            found = Located(parts[0], KIND_PACKAGE, os.path.join(target, '__init__.py'),
                            (target,), os.path.dirname(target))
    for index, part in enumerate(parts[1:], start=1):
        if found is None or not found.search_dirs:
            return None
        found = _find_part('.'.join(parts[:index + 1]), part, found.search_dirs, found.site)
    return found


def submodules(located: Located, limit: int = MAX_LISTED_PER_ENTRY) -> List[Located]:
    """The module itself and, for a package or namespace, its submodules (bounded walk)."""
    out = [located]
    if not located.search_dirs:
        return out
    stack = [(located.name, d, 0) for d in located.search_dirs]
    seen = set()
    while stack and len(out) < limit:
        prefix, directory, depth = stack.pop(0)
        try:
            entries = sorted(os.listdir(directory))
        except OSError:
            continue
        for entry in entries:
            if len(out) >= limit:
                break
            path = os.path.join(directory, entry)
            if entry.startswith('.') or entry == '__pycache__':
                continue
            if os.path.isdir(path):
                if IDENT_RE.match(entry) and os.path.isfile(os.path.join(path, '__init__.py')) \
                        and f'{prefix}.{entry}' not in seen:
                    seen.add(f'{prefix}.{entry}')
                    out.append(Located(f'{prefix}.{entry}', KIND_PACKAGE,
                                       os.path.join(path, '__init__.py'), (path,), located.site))
                    if depth + 1 < MAX_LIST_DEPTH:
                        stack.append((f'{prefix}.{entry}', path, depth + 1))
                continue
            stem, kind = _stem(entry)
            if stem and stem != '__init__' and IDENT_RE.match(stem) \
                    and f'{prefix}.{stem}' not in seen:
                seen.add(f'{prefix}.{stem}')
                out.append(Located(f'{prefix}.{stem}', kind, path, (), located.site))
    return out


def _stem(fname: str) -> Tuple[Optional[str], str]:
    for suffix in importlib.machinery.EXTENSION_SUFFIXES:
        if fname.endswith(suffix):
            return fname[:-len(suffix)], KIND_EXTENSION
    if fname.endswith('.py'):
        return fname[:-3], KIND_SOURCE
    return None, ''
