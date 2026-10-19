"""Project files the settings menu can switch between (P5).

Two sources:

- **examples** (read-only templates): ``<examples_dir>/<name>/roshanavi.yaml``,
  e.g. ``demo_project`` and ``perception_demo``. Opening one copies it to
  ``<data_dir>/projects/<name>.yaml`` the first time (never overwrites), and
  the server then works on that copy, so autosave never writes into examples.
- **data**: ``<data_dir>/roshanavi.yaml`` and ``<data_dir>/projects/*.yaml``.

Clients pick an entry by its ``id`` from the listing (never by a free path),
so only these files can ever be opened.

The id of the last opened entry is remembered in ``<data_dir>/last_project.json`` and,
after validation against the listing, used as the project at the next start.
"""

import glob
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from .dummy_config import write_atomic
from .errors import LauncherError
from .project import DEFAULT_FILE_NAME, bootstrap_project

LOG = logging.getLogger(__name__)

PROJECTS_SUBDIR = 'projects'
LAST_PROJECT_FILE = 'last_project.json'
MAX_ENTRIES = 100
_NAME_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$')


def _title(path: str) -> str:
    """First comment line of the file (``# roshanavi demo project: ...``) as a hint."""
    try:
        with open(path, encoding='utf-8') as fh:
            for _ in range(5):
                line = fh.readline()
                if line.startswith('#'):
                    return line.lstrip('# ').strip()[:200]
    except OSError:
        return ''
    return ''


class ProjectCatalog:
    def __init__(self, data_dir: str, examples_dir: Optional[str] = None):
        self.data_dir = os.path.realpath(data_dir)
        self.examples_dir = os.path.realpath(examples_dir) if examples_dir else None

    def _examples(self) -> List[Dict[str, Any]]:
        if not self.examples_dir or not os.path.isdir(self.examples_dir):
            return []
        entries = []
        pattern = os.path.join(self.examples_dir, '*', DEFAULT_FILE_NAME)
        for path in sorted(glob.glob(pattern))[:MAX_ENTRIES]:
            name = os.path.basename(os.path.dirname(path))
            if _NAME_RE.match(name):
                entries.append({'id': f'example:{name}', 'kind': 'example', 'name': name,
                                'path': path, 'title': _title(path),
                                'copy_path': self._copy_path(name)})
        return entries

    def _copy_path(self, name: str) -> str:
        return os.path.join(self.data_dir, PROJECTS_SUBDIR, f'{name}.yaml')

    def _data(self) -> List[Dict[str, Any]]:
        paths = [os.path.join(self.data_dir, DEFAULT_FILE_NAME)]
        paths += sorted(glob.glob(os.path.join(self.data_dir, PROJECTS_SUBDIR, '*.yaml')))
        entries = []
        for path in paths[:MAX_ENTRIES]:
            if not os.path.isfile(path):
                continue
            rel = os.path.relpath(path, self.data_dir)
            entries.append({'id': f'data:{rel}', 'kind': 'data', 'name': rel, 'path': path,
                            'title': _title(path)})
        return entries

    def list(self, current: str) -> Dict[str, Any]:
        current = os.path.realpath(current)
        entries = [*self._examples(), *self._data()]
        for entry in entries:
            entry['current'] = os.path.realpath(entry.get('copy_path') or entry['path']) == current \
                if entry['kind'] == 'example' else os.path.realpath(entry['path']) == current
        return {'current': current, 'projects': entries}

    def resolve(self, entry_id: str) -> str:
        """The file to open for ``entry_id`` (an example is copied to data first)."""
        for entry in [*self._examples(), *self._data()]:
            if entry['id'] != entry_id:
                continue
            if entry['kind'] == 'data':
                return entry['path']
            target = entry['copy_path']
            if bootstrap_project(target, entry['path']):
                LOG.info('example %s copied to %s', entry['name'], target)
            return target
        raise LauncherError('not_found', f'no such project: {entry_id}', 404)

    # ---- the project to start with ------------------------------------------
    def _last_path(self) -> str:
        return os.path.join(self.data_dir, LAST_PROJECT_FILE)

    def remember(self, entry_id: str) -> None:
        """Remember the entry that was opened (a failure is logged, never raised)."""
        try:
            write_atomic(self._last_path(), json.dumps({'id': entry_id}) + '\n')
        except OSError as exc:
            LOG.warning('cannot remember the opened project: %s', exc)

    def remembered_path(self) -> Optional[str]:
        """The file of the remembered entry, or None when nothing valid is remembered.

        The stored id is only trusted if it is still in the listing, so a deleted project or a
        hand-edited file falls back to the ``--project`` option.
        """
        try:
            with open(self._last_path(), encoding='utf-8') as fh:
                entry_id = json.load(fh).get('id')
        except FileNotFoundError:
            return None
        except (OSError, ValueError, AttributeError) as exc:
            LOG.warning('ignoring %s: %s', self._last_path(), exc)
            return None
        if not isinstance(entry_id, str):
            return None
        try:
            return self.resolve(entry_id)
        except LauncherError:
            LOG.warning('the remembered project %r is not available any more', entry_id)
            return None
