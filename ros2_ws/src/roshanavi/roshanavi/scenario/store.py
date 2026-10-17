"""Scenario files of the project / examples, and the bounded results history (server side).

* Project scenarios live next to the project file: ``<dir>/scenarios/`` for
  ``roshanavi.yaml``, ``<dir>/<stem>_scenarios/`` for other project files.
  Examples (``<examples_dir>/scenarios``) are read-only.
* Clients address a file only by its listed id (``project:<file>`` /
  ``example:<file>``); the file name is checked against a strict pattern and the
  realpath must stay inside that directory (no ``..``, no symlink out).
* Results: ``<data_dir>/scenario_results/<run_id>.json``, newest ``MAX_RESULTS`` kept.
"""

import json
import logging
import os
import re
import threading
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..launcher.dummy_config import write_atomic
from .result import Result
from .schema import MAX_SCENARIO_BYTES, Scenario, ScenarioSchemaError, dump, parse_data, parse_text

LOG = logging.getLogger(__name__)

FILE_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.-]{0,100}\.ya?ml\Z')
RUN_ID_RE = re.compile(r'^[0-9a-f]{12}\Z')
SOURCES = ('project', 'example')
MAX_RESULTS = 50
MAX_FILES = 500


class StoreError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def scenarios_dir_for(project_path: str) -> str:
    directory, base = os.path.split(os.path.realpath(project_path))
    stem = os.path.splitext(base)[0]
    return os.path.join(directory, 'scenarios' if stem == 'roshanavi' else f'{stem}_scenarios')


def file_name_for(name: str) -> str:
    slug = re.sub(r'[^A-Za-z0-9_-]+', '_', name).strip('_-')[:80] or 'scenario'
    return f'{slug}.yaml'


