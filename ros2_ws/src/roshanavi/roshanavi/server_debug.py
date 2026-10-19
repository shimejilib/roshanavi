"""Memory diagnostics route, only with ROSHANAVI_DEBUG_TRACEMALLOC=1 or =route (off by default).

Used to tell a real Python-level leak (``tracemalloc`` current bytes keep growing) from allocator
retention (RSS grows or stays high while ``tracemalloc`` is flat; ``trim=1`` calls glibc
``malloc_trim`` and shows how much RSS was only fragmentation). See docs/design/resources.md,
section on memory growth, and scripts/churn_harness.py (the reproducible load that drives it).

``GET /api/_debug/memory?top=15&objects=0&trim=0&snapshot=0&collect=0&find=Name`` returns the
process memory and the ``tracemalloc`` totals (cheap), plus on request:

* ``snapshot=1``: a tracemalloc snapshot (slow, a few seconds, extra memory) and the allocation
  sites that grew most since the previous snapshot call;
* ``objects=1``: the most numerous live object types;
* ``collect=1``: a full ``gc.collect()`` first (garbage that only waited for a collection vs.
  objects that are still referenced);
* ``find=Name``: how many live objects have a type name containing ``Name`` and which types hold
  the newest one (the retention path);
* ``trim=1``: ``malloc_trim``, to see how much RSS was only freed-but-kept memory.

The Host / Origin middleware covers it like every other route. Nothing is registered, and
``tracemalloc`` is not started, without the environment variable (``start_if_enabled`` is called
first thing in ``main``). ``ROSHANAVI_DEBUG_TRACEMALLOC=route`` registers the route without
starting ``tracemalloc`` (RSS and ``trim=1`` without the tracing overhead).
"""

import ctypes
import gc
import os
import sys
import threading
import time
import tracemalloc
from collections import Counter
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, Query

ENV_VAR = 'ROSHANAVI_DEBUG_TRACEMALLOC'
TRACE_FRAMES = 8
MAX_TOP = 100
ROUTE_ONLY = 'route'


def enabled() -> bool:
    """``1``: route + tracemalloc; ``route``: the route only (no tracing cost)."""
    return os.environ.get(ENV_VAR) in ('1', ROUTE_ONLY)


def start_if_enabled() -> bool:
    """Start tracemalloc before any other allocation (call at the top of ``main``)."""
    if os.environ.get(ENV_VAR) != '1':
        return False
    if not tracemalloc.is_tracing():
        tracemalloc.start(TRACE_FRAMES)
    return True


def _status_kib(field: str) -> Optional[int]:
    try:
        with open('/proc/self/status', encoding='ascii') as handle:
            for line in handle:
                if line.startswith(field + ':'):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return None


def _malloc_trim() -> bool:
    try:
        return bool(ctypes.CDLL('libc.so.6').malloc_trim(0))
    except (OSError, AttributeError):
        return False


class _State:
    """The previous snapshot the next call diffs against."""

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.snapshot: Optional[tracemalloc.Snapshot] = None


def _site(stat: Any) -> Dict[str, Any]:
    frame = stat.traceback[0]
    return {'where': f'{frame.filename}:{frame.lineno}', 'size_kib': round(stat.size / 1024, 1),
            'count': stat.count, 'size_diff_kib': round(stat.size_diff / 1024, 1),
            'count_diff': stat.count_diff}


def _object_counts(top: int) -> List[Dict[str, Any]]:
    counts = Counter(type(obj).__name__ for obj in gc.get_objects())
    return [{'type': name, 'count': n} for name, n in counts.most_common(top)]


def _describe(obj: Any) -> str:
    text = type(obj).__name__
    if isinstance(obj, dict):
        text += '{' + ','.join(str(k) for k in list(obj)[:4]) + '}'
    return text


def find_objects(fragment: str, depth: int = 2) -> Dict[str, Any]:
    """Live (gc-tracked) objects whose type name contains ``fragment``, and what holds the
    newest one: the chain of referrers' types up to ``depth`` levels (the retention path)."""
    found = [o for o in gc.get_objects() if fragment in type(o).__name__]
    chain: List[List[str]] = []
    if found:
        level: List[Any] = [found[-1]]
        seen = {id(found), id(level)}
        for _ in range(depth):
            nxt = [r for o in level for r in gc.get_referrers(o) if id(r) not in seen]
            seen.update(id(r) for r in nxt)
            seen.add(id(nxt))
            chain.append(sorted({_describe(r) for r in nxt})[:12])
            level = [r for r in nxt if not isinstance(r, type(sys._getframe()))]
    return {'fragment': fragment, 'count': len(found), 'referrers': chain}


def memory_report(state: _State, top: int, objects: bool, trim: bool,
                  snapshot: bool = False, find: Optional[str] = None,
                  collect: bool = False) -> Dict[str, Any]:
    with state.lock:
        before_collect = len(gc.get_objects()) if collect else None
        started = time.perf_counter()
        collected = gc.collect() if collect else None
        collect_ms = round((time.perf_counter() - started) * 1000, 1) if collect else None
        before_trim = _status_kib('VmRSS')
        trimmed = _malloc_trim() if trim else None
        current, peak = tracemalloc.get_traced_memory() if tracemalloc.is_tracing() else (0, 0)
        diff: List[Dict[str, Any]] = []
        if snapshot and tracemalloc.is_tracing():
            snap = tracemalloc.take_snapshot().filter_traces((
                tracemalloc.Filter(False, tracemalloc.__file__),
                tracemalloc.Filter(False, __file__)))
            if state.snapshot is not None:
                diff = [_site(s) for s in snap.compare_to(state.snapshot, 'lineno')[:top]]
            state.snapshot = snap
        return {
            'rss_kib': _status_kib('VmRSS'), 'rss_before_trim_kib': before_trim,
            'hwm_kib': _status_kib('VmHWM'), 'trimmed': trimmed,
            'tracemalloc': {'tracing': tracemalloc.is_tracing(), 'current_kib': current // 1024,
                            'peak_kib': peak // 1024},
            'collected': collected, 'collect_ms': collect_ms,
            'gc_objects_before_collect': before_collect,
            'gc_objects': len(gc.get_objects()), 'threads': threading.active_count(),
            'fds': len(os.listdir('/proc/self/fd')), 'diff': diff,
            'objects': _object_counts(top) if objects else None,
            'found': find_objects(find) if find else None}


def register(app: FastAPI) -> bool:
    """Add the route when the environment variable is set; returns whether it did."""
    if not enabled():
        return False
    state = _State()

    @app.get('/api/_debug/memory')
    def get_memory(top: int = Query(15, ge=1, le=MAX_TOP), objects: bool = False,
                   trim: bool = False, snapshot: bool = False,
                   find: Optional[str] = Query(None, max_length=64),
                   collect: bool = False) -> Dict[str, Any]:
        return memory_report(state, top, objects, trim, snapshot, find, collect)
    return True
