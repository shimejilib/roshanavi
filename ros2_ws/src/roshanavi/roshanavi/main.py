"""Entry point: ``ros2 run roshanavi server [--host H] [--port P] ...``.

Child processes started by the Launcher are stopped on every exit path:
uvicorn's SIGINT/SIGTERM handling returns from ``uvicorn.run`` (``finally``),
SIGHUP is turned into SIGTERM, and ``atexit`` covers ``sys.exit`` elsewhere.
Only SIGKILL of the server itself can leave children behind.
"""

import argparse
import atexit
import logging
import os
import signal
import sys
from typing import List, Optional

PACKAGE_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static')
# The Docker image bakes the UI elsewhere and points this variable at it.
DEFAULT_STATIC_DIR = os.environ.get('ROSHANAVI_STATIC_DIR') or PACKAGE_STATIC_DIR

LOG = logging.getLogger('roshanavi')


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog='roshanavi server',
                                     description='roshanavi web/API server')
    parser.add_argument('--host', default='127.0.0.1', help='bind address (default 127.0.0.1)')
    parser.add_argument('--port', type=int, default=8080, help='bind port (default 8080)')
    parser.add_argument('--data-dir', default='/data',
                        help='root for stream/bag files (default /data)')
    parser.add_argument('--static-dir', default=DEFAULT_STATIC_DIR,
                        help='built web UI directory (served at / if it has index.html)')
    parser.add_argument('--show-self', action='store_true',
                        help='include the roshanavi node itself in graph/traffic')
    parser.add_argument('--monitor-heavy', action='store_true',
                        help='subscribe to heavy topics too (images, point clouds); '
                             'default is opt-in per topic via the API')
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
    parser.add_argument('--log-level', default='info',
                        choices=['debug', 'info', 'warning', 'error'])
    # `ros2 run` may append --ros-args ...; ignore anything we do not know.
    args, _unknown = parser.parse_known_args(argv)
    if not 0 < args.port < 65536:
        parser.error('--port must be in 1..65535')
    return args


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
    lab = Lab(data_dir=args.data_dir, show_self=args.show_self,
              monitor_heavy=args.monitor_heavy, workspace=args.workspace,
              project_path=args.project, autostart=not args.no_autostart,
              disk_thresholds=DiskThresholds(args.record_warn_free_mb, args.record_warn_free_pct,
                                             args.record_stop_free_mb,
                                             args.record_stop_free_pct)).start()
    atexit.register(lab.launcher.close)
    signal.signal(signal.SIGHUP, lambda *_: os.kill(os.getpid(), signal.SIGTERM))
    try:
        app = create_app(lab, static_dir=args.static_dir, allowed_hosts=args.allowed_host,
                         allowed_origins=args.allowed_origin)
        uvicorn.run(app, host=args.host, port=args.port, log_level=args.log_level)
    finally:
        lab.stop()
    return 0


if __name__ == '__main__':
    sys.exit(main())
