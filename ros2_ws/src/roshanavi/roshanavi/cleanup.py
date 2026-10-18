"""``ros2 run roshanavi cleanup``: stop nodes a force-killed roshanavi left running (#12).

Reads the process records under ``<data dir>/run`` (:mod:`.launcher.proc_record`)
of servers that are no longer running, and stops only the recorded processes
that still match their fingerprint (start time + command line), plus processes
they started since. Nothing else is ever signalled.
"""

import argparse
import sys
from typing import List, Optional

from .launcher.proc_record import find_leftovers, stop_leftovers


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog='roshanavi cleanup',
        description='Stop the nodes that a roshanavi server started and left behind when it '
                    'was force-killed (kill -9, out of memory). Only processes recorded by '
                    'roshanavi (and still matching the record) are stopped: SIGINT first, then '
                    'SIGTERM, then SIGKILL. In Docker, `docker restart <container>` does the '
                    'same for everything in the container.')
    parser.add_argument('--data-dir', default='/data',
                        help='the --data-dir the server used (default /data)')
    parser.add_argument('--dry-run', action='store_true',
                        help='only list what would be stopped')
    args, _unknown = parser.parse_known_args(argv)  # `ros2 run` may append --ros-args
    return args


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    leftovers = find_leftovers(args.data_dir, remove_stale=not args.dry_run)
    if not leftovers:
        print('Nothing to clean up: no process left by a previous roshanavi run.')
        return 0
    print(f'{len(leftovers)} process(es) left by a previous roshanavi run:')
    for item in leftovers:
        print(f'  pid {item.proc.pid} (target {item.target or "?"}): {item.cmd}')
    if args.dry_run:
        return 0
    result = stop_leftovers(leftovers, report=lambda line: print('  ' + line))
    print(f'Stopped {len(result["stopped"])} process(es).')
    if result['survivors']:
        print(f'{len(result["survivors"])} process(es) could not be stopped: '
              + ', '.join(str(s['pid']) for s in result['survivors']), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())
