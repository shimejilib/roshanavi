"""Registered code paths (scope B) as *libraries* the user's code can import (docs/design/user-code.md).

A registered folder is not only a place to take a function / class from: a package of the
workspace (scope A) or of another code path may ``import simple_pid`` from it. Inside the **node
process** (never the server) a finder is appended to the **end** of ``sys.meta_path``, i.e. it is
asked only after the standard library and every ``sys.path`` entry (site-packages, the ROS
install) failed to provide the name — the same order as appending the folders to ``sys.path``,
but with the safety rules of scope B applied to every dependency:

- only the realpath-checked, user-registered folders (``scopes.check_code_path``) and, for each,
  the import root of its layout: the folder itself (flat), its ``src/`` (src layout), or — when the
  folder is a package itself — just that package under its own name;
- a name the user's code must not take (standard library, ``rclpy``, ``numpy`` ... :
  ``scopes.is_reserved_top``) is never served, so a folder containing ``json/`` cannot shadow
  anything; hidden / ``tests`` / ``docs`` style folders are not served either;
- the file that is found must stay inside the registered folder (``realpath``: an outward symlink is
  refused); namespace packages (no ``__init__.py``) are not served;
- the finder records which top-level names it served, so hot reload drops and re-imports exactly
  those modules (never something that merely lives in a folder, e.g. a venv inside the project).

The server only *looks* (``locate``: ``PathFinder.find_spec`` does not execute code) to give the
right advice when an import fails.
"""

import importlib.abc
import importlib.machinery
import importlib.util
import os
import sys
from dataclasses import dataclass
from importlib.machinery import ModuleSpec
from typing import Dict, List, Optional, Sequence, Set, Tuple

from ..launcher.errors import LauncherError
from .scopes import (CODE_PATH_SKIP_DIRS, CodeLocations, _candidate_dir, _has_init, check_code_path,
                     inside, is_reserved_top)


@dataclass(frozen=True)
class ImportRoot:
    """One registered code path as a source of libraries."""

    path: str                          # as registered
    real: str                          # realpath: the containment root
    dirs: Tuple[str, ...]              # searched for top-level modules (flat dir, then ``src``)
    package: Optional[Tuple[str, str]] = None   # (top, dir): the folder is a package itself


def import_roots(locations: CodeLocations) -> List[ImportRoot]:
    """The registered code paths that still check out, with their import roots."""
    roots: List[ImportRoot] = []
    for path in locations.code_paths:
        try:
            real = check_code_path(path, locations)
        except LauncherError:
            continue
        if _has_init(real):
            top = os.path.basename(real)
            if _candidate_dir(top, CODE_PATH_SKIP_DIRS):
                roots.append(ImportRoot(path, real, (), (top, real)))
            continue
        src = os.path.join(real, 'src')
        roots.append(ImportRoot(path, real, (real, src) if os.path.isdir(src) else (real,)))
    return roots


def _spec_in(top: str, root: ImportRoot) -> Optional[ModuleSpec]:
    if root.package is not None:
        if root.package[0] != top:
            return None
        directory = root.package[1]
        return importlib.util.spec_from_file_location(
            top, os.path.join(directory, '__init__.py'), submodule_search_locations=[directory])
    return importlib.machinery.PathFinder.find_spec(top, list(root.dirs))


def locate_spec(top: str, roots: Sequence[ImportRoot]) -> Optional[Tuple[ImportRoot, ModuleSpec]]:
    """The first registered root that provides the top-level name ``top`` (nothing is imported)."""
    if not _candidate_dir(top, CODE_PATH_SKIP_DIRS) or is_reserved_top(top):
        return None
    for root in roots:
        spec = _spec_in(top, root)
        if spec is None or not spec.origin or not os.path.isfile(spec.origin):
            continue   # not found, or a namespace package (no file of its own)
        if inside(os.path.realpath(spec.origin), root.real):
            return root, spec
    return None


def locate(top: str, locations: CodeLocations) -> Optional[Tuple[ImportRoot, str]]:
    """``(root, file)`` of ``top`` in the registered code paths, for the server's advice."""
    found = locate_spec(top, import_roots(locations))
    return (found[0], os.path.realpath(found[1].origin or '')) if found else None


class CodeImportFinder(importlib.abc.MetaPathFinder):
    """Serves top-level names from the registered code paths, after everything else."""

    def __init__(self, roots: Sequence[ImportRoot]):
        self.roots = tuple(roots)
        self.served: Set[str] = set()

    def find_spec(self, fullname, path=None, target=None):  # type: ignore[no-untyped-def]
        if path is not None or '.' in fullname:
            return None   # a submodule: the parent package's own ``__path__`` handles it
        found = locate_spec(fullname, self.roots)
        if found is None:
            return None
        self.served.add(fullname)
        return found[1]

    def served_modules(self) -> Dict[str, object]:
        """The modules of ``sys.modules`` that came through this finder (and their submodules)."""
        return {name: mod for name, mod in list(sys.modules.items())
                if name.split('.')[0] in self.served}


def install(locations: CodeLocations) -> Optional[CodeImportFinder]:
    """Make the registered code paths importable in **this** (node) process. Replaces the finder
    of an earlier call; None when no code path is usable."""
    uninstall()
    roots = import_roots(locations)
    if not roots:
        return None
    finder = CodeImportFinder(roots)
    sys.meta_path.append(finder)
    return finder


def uninstall() -> None:
    sys.meta_path[:] = [f for f in sys.meta_path if not isinstance(f, CodeImportFinder)]
