"""Python API: ``run_scenario(path) -> Result`` (CLI, launch_pytest, the server).

Without a ``runtime`` the call owns a ROS runtime (its own rclpy context, node
``roshanavi_scenario``) for the duration of the run, so it can be used from any
test process, e.g. a ``launch_pytest`` test that launched the nodes itself.
"""

import os
import threading
from typing import Any, Callable, Dict, Optional, Union

from ..launcher.discovery import Workspace
from ..launcher.manager import ProcessManager
from ..launcher.project import ProjectStore
from ..ros_runtime import RosRuntime
from .procs import SetupProcesses, TargetController
from .result import Result, new_result, schema_error_result
from .runner import RunContext, ScenarioRunner
from .schema import Scenario, ScenarioSchemaError, load_file

RUNTIME_NODE = 'roshanavi_scenario'


def _project_lookup(path: Optional[str]) -> Callable[[str], Any]:
    """Find a target / dummy / transform / function of the project file by id."""
    def lookup(target_id: str) -> Any:
        if not path:
            return None
        spec = ProjectStore(path).load()
        for item in (*spec.targets, *spec.dummies, *spec.transforms, *spec.functions,
                     *spec.classes):
            if item.id == target_id:
                return item
        return None
    return lookup


def default_workspace() -> str:
    return os.environ.get('ROSHANAVI_WORKSPACE') or os.getcwd()


def default_data_dir() -> str:
    return os.environ.get('ROSHANAVI_DATA_DIR') or os.getcwd()


def run_loaded(scenario: Scenario, runtime: RosRuntime, data_dir: str, setup: SetupProcesses,
               targets: TargetController, *, file: str = '', scenario_id: Optional[str] = None,
               cancel: Optional[threading.Event] = None,
               progress: Optional[Callable[[Dict[str, Any]], None]] = None,
               extra_roots: tuple = (), result: Optional[Result] = None,
               settle_sec: Optional[float] = None, node_probe: Any = None) -> Result:
    result = result or new_result(scenario, file, scenario_id)
    ctx = RunContext(runtime=runtime, data_dir=data_dir, setup=setup, targets=targets,
                     extra_roots=extra_roots, cancel=cancel or threading.Event(),
                     progress=progress, node_probe=node_probe)
    if settle_sec is not None:
        ctx.settle_sec = settle_sec
    return ScenarioRunner(scenario, ctx, result).run()


def run_scenario(path: Union[str, Scenario], *, data_dir: Optional[str] = None,
                 workspace: Optional[str] = None, project: Optional[str] = None,
                 runtime: Optional[RosRuntime] = None,
                 cancel: Optional[threading.Event] = None,
                 progress: Optional[Callable[[Dict[str, Any]], None]] = None) -> Result:
    """Run one scenario file (or a parsed :class:`Scenario`) and return its :class:`Result`.

    ``data_dir`` holds stream / bag / media files (default ``$ROSHANAVI_DATA_DIR`` or the
    current directory), ``workspace`` the colcon workspace whose packages setup may start
    (default ``$ROSHANAVI_WORKSPACE`` or the current directory), ``project`` the
    ``roshanavi.yaml`` whose targets ``target:`` items and ``start: {target}`` steps use.
    An invalid file gives a result with status ``error`` and ``schema_errors``.
    """
    file = path if isinstance(path, str) else ''
    if isinstance(path, Scenario):
        scenario = path
    else:
        try:
            scenario = load_file(path)
        except ScenarioSchemaError as exc:
            return schema_error_result(os.path.splitext(os.path.basename(path))[0], path, exc)
    data_dir = os.path.realpath(data_dir or default_data_dir())
    ws = Workspace(workspace or default_workspace())
    own_runtime = runtime is None
    runtime = runtime or RosRuntime(RUNTIME_NODE)
    if own_runtime:
        runtime.start()
    try:
        setup = SetupProcesses(ProcessManager(ws, data_dir))
        targets = TargetController(ProcessManager(ws, data_dir), _project_lookup(project),
                                   owned=True)
        return run_loaded(scenario, runtime, data_dir, setup, targets, file=file, cancel=cancel,
                          progress=progress, extra_roots=(ws.root,))
    finally:
        if own_runtime:
            runtime.stop()
