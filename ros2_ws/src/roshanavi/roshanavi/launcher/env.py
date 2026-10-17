"""Child-process environment, including not-yet-sourced workspace packages.

A package built after the server started is not on ``AMENT_PREFIX_PATH`` (or
``PYTHONPATH`` ...), so ``ros2 run`` would not find it. colcon writes the
environment changes of each package as ``share/<pkg>/package.dsv`` (a tiny
declarative format: ``type;VARIABLE;value``); we apply those directly instead
of sourcing shell scripts, so no shell is ever involved.
"""

import logging
import os
from typing import Dict, Iterable, List, Mapping, Set

LOG = logging.getLogger(__name__)

# Line-buffered, uncolored output so logs stream promptly and read cleanly.
LOG_ENV = {'PYTHONUNBUFFERED': '1', 'RCUTILS_LOGGING_BUFFERED_STREAM': '0',
           'RCUTILS_COLORIZED_OUTPUT': '0'}
MAX_DSV_DEPTH = 4
PREPEND_TYPES = ('prepend-non-duplicate', 'prepend-non-duplicate-if-exists')


def _prepend(env: Dict[str, str], name: str, value: str) -> None:
    parts = [p for p in env.get(name, '').split(os.pathsep) if p]
    if value in parts:
        parts.remove(value)
    env[name] = os.pathsep.join([value, *parts])


def _apply_line(env: Dict[str, str], prefix: str, line: str, seen: Set[str], depth: int) -> None:
    kind, _, rest = line.partition(';')
    if kind == 'source':
        if rest.endswith('.dsv'):
            apply_dsv(env, prefix, os.path.join(prefix, rest), seen, depth + 1)
        return  # .sh/.bash/.ps1 variants describe the same change
    name, _, value = rest.partition(';')
    if not name:
        return
    path = os.path.join(prefix, value) if value else prefix
    if kind in PREPEND_TYPES:
        if kind.endswith('if-exists') and not os.path.exists(path):
            return
        _prepend(env, name, path)
    elif kind == 'set-if-unset':
        env.setdefault(name, value)
    elif kind == 'set':
        env[name] = value
    else:
        LOG.debug('dsv: unsupported line %r', line)


def apply_dsv(env: Dict[str, str], prefix: str, path: str, seen: Set[str],
              depth: int = 0) -> None:
    real = os.path.realpath(path)
    if depth > MAX_DSV_DEPTH or real in seen or not os.path.isfile(real):
        return
    seen.add(real)
    try:
        with open(real, encoding='utf-8') as fh:
            lines = [ln.strip() for ln in fh if ln.strip() and not ln.startswith('#')]
    except OSError as exc:
        LOG.warning('cannot read %s: %s', real, exc)
        return
    for line in lines:
        _apply_line(env, prefix, line, seen, depth)


def overlay_prefixes(env: Dict[str, str], prefixes: Iterable[str]) -> None:
    """Apply each isolated-install prefix's ``share/<pkg>/package.dsv`` to ``env``."""
    for prefix in prefixes:
        share = os.path.join(prefix, 'share')
        seen: Set[str] = set()
        names: List[str] = sorted(os.listdir(share)) if os.path.isdir(share) else []
        for name in names:
            dsv = os.path.join(share, name, 'package.dsv')
            if os.path.isfile(dsv):
                apply_dsv(env, prefix, dsv, seen)
        # Not every package.dsv carries the ament_prefix_path hook (e.g. ament_python
        # with --symlink-install), but `ros2 run/launch` need the ament index.
        _prepend(env, 'AMENT_PREFIX_PATH', prefix)


def child_env(base: Mapping[str, str], unsourced_prefixes: Iterable[str] = ()) -> Dict[str, str]:
    env = dict(base)
    overlay_prefixes(env, unsourced_prefixes)
    env.update(LOG_ENV)
    return env
