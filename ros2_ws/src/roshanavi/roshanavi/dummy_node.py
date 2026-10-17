"""``ros2 run roshanavi dummy --config <yaml>``: one injection as its own ROS node.

The node name comes from the config (``dummy.name``) and can be overridden by
``--ros-args -r __node:=<name>`` (the Launcher and the exported launch file
always pass it, which also lets the Launcher map the node to this process
exactly). It reuses the injector (once / periodic / stream, ``${}``
expressions, JSONL / CSV files) and keeps running until SIGINT/SIGTERM, so the
node stays visible on the graph even after a finite job completes.

The node declares a bool parameter ``paused``: setting it to true (from the
roshanavi map, or ``ros2 param set``) stops sending without stopping the node.
"""

import argparse
import logging
import signal
import sys
import threading
from typing import Any, List, Optional

from rcl_interfaces.msg import ParameterDescriptor, SetParametersResult
from rclpy.parameter import Parameter

from .injector import Injector
from .jobs import InjectError
from .launcher.dummy_config import inject_spec, load_config
from .launcher.errors import LauncherError
from .msgutil import MsgUtilError
from .ros_runtime import RosRuntime

LOG = logging.getLogger('roshanavi.dummy')
POLL_SEC = 0.5
EXIT_CONFIG_ERROR = 2
EXIT_JOB_ERROR = 1
PAUSED_PARAM = 'paused'


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='roshanavi dummy',
                                     description='persistent dummy input node')
    parser.add_argument('--config', required=True, help='dummy node config YAML')
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


def run(config_path: str, stop: threading.Event) -> int:
    try:
        config = load_config(config_path)
    except LauncherError as exc:
        LOG.error('%s', exc)
        return EXIT_CONFIG_ERROR
    spec = config['spec']
    runtime = RosRuntime(spec.name, require_self_name=False)
    runtime.start()
    injector = Injector(runtime, config['data_dir'])
    try:
        job = injector.start(inject_spec(spec))
        install_pause_parameter(runtime.node, injector, job['id'])
        LOG.info('dummy node publishing %s (%s, %s)', spec.topic, spec.type, spec.mode)
        return _wait(injector, job['id'], stop)
    except (InjectError, MsgUtilError) as exc:
        LOG.error('cannot start injection: %s', exc)
        return EXIT_JOB_ERROR
    finally:
        injector.close()
        runtime.stop()


def install_pause_parameter(node: Any, injector: Injector, job_id: str) -> None:
    """``paused`` (bool) parameter that pauses / resumes the injection job."""
    node.declare_parameter(PAUSED_PARAM, False, ParameterDescriptor(
        description='true: stop sending (the node keeps running); false: send again'))

    def on_set(params: List[Parameter]) -> SetParametersResult:
        for param in params:
            if param.name != PAUSED_PARAM:
                continue
            if param.type_ != Parameter.Type.BOOL:
                return SetParametersResult(successful=False, reason='paused must be true/false')
            try:
                injector.set_paused(job_id, bool(param.value))
            except InjectError as exc:
                return SetParametersResult(successful=False, reason=str(exc))
        return SetParametersResult(successful=True)
    node.add_on_set_parameters_callback(on_set)


def _wait(injector: Injector, job_id: str, stop: threading.Event) -> int:
    reported = False
    while not stop.wait(POLL_SEC):
        job = injector.get(job_id)
        if job['state'] == 'error':
            LOG.error('injection failed: %s', job['error'])
            return EXIT_JOB_ERROR
        if job['state'] == 'done' and not reported:
            LOG.info('sent %d message(s); the node stays up until stopped', job['sent'])
            reported = True
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format='[%(levelname)s] %(name)s: %(message)s')
    stop = threading.Event()
    _install_signals(stop)
    return run(args.config, stop)


if __name__ == '__main__':
    sys.exit(main())
