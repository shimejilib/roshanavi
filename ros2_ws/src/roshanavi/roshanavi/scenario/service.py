"""Server side of scenarios: run one at a time in a thread, progress, cancel, history.

A run uses the lab's ROS runtime and workspace, a private process manager for its
setup processes, and the lab's launcher for ``target`` items / steps (put back as
they were at the end). Results are kept under ``data_dir/scenario_results``.
"""

import logging
import threading
from typing import Any, Callable, Dict, List, Optional

from ..launcher.manager import ProcessManager
from .procs import SetupProcesses, TargetController
from .recorder import ScenarioRecorder
from .result import Result, new_result, schema_error_result
from .schema import ScenarioSchemaError
from .store import ResultStore, ScenarioStore, StoreError

LOG = logging.getLogger(__name__)

JOIN_SEC = 30.0


class ScenarioService:
    def __init__(self, lab: Any, project_path: Callable[[], str]):
        self._lab = lab
        self.store = ScenarioStore(project_path, lab.examples_dir)
        self.results = ResultStore(lab.data_dir)
        self.recorder = ScenarioRecorder(lab.runtime)
        self._lock = threading.Lock()
        self._thread: Optional[threading.Thread] = None
        self._cancel: Optional[threading.Event] = None
        self._snapshot: Optional[Dict[str, Any]] = None

    # ---- runs ------------------------------------------------------------------------------
    @property
    def running(self) -> bool:
        thread = self._thread
        return thread is not None and thread.is_alive()

    def current(self) -> Optional[Dict[str, Any]]:
        return self._snapshot

    def run(self, scenario_id: str) -> Dict[str, Any]:
        with self._lock:
            if self.running:
                raise StoreError('run_busy', 'another scenario is running; wait for it or '
                                 'cancel it first', 409)
            try:
                scenario, path = self.store.load(scenario_id)
            except ScenarioSchemaError as exc:
                result = schema_error_result(scenario_id.partition(':')[2], scenario_id, exc,
                                             scenario_id)
                self.results.save(result)
                self._snapshot = result.to_dict()
                return self._snapshot
            result = new_result(scenario, scenario_id.partition(':')[2], scenario_id)
            self._snapshot = result.to_dict()
            cancel = threading.Event()
            self._cancel = cancel
            self._thread = threading.Thread(target=self._run, args=(scenario, result, cancel),
                                            name=f'scenario-{result.run_id}', daemon=True)
            self._thread.start()
            return self._snapshot

    def _publish(self, snapshot: Dict[str, Any]) -> None:
        self._snapshot = snapshot

    def _run(self, scenario: Any, result: Result, cancel: threading.Event) -> None:
        from .api import run_loaded  # needs rclpy; kept out of import time
        lab = self._lab
        workspace = lab.launcher.workspace
        try:
            setup = SetupProcesses(ProcessManager(workspace, lab.data_dir))
            targets = TargetController(lab.launcher.manager)
            run_loaded(scenario, lab.runtime, lab.data_dir, setup, targets, cancel=cancel,
                       progress=self._publish, extra_roots=(workspace.root,), result=result)
        except Exception as exc:  # the runner handles its own errors; this is a last resort
            LOG.exception('scenario run failed')
            result.status, result.message = 'error', f'{type(exc).__name__}: {exc}'
        self._snapshot = result.to_dict()
        self.results.save(result)
        LOG.info('scenario %s finished: %s', scenario.name, result.status)

    def cancel(self, run_id: str) -> Dict[str, Any]:
        snapshot = self._snapshot
        if snapshot is None or snapshot.get('run_id') != run_id or not self.running:
            raise StoreError('not_running', f'run {run_id} is not running', 409)
        if self._cancel is not None:
            self._cancel.set()
        return {'run_id': run_id, 'cancelling': True}

    def history(self) -> List[Dict[str, Any]]:
        return self.results.list()

    def close(self) -> None:
        self.recorder.close()
        if self._cancel is not None:
            self._cancel.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=JOIN_SEC)
