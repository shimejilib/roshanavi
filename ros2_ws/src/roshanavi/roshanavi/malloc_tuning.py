"""Cap glibc's malloc arenas for the server process.

glibc gives every thread that mallocs its own arena (up to 8 x cores). The server runs a
web-server thread pool, the rclpy executor and the sampler threads; the memory one thread frees
cannot be reused by a thread that sits on another arena, and a non-main arena shrinks only from
its top. Under node / viewer / echo churn the resident size therefore ratchets up in steps and
never comes back (measured: 500 class-node create/delete cycles +10 MB with the default, +1.5 MB
with two arenas; docs/design/resources.md, メモリの増え方). Two arenas keep the threads' blocks
in a pool the allocator can reuse; the lock contention it adds is invisible next to the GIL.

``MALLOC_ARENA_MAX`` set by the user (or the Docker image) always wins.
"""

import ctypes
import ctypes.util
import logging
import os
from typing import Any, Mapping, Optional

LOG = logging.getLogger(__name__)

M_ARENA_MAX = -8  # <malloc.h>
DEFAULT_ARENAS = 2
ENV_VAR = 'MALLOC_ARENA_MAX'


def _load_libc() -> Optional[Any]:
    try:
        return ctypes.CDLL(ctypes.util.find_library('c') or 'libc.so.6')
    except OSError:
        return None


def limit_malloc_arenas(count: int = DEFAULT_ARENAS, libc: Optional[Any] = None,
                        environ: Optional[Mapping[str, str]] = None) -> bool:
    """Call ``mallopt(M_ARENA_MAX, count)``; True when it was applied.

    Must run before the server starts its threads (the first line of ``main``). No-op when the
    user already set ``MALLOC_ARENA_MAX`` or the C library is not glibc.
    """
    env = os.environ if environ is None else environ
    if env.get(ENV_VAR):
        return False
    lib = libc if libc is not None else _load_libc()
    mallopt = getattr(lib, 'mallopt', None)
    if mallopt is None:
        return False
    try:
        applied = mallopt(M_ARENA_MAX, int(count)) == 1  # mallopt returns 1 on success
    except (OSError, ctypes.ArgumentError) as exc:
        LOG.debug('mallopt(M_ARENA_MAX) failed: %s', exc)
        return False
    return applied
