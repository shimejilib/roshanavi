"""Measure one node's process for scenario steps (``resources`` / ``mem_growth``).

Works with the server (its attribution is passed as ``resolver``) and without it (the
CLI): then the node's process is found by its command line (``__node:=`` / ``__ns:=``,
the deepest match) or, failing that, a unique program name equal to the node's base
name. A process inside the scenario's own setup / target trees counts as ``exact``;
anything else is ``heuristic`` (推定). Read-only: only ``/proc`` is read.
"""

import os
import time
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import psutil

from ..process_map import CONFIDENCE_EXACT, CONFIDENCE_HEURISTIC, ros_identity
from .attribution import NodeAttr, deepest
from .procs import ProcRow, visible_all

RESOLVE_AGAIN_SEC = 2.0


@dataclass(frozen=True)
class NodeSample:
    t: float  # monotonic
    pids: Tuple[int, ...]
    cpu_seconds: float
    rss: int
    confidence: str


def _rows(see_all: bool, uid: int) -> Dict[int, ProcRow]:
    rows: Dict[int, ProcRow] = {}
    for proc in psutil.process_iter(['pid', 'ppid', 'name', 'uids', 'cmdline', 'create_time'],
                                    ad_value=None):
        info = proc.info
        uids = info.get('uids')
        if not see_all and (uids is None or uids[0] != uid):
            continue
        rows[info['pid']] = ProcRow(pid=info['pid'], ppid=info.get('ppid') or 0,
                                    name=info.get('name') or '',
                                    cmdline=tuple(info.get('cmdline') or ()),
                                    create_time=info.get('create_time') or 0.0,
                                    cpu_seconds=0.0, rss=0)
    return rows


def find_by_cmdline(rows: Dict[int, ProcRow], node: str) -> Optional[int]:
    matches = [pid for pid, row in rows.items() if ros_identity(row.cmdline) == node]
    if matches:
        return deepest(rows, matches)
    base = node.rsplit('/', 1)[-1]
    by_exe = [pid for pid, row in rows.items() if row.exe_name == base]
    return by_exe[0] if len(by_exe) == 1 else None


def _tree(roots: Iterable[int]) -> set:
    found = set()
    for root in roots:
        try:
            proc = psutil.Process(root)
            found.add(root)
            found.update(child.pid for child in proc.children(recursive=True))
        except psutil.Error:
            continue
    return found


class NodeProbe:
    def __init__(self, resolver: Optional[Callable[[str], Optional[NodeAttr]]] = None,
                 owned: Callable[[], Sequence[int]] = lambda: (),
                 clock: Callable[[], float] = time.monotonic, see_all: Optional[bool] = None):
        self._resolver = resolver
        self._owned = owned
        self._clock = clock
        self._see_all = visible_all() if see_all is None else see_all
        self._uid = os.getuid()
        self._found: Dict[str, Tuple[Tuple[int, ...], str, float]] = {}
        self._procs: Dict[int, psutil.Process] = {}

    def _resolve(self, node: str) -> Optional[Tuple[Tuple[int, ...], str]]:
        rows = _rows(self._see_all, self._uid)
        pid = find_by_cmdline(rows, node)
        owned = _tree(self._owned())
        if pid is not None and pid in owned:  # the scenario's own setup / target process
            return (pid,), CONFIDENCE_EXACT
        if self._resolver is not None:
            attr = self._resolver(node)
            if attr is not None and attr.pids:
                exact = attr.confidence == CONFIDENCE_EXACT or set(attr.pids) <= owned
                return attr.pids, CONFIDENCE_EXACT if exact else CONFIDENCE_HEURISTIC
        return None if pid is None else ((pid,), CONFIDENCE_HEURISTIC)

    def _process(self, pid: int) -> psutil.Process:
        proc = self._procs.get(pid)
        if proc is None or not proc.is_running():
            proc = self._procs[pid] = psutil.Process(pid)
        return proc

    def sample(self, node: str) -> Optional[NodeSample]:
        """Current cumulative CPU seconds and RSS of the node's process(es); None if not found."""
        now = self._clock()
        cached = self._found.get(node)
        if cached is None or now - cached[2] >= RESOLVE_AGAIN_SEC:
            resolved = self._resolve(node)
            if resolved is None:
                self._found.pop(node, None)
                return None
            cached = self._found[node] = (*resolved, now)
        pids, confidence, _ = cached
        cpu, rss, alive = 0.0, 0, []
        for pid in pids:
            try:
                proc = self._process(pid)
                with proc.oneshot():
                    times = proc.cpu_times()
                    cpu += times.user + times.system
                    rss += proc.memory_info().rss
                alive.append(pid)
            except psutil.Error:
                continue
        if not alive:
            self._found.pop(node, None)
            return None
        return NodeSample(now, tuple(alive), cpu, rss, confidence)


def segments(samples: Sequence[NodeSample]) -> List[List[NodeSample]]:
    """Split samples where the process changed (restart): CPU deltas only within one."""
    out: List[List[NodeSample]] = []
    for sample in samples:
        if out and out[-1][-1].pids == sample.pids:
            out[-1].append(sample)
        else:
            out.append([sample])
    return out
