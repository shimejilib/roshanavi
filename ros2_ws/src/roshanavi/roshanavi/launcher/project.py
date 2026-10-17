"""``roshanavi.yaml`` project file: schema-validated load, atomic save.

Keys are written in schema order with empty values omitted, so the file stays
short, stable across saves and pleasant to review in git.
"""

import logging
import os
import threading
from typing import Any, Dict, Optional

import yaml
from pydantic import ValidationError

from .dummy_config import format_errors, write_atomic
from .errors import LauncherError
from .schema import ProjectSpec, clean_dict

LOG = logging.getLogger(__name__)

DEFAULT_FILE_NAME = 'roshanavi.yaml'
MAX_PROJECT_BYTES = 1024 * 1024
HEADER = ('# roshanavi project: launch targets, persistent dummy nodes and watched topics.\n'
          '# Edited from the roshanavi web UI (Launcher tab); safe to keep in git.\n')


def bootstrap_project(path: str, template: Optional[str]) -> bool:
    """Copy ``template`` to ``path`` if no project exists there yet (never overwrites).

    The template must be a valid project. Returns True when it was copied.
    """
    if not template or os.path.lexists(path):
        return False
    try:
        with open(template, encoding='utf-8') as fh:
            text = fh.read(MAX_PROJECT_BYTES + 1)
    except OSError as exc:
        raise LauncherError('invalid_project', f'cannot read template {template}: {exc}') from exc
    if len(text) > MAX_PROJECT_BYTES:
        raise LauncherError('invalid_project', f'template {template} is larger than 1 MB')
    parse_project(text, os.path.basename(template))  # refuse to install a broken template
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)  # no overwrite race
    except FileExistsError:
        return False
    except OSError as exc:
        raise LauncherError('save_failed', f'cannot create {path}: {exc}', 500) from exc
    with os.fdopen(fd, 'w', encoding='utf-8') as fh:
        fh.write(text)
    LOG.info('project %s created from template %s', path, template)
    return True


def parse_project(text: str, source: str = 'project') -> ProjectSpec:
    try:
        raw = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        mark = getattr(exc, 'problem_mark', None)
        where = f' (line {mark.line + 1}, column {mark.column + 1})' if mark else ''
        raise LauncherError('invalid_project', f'{source}: invalid YAML{where}: '
                            f'{getattr(exc, "problem", exc)}') from exc
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise LauncherError('invalid_project', f'{source}: the top level must be a mapping')
    try:
        return ProjectSpec.parse_obj(raw)
    except ValidationError as exc:
        raise LauncherError('invalid_project', f'{source}: {format_errors(exc)}') from exc


def dump_project(spec: ProjectSpec) -> str:
    return HEADER + yaml.safe_dump(clean_dict(spec), sort_keys=False, allow_unicode=True,
                                   default_flow_style=False)


class ProjectStore:
    def __init__(self, path: str):
        self.path = os.path.realpath(path)
        self._lock = threading.Lock()
        self._saved: Dict[str, Any] = clean_dict(ProjectSpec())

    def exists(self) -> bool:
        return os.path.isfile(self.path)

    def load(self) -> ProjectSpec:
        """The project on disk (an empty project if the file does not exist yet)."""
        if not self.exists():
            spec = ProjectSpec()
        else:
            if os.path.getsize(self.path) > MAX_PROJECT_BYTES:
                raise LauncherError('invalid_project', f'{self.path} is larger than 1 MB')
            try:
                with open(self.path, encoding='utf-8') as fh:
                    text = fh.read()
            except OSError as exc:
                raise LauncherError('invalid_project', f'cannot read {self.path}: {exc}') from exc
            spec = parse_project(text, os.path.basename(self.path))
        with self._lock:
            self._saved = clean_dict(spec)
        return spec

    def save(self, spec: ProjectSpec) -> None:
        directory = os.path.dirname(self.path)
        try:
            os.makedirs(directory, exist_ok=True)
            write_atomic(self.path, dump_project(spec))
        except OSError as exc:
            raise LauncherError('save_failed', f'cannot write {self.path}: {exc}', 500) from exc
        with self._lock:
            self._saved = clean_dict(spec)
        LOG.info('project saved to %s', self.path)

    def is_dirty(self, spec: ProjectSpec) -> bool:
        with self._lock:
            return clean_dict(spec) != self._saved

    def saved(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            return dict(self._saved)
