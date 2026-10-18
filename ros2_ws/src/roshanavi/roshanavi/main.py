"""Entry point: ``ros2 run roshanavi server [--host H] [--port P] ...``.

Child processes started by the Launcher are stopped on every exit path:
uvicorn's SIGINT/SIGTERM handling returns from ``uvicorn.run`` (``finally``),
SIGHUP is turned into SIGTERM, and ``atexit`` covers ``sys.exit`` elsewhere.
uvicorn 0.29+ (Lyrical) re-raises the handled signal after its graceful shutdown;
the SIGTERM handler below turns that into :class:`_Stopped` (SIGINT into
``KeyboardInterrupt``), so ``finally`` still runs instead of the process dying.
Only SIGKILL of the server itself can leave children behind.
"""

import argparse
import atexit
import logging
import os
import signal
import sys
from typing import Any, Dict, List, Optional

PACKAGE_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
# The Docker image bakes the UI elsewhere and points this variable at it.
DEFAULT_STATIC_DIR = os.environ.get('ROSHANAVI_STATIC_DIR') or PACKAGE_STATIC_DIR

LOG = logging.getLogger('roshanavi')


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='roshanavi server',
                                     description='roshanavi web/API server')
    parser.add_argument('--host', default='127.0.0.1', help='bind address (default 127.0.0.1)')
    parser.add_argument('--port', type=int, default=6871, help='bind port (default 6871: below the DDS/RTPS ports 7400+, '
                             'outside the ephemeral range and common dev ports)')
    parser.add_argument('--data-dir', default='/data',
                        help='root for stream/bag files (default /data)')
    parser.add_argument('--static-dir', default=DEFAULT_STATIC_DIR,
                        help='built web UI directory (served at / if it has index.html)')
    parser.add_argument('--show-self', action='store_true',
                        help='include the roshanavi node itself in graph/traffic')
    parser.add_argument('--monitor-heavy', action='store_true',
                        help='subscribe to heavy topics too (images, point clouds); '
                             'default is opt-in per topic via the API')
    parser.add_argument('--probe', choices=['auto', 'off'], default='auto',
                        help='measure traffic with the C++ probe (roshanavi_probe) when it is '
                             'built (auto, default) or always in Python (off)')
    parser.add_argument('--tracing', choices=['auto', 'off'], default='auto',
                        help='詳細計測モード (LTTng tracing): auto (default) records node start-up '
                             'events while lttng and python3-bt2 are installed, so the mode can be '
                             'turned on from the UI without restarting nodes; off disables it')
    parser.add_argument('--trace-buffer-kib', type=int, default=4096,
                        help='詳細計測モード: ring buffer per CPU in KiB (default 4096; shrunk to '
                             'fit half of the free /dev/shm)')
    parser.add_argument('--allowed-host', action='append', default=[], metavar='HOST',
                        help='extra Host header value to accept (repeatable); localhost, '
                             '127.0.0.1 and [::1] are always allowed')
    parser.add_argument('--allowed-origin', action='append', default=[], metavar='ORIGIN',
                        help='extra WebSocket Origin to accept, e.g. https://lab.example:8443 '
                             '(repeatable)')
    parser.add_argument('--workspace',
                        default=os.environ.get('ROSHANAVI_WORKSPACE') or os.getcwd(),
                        help='colcon workspace root (default: $ROSHANAVI_WORKSPACE or cwd)')
    parser.add_argument('--project', default=None,
                        help='project file (default: <workspace>/roshanavi.yaml)')
    parser.add_argument('--project-template',
                        default=os.environ.get('ROSHANAVI_PROJECT_TEMPLATE') or None,
                        help='copy this project file to --project when that file does not '
                             'exist yet (never overwrites; e.g. the demo project)')
    parser.add_argument('--examples-dir',
                        default=os.environ.get('ROSHANAVI_EXAMPLES_DIR') or None,
                        help='folder of example projects (<name>/roshanavi.yaml) offered in the '
                             'settings menu; default: two levels above --project-template')
    parser.add_argument('--no-sample-media', action='store_true',
                        help='do not generate the perception demo media (data-dir/samples) '
                             'with ffmpeg on start')
    parser.add_argument('--no-autostart', action='store_true',
                        help='do not start the project targets marked autostart')
    parser.add_argument('--record-warn-free-mb', type=float, default=1024.0,
                        help='recording: warn below this much free space (MiB, default 1024)')
    parser.add_argument('--record-warn-free-pct', type=float, default=5.0,
                        help='recording: warn below this %% of the volume free (default 5)')
    parser.add_argument('--record-stop-free-mb', type=float, default=256.0,
                        help='recording: stop automatically below this (MiB, default 256)')
    parser.add_argument('--record-stop-free-pct', type=float, default=1.0,
                        help='recording: stop automatically below this %% free (default 1)')
    parser.add_argument('--no-resources', action='store_true',
                        help='turn off resource monitoring (CPU / memory / disk / network / GPU, '
                             'docs/design/resources.md)')
    parser.add_argument('--no-reverse-dns', action='store_true',
                        help='do not look up host names of remote addresses in the connection list')
    parser.add_argument('--log-level', default='info',
                        choices=['debug', 'info', 'warning', 'error'])
    takeover = parser.add_argument_group(
        'launch takeover', 'Run an existing launch file under roshanavi: its nodes become '
        'targets you can stop, restart and read logs of one by one (docs/guide).')
    takeover.add_argument('--launch', nargs='+', metavar='ARG', default=None,
                          help='PACKAGE LAUNCH_FILE [name:=value ...]: take over this launch '
                               'file of a package and start everything in it. The launch file '
                               'stays the source of truth: when it changes, the UI offers to '
                               'import it again. Restarting roshanavi with the same file and '
                               'arguments reuses the targets (no duplicates)')
    takeover.add_argument('--launch-mode', choices=['node', 'whole'], default='node',
                          help='node (default): one target per node (fine-grained control); '
                               'parts that cannot run one by one (ExecuteProcess, containers, '
                               'timers, event handlers) run together as one extra target, and '
                               'the UI lists launch behaviour that is lost. whole: run the '
                               'launch file as one target, exactly like ros2 launch (stop and '
                               'restart only all together)')
    takeover.add_argument('--mine', action='append', default=[], metavar='NODE',
                          help='node you are developing (role "mine"); repeatable, e.g. '
                               '--mine patrol')
    # `ros2 run` may append --ros-args ...; ignore anything we do not know.
    args, _unknown = parser.parse_known_args(argv)
    if not 0 < args.port < 65536:
        parser.error('--port must be in 1..65535')
    args.launch_spec = _launch_spec(parser, args.launch)
    return args


