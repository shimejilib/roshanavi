"""``ros2 run roshanavi function --config <yaml>``: a function or class node (docs/design/nodes.md).

A config with a ``class`` key runs a class node (``run_class``, below); a ``function`` key is the
function node described here.

Imports a plain Python function from a workspace package (``function.module``),
calls it with the value of each received message (or periodically), and
publishes what it returns. ``None`` publishes nothing; an exception is logged
with file:line and the node keeps running. Saving the module file reloads the
function (``function/loader.py``).

The config is ``{function: <FunctionSpec>, workspace: <root>, status_file?: <path>,
code_paths?: [...], installed_modules?: [...]}`` (the last two: the project's opt-in code
locations, docs/design/user-code.md).
Exit codes: 2 = bad config, 1 = cannot start (unknown message type ...),
0 = stopped by SIGINT / SIGTERM. A module that does not import yet is not an
exit: the node waits for the file to be fixed and reports the error.
"""

import argparse
import logging
import signal
import sys
import threading
from typing import List, Optional

from . import data_kinds
from .function.class_loader import ClassLoader
from .function.class_runner import ClassRunner
from .function.loader import FunctionLoader, LoadError, Watcher
from .function.runner import FunctionRunner, StatusFile
from .function.scopes import CodeLocations
from .launcher.schema import ClassSpec
from .launcher.dummy_config import load_function_config
from .launcher.errors import LauncherError
from .msgutil import MsgUtilError
from .ros_runtime import RosRuntime

LOG = logging.getLogger('roshanavi.function')
STATUS_PERIOD_SEC = 1.0
EXIT_CONFIG_ERROR = 2
EXIT_START_ERROR = 1


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='roshanavi function',
                                     description='function node: a Python function as a node')
    parser.add_argument('--config', required=True, help='function node config YAML')
    parser.add_argument('--log-level', default='info',
                        choices=['debug', 'info', 'warning', 'error'])
    args, _ros_args = parser.parse_known_args(argv)  # --ros-args ... is for rclpy
    return args


def _install_signals(stop: threading.Event) -> None:
    def handler(signum: int, _frame: object) -> None:
        LOG.info('received %s, shutting down', signal.Signals(signum).name)
        stop.set()
    signal.signal(signal.SIGINT, handler)
    signal.signal(signal.SIGTERM, handler)


def locations_of(config: dict) -> CodeLocations:
    """Scope A (the workspace) and the project's scope B / C; installed modules are looked up
    on this process's own ``sys.path`` (it is the node's interpreter)."""
    code = config['code']
    return CodeLocations(workspace=config['workspace'], code_paths=tuple(code.code_paths),
                         installed_modules=tuple(code.installed_modules))


def run(config_path: str, stop: threading.Event) -> int:
    try:
        config = load_function_config(config_path)
    except LauncherError as exc:
        LOG.error('%s', exc)
        return EXIT_CONFIG_ERROR
    if isinstance(config['spec'], ClassSpec):
        return run_class(config, stop)
    spec, status = config['spec'], StatusFile(config.get('status_file'))
    loader = FunctionLoader(locations_of(config), spec.module, spec.function)
    try:
        loader.load()
        LOG.info('loaded %s.%s%s from %s', spec.module, spec.function, loader.signature,
                 loader.location_of_function())
    except LoadError as exc:
        LOG.error('関数を読み込めません / cannot import the function: %s '
                  '(waiting for the file to be fixed)', exc)
    runtime = RosRuntime(spec.name, require_self_name=False)
    runtime.start()
    runner: Optional[FunctionRunner] = None
    watcher: Optional[Watcher] = None
    try:
        runner = FunctionRunner(spec, runtime, loader)
        if loader.problem is not None:
            runner.core.report(loader.problem)
        watcher = Watcher(loader, runner.core.on_reload)
        watcher.start()
        LOG.info('function %s: %s -> %s (%s)', spec.function,
                 ', '.join(p.topic for p in runner.core.inputs) or f'every {1 / spec.rate_hz:g} s',
                 spec.output.topic, spec.call)
        status.write(runner.core.snapshot())
        while not stop.wait(STATUS_PERIOD_SEC):
            status.write(runner.core.snapshot())
        return 0
    except (MsgUtilError, data_kinds.KindError) as exc:
        LOG.error('cannot start: %s', exc)
        return EXIT_START_ERROR
    finally:
        if watcher is not None:
            watcher.close()
        if runner is not None:
            status.write({**runner.core.snapshot(), 'state': 'stopped'})
            runner.close()
        runtime.stop()


def run_class(config: dict, stop: threading.Event) -> int:
    """A class node: one instance of the user's class, methods bound to topics (class_core)."""
    spec, status = config['spec'], StatusFile(config.get('status_file'))
    loader = ClassLoader(locations_of(config), spec.module, spec.class_name)
    try:
        loader.load()
        LOG.info('loaded %s.%s%s from %s', spec.module, spec.class_name, loader.signature,
                 loader.location_of_function())
    except LoadError as exc:
        LOG.error('クラスを読み込めません / cannot import the class: %s '
                  '(waiting for the file to be fixed)', exc)
    runtime = RosRuntime(spec.name, require_self_name=False)
    runtime.start()
    runner: Optional[ClassRunner] = None
    watcher: Optional[Watcher] = None
    try:
        runner = ClassRunner(spec, runtime, loader)
        core = runner.core
        core.on_change = lambda: status.write(core.snapshot())
        if loader.problem is not None:
            core.report(loader.problem)
        watcher = Watcher(loader, core.on_reload, reload_fn=core.reload)
        watcher.start()
        LOG.info('class %s: %d method(s), %d action(s)', spec.class_name, len(spec.methods),
                 len(spec.actions))
        status.write(core.snapshot())
        while not stop.wait(STATUS_PERIOD_SEC):
            status.write(core.snapshot())
        return 0
    except (MsgUtilError, data_kinds.KindError) as exc:
        LOG.error('cannot start: %s', exc)
        return EXIT_START_ERROR
    finally:
        if watcher is not None:
            watcher.close()
        if runner is not None:
            runner.core.on_change = None
            runner.close()
            status.write({**runner.core.snapshot(), 'state': 'stopped'})
        runtime.stop()


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format='[%(levelname)s] %(name)s: %(message)s')
    stop = threading.Event()
    _install_signals(stop)
    return run(args.config, stop)


if __name__ == '__main__':
    sys.exit(main())
