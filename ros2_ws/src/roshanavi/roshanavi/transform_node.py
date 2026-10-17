"""``ros2 run roshanavi transform --config <yaml>``: a transform node (変換ノード).

Subscribes the input topic(s) of the config's ``transform`` spec and publishes
the computed (``mode: map``) or forwarded (``mode: relay``) messages on the
output topic, with optional filter condition, drop ratio, throttle and delay
(DESIGN §4.18). The node name comes from ``--ros-args -r __node:=<name>``
(the Launcher and the exported launch file always pass it) or the spec.

Exit codes: 2 = bad config (unreadable, schema or expression errors),
1 = cannot start (unknown message type ...), 0 = stopped by SIGINT / SIGTERM.
Counters (received / published / filtered / dropped / throttled / errors) are
logged every 10 s while they change.
"""

import argparse
import logging
import signal
import sys
import threading
from typing import Any, Dict, List, Optional

from .launcher.dummy_config import load_transform_config
from .launcher.errors import LauncherError
from .msgutil import MsgUtilError
from .ros_runtime import RosRuntime
from .transform.runner import TransformConfigError, TransformRunner

LOG = logging.getLogger('roshanavi.transform')
STATS_PERIOD_SEC = 10.0
EXIT_CONFIG_ERROR = 2
EXIT_START_ERROR = 1


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='roshanavi transform',
                                     description='transform node: topic(s) in -> topic out')
    parser.add_argument('--config', required=True, help='transform node config YAML')
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
        spec = load_transform_config(config_path)
    except LauncherError as exc:
        LOG.error('%s', exc)
        return EXIT_CONFIG_ERROR
    runtime = RosRuntime(spec.name, require_self_name=False)
    runtime.start()
    runner: Optional[TransformRunner] = None
    try:
        runner = TransformRunner(spec, runtime)
        LOG.info('transform %s -> %s (%s)', ', '.join(i.topic for i in spec.inputs),
                 spec.output.topic, spec.mode)
        _report_until(stop, runner)
        return 0
    except TransformConfigError as exc:
        LOG.error('invalid expression: %s', exc)
        return EXIT_CONFIG_ERROR
    except MsgUtilError as exc:
        LOG.error('cannot start: %s', exc)
        return EXIT_START_ERROR
    finally:
        if runner is not None:
            runner.close()
        runtime.stop()


def _report_until(stop: threading.Event, runner: TransformRunner) -> None:
    last: Dict[str, Any] = {}
    while not stop.wait(STATS_PERIOD_SEC):
        stats = runner.snapshot()
        if stats != last:
            LOG.info('received %(received)d, published %(published)d, filtered %(filtered)d, '
                     'dropped %(dropped)d, throttled %(throttled)d, errors %(errors)d', stats)
            last = stats


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format='[%(levelname)s] %(name)s: %(message)s')
    stop = threading.Event()
    _install_signals(stop)
    return run(args.config, stop)


if __name__ == '__main__':
    sys.exit(main())
