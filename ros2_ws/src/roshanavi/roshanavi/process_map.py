"""Node <-> process mapping (reusable: Launcher roles now, CPU/memory per node later).

ROS 2 graph introspection does not say which process a node lives in, so we
infer it from the process trees of the processes *we* started:

1. **exact**: a process in the target's tree carries ``__node:=<name>`` (and
   optionally ``__ns:=<ns>``) in its argv. ``launch_ros`` adds these when a
   ``Node`` action has ``name=``/``namespace=``; the Launcher adds them when
   the user sets a node name. The deepest such process (the node executable,
   not the ``ros2 run`` wrapper) is reported as the node's pid.
2. **heuristic**: a node that first appeared within ``window_sec`` after a
   target (re)started, that no other target claims and that was not seen
   while none of our processes was running (the *baseline*). When several targets
   are candidates, the one with a process whose executable name equals the
   node name wins; otherwise the most recently started one.

Limits (documented in docs/design/launcher.md): composable nodes inside a container
map to the container process (per-container, not per-node); nodes in other
PID namespaces (other containers) or hosts are never mapped; a heuristic match
can be wrong when unrelated nodes start at the same moment.

The pure core is :func:`map_nodes`; :class:`NodeProcessMapper` adds the
stateful bits (first-seen times, baseline, sticky heuristic assignments).
"""

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

import psutil

CONFIDENCE_EXACT = 'exact'
CONFIDENCE_HEURISTIC = 'heuristic'
DEFAULT_WINDOW_SEC = 20.0
EARLY_SLACK_SEC = 0.5


@dataclass(frozen=True)
class ProcInfo:
    pid: int
    ppid: int
    depth: int  # 0 = the target's root process
    cmdline: Tuple[str, ...]

    @property
    def exe_name(self) -> str:
        """Basename of the program, skipping an interpreter (``python3 script``)."""
        for item in self.cmdline[:2]:
            base = os.path.basename(item)
            if base and not base.startswith('python'):
                return base
        return os.path.basename(self.cmdline[0]) if self.cmdline else ''


@dataclass(frozen=True)
class TargetProcs:
    target_id: str
    started_at: float  # monotonic seconds
    procs: Tuple[ProcInfo, ...] = ()


@dataclass(frozen=True)
class NodeMapping:
    node: str
    target_id: str
    pid: Optional[int]
    confidence: str

    def to_dict(self) -> Dict[str, object]:
        return {'node': self.node, 'target_id': self.target_id, 'pid': self.pid,
                'confidence': self.confidence}


def fq_node(name: str, namespace: str) -> str:
    namespace = namespace or '/'
    if not namespace.startswith('/'):
        namespace = '/' + namespace
    return f'{namespace.rstrip("/")}/{name}'


def _remap_value(item: str, key: str) -> Optional[str]:
    """Value of ``key:=v`` or node-specific ``nodename:key:=v``; None otherwise."""
    if ':=' not in item:
        return None
    lhs, value = item.split(':=', 1)
    if lhs == key or lhs.endswith(':' + key):
        return value or None
    return None


def ros_identity(cmdline: Sequence[str]) -> Optional[str]:
    """Fully qualified node name from ``__node:=`` / ``__ns:=`` argv items."""
    name = namespace = None
    for item in cmdline:
        name = _remap_value(item, '__node') or _remap_value(item, '__name') or name
        namespace = _remap_value(item, '__ns') or namespace
    return fq_node(name, namespace or '/') if name else None


def process_tree(root_pid: int) -> Tuple[ProcInfo, ...]:
    """The root process and all descendants, root first, ordered by depth."""
    try:
        root = psutil.Process(root_pid)
        procs = [root, *root.children(recursive=True)]
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return ()
    infos: List[ProcInfo] = []
    depth_of: Dict[int, int] = {root_pid: 0}
    for proc in procs:
        try:
            cmdline, ppid = tuple(proc.cmdline()), proc.ppid()
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
        depth = 0 if proc.pid == root_pid else depth_of.get(ppid, 0) + 1
        depth_of[proc.pid] = depth
        infos.append(ProcInfo(pid=proc.pid, ppid=ppid, depth=depth, cmdline=cmdline))
    return tuple(sorted(infos, key=lambda p: (p.depth, p.pid)))


