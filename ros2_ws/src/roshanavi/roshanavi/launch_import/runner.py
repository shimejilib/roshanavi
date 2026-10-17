"""Run the launch-file evaluation child with a timeout (server side, docs/design/launcher.md).

Evaluating a Python launch file executes its code, so it never happens in
the server process: :mod:`.child` runs in a new session (process group) with
the same environment the launcher gives its own processes. On timeout the whole
group is killed; after a normal exit the group is killed too, so nothing the
launch file may have started in the background survives. Only one JSON
object comes back, which is size-limited and shape-checked here.
"""

import json
import logging
import os
import signal
import subprocess
import sys
from typing import Any, Dict, Mapping

from ..launcher.errors import LauncherError

LOG = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SEC = 20.0
MAX_OUTPUT_BYTES = 8 * 1024 * 1024
STDERR_TAIL = 1500
CHILD_MODULE = 'roshanavi.launch_import.child'


def _kill_group(pid: int) -> None:
    try:
        os.killpg(pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass  # the group is already gone


def _tail(data: bytes) -> str:
    return data.decode('utf-8', 'replace')[-STDERR_TAIL:].strip()


def run_child(request: Mapping[str, Any], env: Mapping[str, str], cwd: str,
              timeout_sec: float = DEFAULT_TIMEOUT_SEC) -> Dict[str, Any]:
    """Evaluate ``request`` (``{path, args}``) in a subprocess; the parsed JSON result."""
    try:
        proc = subprocess.Popen([sys.executable, '-m', CHILD_MODULE], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                env=dict(env), cwd=cwd, start_new_session=True)
    except OSError as exc:
        raise LauncherError('launch_eval_failed', f'cannot start the evaluator: {exc}',
                            500) from exc
    try:
        out, err = proc.communicate(json.dumps(dict(request)).encode(), timeout=timeout_sec)
    except subprocess.TimeoutExpired:
        _kill_group(proc.pid)
        proc.communicate()
        raise LauncherError('launch_eval_timeout', f'evaluating the launch file took longer '
                            f'than {timeout_sec:g} s', 504) from None
    finally:
        _kill_group(proc.pid)
    if err:
        LOG.debug('launch evaluation stderr: %s', _tail(err))
    return parse_output(out, err, proc.returncode)


def parse_output(out: bytes, err: bytes, returncode: int) -> Dict[str, Any]:
    if len(out) > MAX_OUTPUT_BYTES:
        raise LauncherError('launch_eval_failed', 'the evaluation result is too large', 422)
    try:
        payload = json.loads(out.decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise LauncherError('launch_eval_failed', f'the evaluator stopped (exit code '
                            f'{returncode}): {_tail(err) or "no output"}', 422) from None
    if not isinstance(payload, dict):
        raise LauncherError('launch_eval_failed', 'unexpected evaluation result', 422)
    if not payload.get('ok'):
        error = payload.get('error') if isinstance(payload.get('error'), dict) else {}
        raise LauncherError('launch_eval_failed', str(error.get('message') or 'unknown error'),
                            422)
    return payload