def _launch_spec(parser: argparse.ArgumentParser,
                 values: Optional[List[str]]) -> Optional[Dict[str, Any]]:
    """``--launch PACKAGE LAUNCH_FILE [name:=value ...]`` -> {package, launch_file, args}."""
    if not values:
        return None
    if len(values) < 2:
        parser.error('--launch needs PACKAGE and LAUNCH_FILE, e.g. '
                     '--launch turtle_patrol patrol.launch.py side_length:=2.0')
    launch_args: Dict[str, str] = {}
    for item in values[2:]:
        name, sep, value = item.partition(':=')
        if not sep or not name:
            parser.error(f'--launch: launch arguments look like name:=value (got {item!r})')
        launch_args[name] = value
    return {'package': values[0], 'launch_file': values[1], 'args': launch_args}


def _bootstrap(args: argparse.Namespace) -> None:
    """Install the project template if requested (a broken template is logged, not fatal)."""
    from .launcher.errors import LauncherError
    from .launcher.project import DEFAULT_FILE_NAME, bootstrap_project
    path = args.project or os.path.join(args.workspace, DEFAULT_FILE_NAME)
    try:
        bootstrap_project(path, args.project_template)
    except LauncherError as exc:
        LOG.error('project template not installed: %s', exc)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    logging.basicConfig(level=args.log_level.upper(),
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    import uvicorn  # imported late so --help works without heavy imports

    from .lab import Lab
    from .media.diskguard import DiskThresholds
    from .server import create_app

    if not os.path.isdir(args.data_dir):
        LOG.warning('data dir %s does not exist; stream/bag injection will fail', args.data_dir)
    if not os.path.isdir(args.workspace):
        LOG.error('workspace %s does not exist', args.workspace)
        return 2
    _bootstrap(args)
    examples_dir = args.examples_dir or (
        os.path.dirname(os.path.dirname(os.path.abspath(args.project_template)))
        if args.project_template else None)
    lab = Lab(data_dir=args.data_dir, show_self=args.show_self,
              monitor_heavy=args.monitor_heavy, workspace=args.workspace,
              project_path=args.project, autostart=not args.no_autostart,
              disk_thresholds=DiskThresholds(args.record_warn_free_mb, args.record_warn_free_pct,
                                             args.record_stop_free_mb,
                                             args.record_stop_free_pct),
              probe=args.probe, tracing=args.tracing,
              trace_buffer_per_cpu=max(8, args.trace_buffer_kib) * 1024,
              examples_dir=examples_dir, generate_samples=not args.no_sample_media,
              resources=not args.no_resources, reverse_dns=not args.no_reverse_dns,
              use_remembered_project=args.launch_spec is None).start()
    if args.launch_spec:
        _start_takeover(lab, args)
    atexit.register(lab.launcher.close)
    atexit.register(lab.tracing.close)
    signal.signal(signal.SIGHUP, lambda *_: os.kill(os.getpid(), signal.SIGTERM))
    signal.signal(signal.SIGTERM, _raise_stopped)
    try:
        app = create_app(lab, static_dir=args.static_dir, allowed_hosts=args.allowed_host,
                         allowed_origins=args.allowed_origin)
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    except (_Stopped, KeyboardInterrupt):
        pass  # the signal uvicorn re-raised after shutting down (uvicorn 0.29+)
    finally:
        signal.signal(signal.SIGTERM, signal.SIG_DFL)  # a second SIGTERM while stopping kills
        lab.stop()
    return 0


def _start_takeover(lab: Any, args: argparse.Namespace) -> None:
    from .launcher.errors import LauncherError
    spec = args.launch_spec
    try:
        lab.takeover.configure(spec['package'], spec['launch_file'], spec['args'],
                               mode=args.launch_mode, mine=args.mine)
    except LauncherError as exc:  # shown in the UI as well (GET /api/takeover)
        LOG.error('--launch: %s', exc)
        lab.takeover.fail(exc)


class _Stopped(Exception):
    """SIGTERM reached the server outside uvicorn's own handler."""


def _raise_stopped(*_args) -> None:
    raise _Stopped()


if __name__ == '__main__':
    sys.exit(main())