def exact_claims(targets: Iterable[TargetProcs]) -> Dict[str, NodeMapping]:
    claims: Dict[str, NodeMapping] = {}
    for target in targets:
        for proc in target.procs:  # depth order: deeper processes override wrappers
            node = ros_identity(proc.cmdline)
            if node:
                claims[node] = NodeMapping(node, target.target_id, proc.pid, CONFIDENCE_EXACT)
    return claims


def _guess_pid(target: TargetProcs, node: str) -> Optional[int]:
    base = node.rsplit('/', 1)[-1]
    matches = [p for p in target.procs if p.exe_name == base]
    if matches:
        return matches[-1].pid
    leaves = [p for p in target.procs if not any(c.ppid == p.pid for c in target.procs)]
    return leaves[0].pid if len(leaves) == 1 else None


def _pick_target(node: str, first_seen: float, targets: Sequence[TargetProcs],
                 window_sec: float) -> Optional[TargetProcs]:
    candidates = [t for t in targets
                  if t.started_at - EARLY_SLACK_SEC <= first_seen <= t.started_at + window_sec]
    if len(candidates) <= 1:
        return candidates[0] if candidates else None
    base = node.rsplit('/', 1)[-1]
    named = [t for t in candidates if any(p.exe_name == base for p in t.procs)]
    pool = named or candidates
    return max(pool, key=lambda t: t.started_at)


def map_nodes(nodes: Iterable[str], targets: Sequence[TargetProcs],
              first_seen: Mapping[str, float], baseline: Set[str] = frozenset(),
              sticky: Mapping[str, NodeMapping] = None,
              window_sec: float = DEFAULT_WINDOW_SEC) -> Dict[str, NodeMapping]:
    """Pure mapping of graph node ids to targets (see module docstring)."""
    live = {t.target_id: t for t in targets if t.procs}
    exact = {n: m for n, m in exact_claims(live.values()).items()}
    result: Dict[str, NodeMapping] = {}
    for node in nodes:
        if node in exact:
            result[node] = exact[node]
            continue
        previous = (sticky or {}).get(node)
        if previous is not None and previous.target_id in live:
            result[node] = previous
            continue
        if node in baseline or node not in first_seen:
            continue
        target = _pick_target(node, first_seen[node], list(live.values()), window_sec)
        if target is not None:
            result[node] = NodeMapping(node, target.target_id, _guess_pid(target, node),
                                       CONFIDENCE_HEURISTIC)
    return result


@dataclass
class _State:
    first_seen: Dict[str, float] = field(default_factory=dict)
    baseline: Set[str] = field(default_factory=set)
    mapping: Dict[str, NodeMapping] = field(default_factory=dict)


class NodeProcessMapper:
    """Keeps first-seen times and sticky assignments between graph refreshes."""

    def __init__(self, window_sec: float = DEFAULT_WINDOW_SEC,
                 clock: Callable[[], float] = time.monotonic,
                 tree: Callable[[int], Tuple[ProcInfo, ...]] = process_tree):
        self._window = window_sec
        self._clock = clock
        self._tree = tree
        self._lock = threading.Lock()
        self._state = _State()

    def update(self, nodes: Iterable[str],
               targets: Iterable[Tuple[str, float, Optional[int]]]) -> Dict[str, NodeMapping]:
        """``targets``: (target_id, started_at monotonic, root pid or None)."""
        now = self._clock()
        nodes = list(nodes)
        procs = [TargetProcs(tid, started, self._tree(pid) if pid else ())
                 for tid, started, pid in targets]
        with self._lock:
            state = self._state
            first_seen = {n: state.first_seen.get(n, now) for n in nodes}
            # Nodes seen while none of our processes runs cannot be ours; entries
            # are dropped when the node vanishes so a later restart can map it.
            idle = not any(t.procs for t in procs)
            baseline = {n for n in nodes if idle or n in (state.baseline or ())}
            mapping = map_nodes(nodes, procs, first_seen, baseline, state.mapping, self._window)
            self._state = _State(first_seen=first_seen, baseline=baseline, mapping=mapping)
        return mapping

    def mapping(self) -> Dict[str, NodeMapping]:
        with self._lock:
            return dict(self._state.mapping)
