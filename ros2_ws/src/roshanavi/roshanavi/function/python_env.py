"""Which Python runs function / class nodes, and what its search path is (server side).

- **A virtual environment wins.** When the server itself runs in a venv, or one is activated in
  the environment that started it (``VIRTUAL_ENV``), function / class nodes are started with
  ``ros2 run --prefix <venv>/bin/python3 roshanavi function ...`` so the user's libraries in that
  venv are importable (docs/design/user-code.md, 依存ライブラリ ②). Otherwise ``ros2 run`` uses
  the entry script's own interpreter (unchanged).
- **The search path of that interpreter** is asked once (``<python> -c <probe>``: argv list, no
  shell, 10 s, nothing of the user is imported) and cached, so installed modules (scope C) are
  located on the node's path, not the server's.
"""

import json
import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from typing import Any, Dict, Mapping, Optional, Tuple

LOG = logging.getLogger(__name__)

PROBE_TIMEOUT_SEC = 10.0
PROBE_TTL_SEC = 300.0
MAX_PROBE_BYTES = 1024 * 1024
PROBE_CODE = ('import json, platform, sys; print(json.dumps({"executable": sys.executable, '
              '"version": platform.python_version(), "prefix": sys.prefix, '
              '"base_prefix": getattr(sys, "base_prefix", sys.prefix), "path": sys.path}))')


def _executable(path: str) -> bool:
    return os.path.isfile(path) and os.access(path, os.X_OK)


def venv_python(env: Mapping[str, str]) -> Optional[str]:
    """The venv interpreter function nodes should use, or None (no venv: keep ``ros2 run``)."""
    if sys.prefix != getattr(sys, 'base_prefix', sys.prefix):
        return sys.executable
    venv = env.get('VIRTUAL_ENV')
    if venv:
        for name in ('python3', 'python'):
            path = os.path.join(venv, 'bin', name)
            if _executable(path):
                return path
    return None


def entry_script_python(script: Optional[str], env: Mapping[str, str]) -> str:
    """The interpreter of an entry script's shebang (``#!/usr/bin/python3`` / ``env python3``)."""
    if script:
        try:
            with open(script, 'rb') as fh:
                first = fh.readline(512).decode('utf-8', 'replace').strip()
        except OSError:
            first = ''
        if first.startswith('#!'):
            parts = first[2:].split()
            if parts and os.path.basename(parts[0]) == 'env' and len(parts) > 1:
                found = shutil.which(parts[1], path=env.get('PATH'))
                if found:
                    return found
            elif parts and _executable(parts[0]):
                return parts[0]
    return sys.executable


class InterpreterProbe:
    """``{executable, version, prefix, base_prefix, venv, path}`` of an interpreter, cached."""

    def __init__(self, runner: Any = subprocess.run, clock: Any = time.monotonic):
        self._run = runner
        self._clock = clock
        self._lock = threading.Lock()
        self._cache: Dict[Tuple[str, str, str], Tuple[float, Dict[str, Any]]] = {}

    def info(self, python: str, env: Mapping[str, str], refresh: bool = False) -> Dict[str, Any]:
        key = (python, env.get('PYTHONPATH', ''), env.get('VIRTUAL_ENV', ''))
        with self._lock:
            hit = self._cache.get(key)
        if hit and not refresh and self._clock() - hit[0] < PROBE_TTL_SEC:
            return hit[1]
        info = self._probe(python, env)
        with self._lock:
            self._cache[key] = (self._clock(), info)
        return info

    def _probe(self, python: str, env: Mapping[str, str]) -> Dict[str, Any]:
        fallback = {'executable': python, 'version': None, 'prefix': None, 'venv': None,
                    'path': list(sys.path)}
        try:
            done = self._run([python, '-c', PROBE_CODE], env=dict(env), capture_output=True,
                             timeout=PROBE_TIMEOUT_SEC, check=False, stdin=subprocess.DEVNULL)
            out = (done.stdout or b'')[:MAX_PROBE_BYTES]
            data = json.loads(out.decode('utf-8', 'replace')) if done.returncode == 0 else None
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            LOG.warning('cannot ask %s for its search path: %s', python, exc)
            return {**fallback, 'error': str(exc)}
        if not isinstance(data, dict) or not isinstance(data.get('path'), list):
            err = (getattr(done, 'stderr', b'') or b'')[-500:].decode('utf-8', 'replace')
            return {**fallback, 'error': err or 'no answer'}
        return {'executable': str(data.get('executable') or python),
                'version': data.get('version'), 'prefix': data.get('prefix'),
                'venv': data.get('prefix') != data.get('base_prefix'),
                'path': [str(p) for p in data['path'] if isinstance(p, str)]}