class ScenarioStore:
    def __init__(self, project_path: Callable[[], str], examples_dir: Optional[str]):
        self._project_path = project_path
        self._examples = os.path.join(examples_dir, 'scenarios') if examples_dir else None
        self._lock = threading.Lock()

    # ---- locations -------------------------------------------------------------------------
    def project_dir(self) -> str:
        return scenarios_dir_for(self._project_path())

    def _dir(self, source: str) -> Optional[str]:
        return self.project_dir() if source == 'project' else self._examples

    def resolve(self, scenario_id: str) -> Tuple[str, str, str]:
        """``(source, file, realpath)`` of a listed id (raises 404 / 400)."""
        source, sep, name = str(scenario_id).partition(':')
        if not sep or source not in SOURCES or not FILE_RE.match(name):
            raise StoreError('invalid_id', f'invalid scenario id: {scenario_id!r}')
        directory = self._dir(source)
        if not directory:
            raise StoreError('not_found', f'no such scenario: {scenario_id}', 404)
        root = os.path.realpath(directory)
        path = os.path.realpath(os.path.join(root, name))
        if os.path.dirname(path) != root:
            raise StoreError('forbidden_path', f'{scenario_id} is outside the scenarios directory',
                             403)
        return source, name, path

    # ---- read ------------------------------------------------------------------------------
    @staticmethod
    def _read(path: str) -> str:
        if os.path.getsize(path) > MAX_SCENARIO_BYTES:
            raise StoreError('too_large', f'{os.path.basename(path)} is larger than '
                             f'{MAX_SCENARIO_BYTES // 1024} KB')
        with open(path, encoding='utf-8') as fh:
            return fh.read()

    def _entry(self, source: str, name: str, path: str) -> Dict[str, Any]:
        item: Dict[str, Any] = {'id': f'{source}:{name}', 'source': source, 'file': name,
                                'read_only': source == 'example', 'name': os.path.splitext(name)[0],
                                'description': None, 'steps': 0, 'error': None, 'errors': []}
        try:
            scenario = parse_text(self._read(path), name)
            item.update(name=scenario.name, description=scenario.description,
                        steps=len(scenario.steps), setup=len(scenario.setup),
                        guards=len(scenario.guards))
        except ScenarioSchemaError as exc:
            item.update(error=str(exc), errors=exc.errors)
        except (OSError, StoreError, UnicodeDecodeError) as exc:
            item['error'] = str(exc)
        return item

    def list(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        for source in SOURCES:
            directory = self._dir(source)
            if not directory or not os.path.isdir(directory):
                continue
            root = os.path.realpath(directory)
            names = sorted(n for n in os.listdir(root) if FILE_RE.match(n))[:MAX_FILES]
            for name in names:
                path = os.path.realpath(os.path.join(root, name))
                if os.path.dirname(path) == root and os.path.isfile(path):
                    items.append(self._entry(source, name, path))
        return items

    def get(self, scenario_id: str) -> Dict[str, Any]:
        source, name, path = self.resolve(scenario_id)
        if not os.path.isfile(path):
            raise StoreError('not_found', f'no such scenario: {scenario_id}', 404)
        text = self._read(path)
        out = self._entry(source, name, path)
        out['yaml'] = text
        try:
            from .schema import to_raw
            out['spec'] = to_raw(parse_text(text, name))
        except ScenarioSchemaError:
            out['spec'] = None
        return out

    def load(self, scenario_id: str) -> Tuple[Scenario, str]:
        """Parsed scenario for a run (raises ScenarioSchemaError) and its file path."""
        _source, name, path = self.resolve(scenario_id)
        if not os.path.isfile(path):
            raise StoreError('not_found', f'no such scenario: {scenario_id}', 404)
        return parse_text(self._read(path), name), path

    # ---- write (project only) ------------------------------------------------------------------
    @staticmethod
    def render(spec: Optional[Dict[str, Any]], text: Optional[str]) -> Tuple[Scenario, str]:
        """Validate a form spec (dumped canonically) or raw YAML (kept as written)."""
        if (spec is None) == (text is None):
            raise StoreError('invalid_request', 'send either "spec" or "yaml"')
        if text is not None:
            return parse_text(text, 'yaml'), text
        scenario = parse_data(spec, 'spec')
        return scenario, dump(scenario)

    def save(self, scenario_id: Optional[str], spec: Optional[Dict[str, Any]],
             text: Optional[str], file: Optional[str] = None,
             overwrite: bool = False) -> Dict[str, Any]:
        scenario, body = self.render(spec, text)
        if scenario_id is None:
            name = file or file_name_for(scenario.name)
            scenario_id = f'project:{name}'
        source, name, path = self.resolve(scenario_id)
        if source != 'project':
            raise StoreError('read_only', 'example scenarios are read-only; save a copy into '
                             'the project instead', 403)
        with self._lock:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            if os.path.exists(path) and not overwrite:
                raise StoreError('file_exists', f'{name} already exists', 409)
            write_atomic(path, body)
        LOG.info('scenario saved: %s', path)
        return self.get(scenario_id)

    def delete(self, scenario_id: str) -> Dict[str, Any]:
        source, name, path = self.resolve(scenario_id)
        if source != 'project':
            raise StoreError('read_only', 'example scenarios cannot be deleted', 403)
        if not os.path.isfile(path):
            raise StoreError('not_found', f'no such scenario: {scenario_id}', 404)
        os.unlink(path)
        return {'deleted': scenario_id}


class ResultStore:
    """The newest :data:`MAX_RESULTS` run results as JSON files under ``data_dir``."""

    def __init__(self, data_dir: str, limit: int = MAX_RESULTS):
        self.directory = os.path.join(os.path.realpath(data_dir), 'scenario_results')
        self._limit = limit
        self._lock = threading.Lock()

    def _files(self) -> List[str]:
        if not os.path.isdir(self.directory):
            return []
        names = [n for n in os.listdir(self.directory) if n.endswith('.json')]
        return sorted(names, key=lambda n: os.path.getmtime(os.path.join(self.directory, n)),
                      reverse=True)

    def save(self, result: Result) -> None:
        with self._lock:
            try:
                os.makedirs(self.directory, exist_ok=True)
                path = os.path.join(self.directory, f'{result.run_id}.json')
                write_atomic(path, json.dumps(result.to_dict(), ensure_ascii=False))
                for old in self._files()[self._limit:]:
                    os.unlink(os.path.join(self.directory, old))
            except OSError as exc:
                LOG.warning('cannot save scenario result: %s', exc)

    def get(self, run_id: str) -> Dict[str, Any]:
        if not RUN_ID_RE.match(str(run_id)):
            raise StoreError('invalid_id', f'invalid run id: {run_id!r}')
        path = os.path.join(self.directory, f'{run_id}.json')
        try:
            with open(path, encoding='utf-8') as fh:
                return json.load(fh)
        except FileNotFoundError:
            raise StoreError('not_found', f'no such run: {run_id}', 404) from None

    def list(self) -> List[Dict[str, Any]]:
        out = []
        for name in self._files():
            try:
                with open(os.path.join(self.directory, name), encoding='utf-8') as fh:
                    data = json.load(fh)
            except (OSError, ValueError):
                continue
            failed = next((s for s in [*data.get('setup', []), *data.get('guards', []),
                                       *data.get('steps', [])]
                           if s.get('status') in ('failed', 'error')), None)
            out.append({k: data.get(k) for k in ('run_id', 'scenario_id', 'name', 'file',
                                                  'status', 'started_at', 'duration_sec',
                                                  'message')}
                       | {'failed': None if failed is None else {
                           'index': failed.get('index'), 'kind': failed.get('kind'),
                           'message': failed.get('message')}})
        return out
