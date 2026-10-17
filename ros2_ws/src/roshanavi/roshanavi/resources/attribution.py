"""Which process is which: ROS node <-> process, and ROS / roshanavi / other groups (pure).

Inputs are one :class:`ProcessTable` scan plus what the Launcher already knows
(:mod:`roshanavi.process_map`), so no extra system calls happen here.

Node -> process (docs/design/resources.md#前提), first match wins:
1. **launcher, exact**: :class:`~roshanavi.process_map.NodeProcessMapper` found
   ``__node:=`` inside a Launcher target's process tree.
2. **cmdline** (heuristic, 推定): any visible process whose argv carries
   ``__node:=<name>`` / ``__ns:=`` for that node; the deepest one wins (the program, not
   the ``ros2 run`` wrapper). It comes before the Launcher's timing heuristic, which can
   pin a node started elsewhere at the same moment on the wrong target.
3. **launcher, heuristic** (推定): the Launcher's guess (first seen right after a target
   started). When it knows the target but not the process, the whole target tree is used.
4. **exe** (heuristic, 推定): exactly one unclaimed process whose program name equals the
   node's base name (``demo_nodes_cpp talker`` -> ``/talker``).
- Several nodes in one process (composable container, multi-node executables) share that
  process: each node lists the others in ``shared`` and shows the process total.

Process groups:
- ``ros``: the trees of Launcher targets with role mine / dependency, and any other
  process hosting a mapped node (the scenario's setup processes, nodes started elsewhere);
- ``self`` (roshanavi itself): the server, the measurement probe, the tracing worker and
  LTTng daemons, the recorder, the build, roshanavi-made nodes (input / transform /
  function) and every other descendant of the server;
- ``other``: everything else that is visible.
"""

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ..process_map import CONFIDENCE_EXACT, CONFIDENCE_HEURISTIC, NodeMapping, ros_identity
from .procs import ProcRow, children_map, descendants

GROUP_ROS = 'ros'
GROUP_SELF = 'self'
GROUP_OTHER = 'other'
SELF_CHILD_ROLES = ('dummy', 'transform', 'function')

# Labels of roshanavi's own processes (the UI translates them).
SELF_SERVER = 'server'
SELF_PROBE = 'probe'
SELF_TRACING = 'tracing'
SELF_LTTNG = 'lttng'
SELF_RECORDER = 'recorder'
SELF_BUILD = 'build'
SELF_CHILD_NODES = 'child_nodes'
SELF_HELPER = 'helper'

SOURCE_LAUNCHER = 'launcher'
SOURCE_CMDLINE = 'cmdline'
SOURCE_EXE = 'exe'


@dataclass(frozen=True)
class NodeAttr:
    node: str
    pids: Tuple[int, ...]  # usually one; a whole target tree when only the target is known
    confidence: str
    source: str
    target_id: Optional[str] = None
    shared: Tuple[str, ...] = ()

    @property
    def pid(self) -> Optional[int]:
        return self.pids[0] if len(self.pids) == 1 else None

    def to_dict(self) -> Dict[str, object]:
        return {'pid': self.pid, 'pids': list(self.pids), 'confidence': self.confidence,
                'source': self.source, 'target_id': self.target_id, 'shared': list(self.shared)}


@dataclass(frozen=True)
class ProcRole:
    group: str
    label: str  # target id, a SELF_* label, or the process name
    role: Optional[str] = None  # the target's role (mine / dependency / dummy ...)
    target_id: Optional[str] = None
    nodes: Tuple[str, ...] = ()


@dataclass(frozen=True)
class SelfPids:
    """roshanavi's own processes the caller knows by pid (None = not running)."""
    server: int
    probe: Optional[int] = None
    tracing: Optional[int] = None
    recorder: Optional[int] = None
    lttng_names: Tuple[str, ...] = ()  # LTTng daemon names while tracing is on


@dataclass
class Attribution:
    nodes: Dict[str, NodeAttr] = field(default_factory=dict)
    procs: Dict[int, ProcRole] = field(default_factory=dict)

    def group_of(self, pid: int) -> str:
        role = self.procs.get(pid)
        return role.group if role else GROUP_OTHER


def deepest(rows: Mapping[int, ProcRow], pids: Sequence[int]) -> int:
    """The match that is not an ancestor of another match (the program, not a wrapper)."""
    candidates = set(pids)
    for pid in pids:
        parent = rows[pid].ppid
        seen = set()
        while parent in rows and parent not in seen:
            seen.add(parent)
            candidates.discard(parent)
            parent = rows[parent].ppid
    return min(candidates) if candidates else pids[0]


def _assign_targets(rows: Mapping[int, ProcRow], kids: Dict[int, Tuple[int, ...]],
                    targets: Iterable[Tuple[str, float, Optional[int]]],
                    roles: Mapping[str, str], out: Dict[int, ProcRole]
                    ) -> Dict[str, Tuple[int, ...]]:
    trees: Dict[str, Tuple[int, ...]] = {}
    for target_id, _started, root in targets:
        if not root:
            continue
        tree = descendants(rows, root, kids)
        trees[target_id] = tree
        role = roles.get(target_id)
        group, label = ((GROUP_SELF, SELF_CHILD_NODES) if role in SELF_CHILD_ROLES
                        else (GROUP_ROS, target_id))
        for pid in tree:
            out.setdefault(pid, ProcRole(group, label, role, target_id))
    return trees


def _launches_roshanavi(row: ProcRow) -> bool:
    """The ``ros2 run roshanavi server`` wrapper above the server process."""
    return row.exe_name == 'ros2' and 'roshanavi' in row.cmdline[:6]


def _assign_self(rows: Mapping[int, ProcRow], kids: Dict[int, Tuple[int, ...]],
                 own: SelfPids, out: Dict[int, ProcRole]) -> None:
    named = ((own.server, SELF_SERVER), (own.probe, SELF_PROBE), (own.tracing, SELF_TRACING),
             (own.recorder, SELF_RECORDER))
    parent = rows[own.server].ppid if own.server in rows else 0
    while parent in rows and _launches_roshanavi(rows[parent]):  # `ros2 run roshanavi server`
        out.setdefault(parent, ProcRole(GROUP_SELF, SELF_SERVER))
        parent = rows[parent].ppid
    for pid, label in named:
        if pid and pid in rows:
            for member in descendants(rows, pid, kids) if label != SELF_SERVER else (pid,):
                out.setdefault(member, ProcRole(GROUP_SELF, label))
    for row in rows.values():
        if row.name in own.lttng_names:
            out.setdefault(row.pid, ProcRole(GROUP_SELF, SELF_LTTNG))
    for pid in descendants(rows, own.server, kids)[1:]:
        if pid in out:
            continue
        row = rows[pid]
        if ros_identity(row.cmdline):
            out[pid] = ProcRole(GROUP_ROS, ros_identity(row.cmdline) or row.name)
        elif 'colcon' in row.name or any('colcon' in a for a in row.cmdline[:2]):
            out[pid] = ProcRole(GROUP_SELF, SELF_BUILD)
        else:
            out[pid] = ProcRole(GROUP_SELF, SELF_HELPER)


def _launcher_nodes(rows: Mapping[int, ProcRow], nodes: Sequence[str],
                    launcher: Mapping[str, NodeMapping], trees: Mapping[str, Tuple[int, ...]],
                    found: Dict[str, NodeAttr], exact: bool) -> None:
    """Launcher mappings of one confidence (exact first; its heuristic only after cmdline)."""
    for node in nodes:
        mapping = launcher.get(node)
        if node in found or mapping is None or (mapping.confidence == CONFIDENCE_EXACT) != exact:
            continue
        if mapping.pid is not None and mapping.pid in rows:
            found[node] = NodeAttr(node, (mapping.pid,), mapping.confidence, SOURCE_LAUNCHER,
                                   mapping.target_id)
        elif trees.get(mapping.target_id):
            found[node] = NodeAttr(node, trees[mapping.target_id], CONFIDENCE_HEURISTIC,
                                   SOURCE_LAUNCHER, mapping.target_id)


def _cmdline_nodes(rows: Mapping[int, ProcRow], nodes: Sequence[str], found: Dict[str, NodeAttr],
                   procs: Dict[int, ProcRole]) -> None:
    """``__node:=`` in argv. Beats the Launcher's timing heuristic: a node that a scenario or
    a terminal started right after a target (re)start must not be pinned on that target."""
    by_identity: Dict[str, List[int]] = {}
    for row in rows.values():
        identity = ros_identity(row.cmdline)
        if identity:
            by_identity.setdefault(identity, []).append(row.pid)
    for node in nodes:
        if node not in found and node in by_identity:
            program = deepest(rows, by_identity[node])
            found[node] = NodeAttr(node, (program,), CONFIDENCE_HEURISTIC, SOURCE_CMDLINE)
            for pid in by_identity[node]:  # the ``ros2 run`` wrapper belongs to the node too
                if pid != program and pid not in procs:
                    procs[pid] = ProcRole(GROUP_ROS, node)


def _exe_nodes(rows: Mapping[int, ProcRow], nodes: Sequence[str], found: Dict[str, NodeAttr],
               procs: Mapping[int, ProcRole]) -> None:
    claimed = {pid for attr in found.values() for pid in attr.pids}
    by_exe: Dict[str, List[int]] = {}
    for row in rows.values():
        role = procs.get(row.pid)
        if row.pid in claimed or (role is not None and role.group == GROUP_SELF
                                  and role.label != SELF_HELPER):
            continue
        by_exe.setdefault(row.exe_name, []).append(row.pid)
    for node in nodes:
        base = node.rsplit('/', 1)[-1]
        if node not in found and len(by_exe.get(base, ())) == 1:
            found[node] = NodeAttr(node, (by_exe[base][0],), CONFIDENCE_HEURISTIC, SOURCE_EXE)


def _mark_shared(found: Dict[str, NodeAttr]) -> Dict[str, NodeAttr]:
    by_pid: Dict[Tuple[int, ...], List[str]] = {}
    for node, attr in found.items():
        by_pid.setdefault(attr.pids, []).append(node)
    out: Dict[str, NodeAttr] = {}
    for node, attr in found.items():
        others = tuple(sorted(n for n in by_pid[attr.pids] if n != node))
        out[node] = NodeAttr(attr.node, attr.pids, attr.confidence, attr.source,
                             attr.target_id, others)
    return out


def attribute(rows: Mapping[int, ProcRow], nodes: Sequence[str],
              launcher: Mapping[str, NodeMapping],
              targets: Iterable[Tuple[str, float, Optional[int]]],
              roles: Mapping[str, str], own: SelfPids) -> Attribution:
    kids = children_map(rows)
    procs: Dict[int, ProcRole] = {}
    trees = _assign_targets(rows, kids, targets, roles, procs)
    _assign_self(rows, kids, own, procs)
    found: Dict[str, NodeAttr] = {}
    _launcher_nodes(rows, nodes, launcher, trees, found, exact=True)
    _cmdline_nodes(rows, nodes, found, procs)
    _launcher_nodes(rows, nodes, launcher, trees, found, exact=False)
    _exe_nodes(rows, nodes, found, procs)
    found = _mark_shared(found)
    hosted: Dict[int, List[str]] = {}
    for node, attr in found.items():
        for pid in attr.pids:
            hosted.setdefault(pid, []).append(node)
    for pid, names in hosted.items():
        role = procs.get(pid)
        names_t = tuple(sorted(names))
        if role is None:
            row = rows.get(pid)
            procs[pid] = ProcRole(GROUP_ROS, row.name if row else str(pid), nodes=names_t)
        elif role.group == GROUP_SELF and role.label == SELF_HELPER:
            procs[pid] = ProcRole(GROUP_ROS, rows[pid].name, nodes=names_t)
        else:
            procs[pid] = ProcRole(role.group, role.label, role.role, role.target_id, names_t)
    return Attribution(nodes=found, procs=procs)


__all__ = ['Attribution', 'NodeAttr', 'ProcRole', 'SelfPids', 'attribute', 'CONFIDENCE_EXACT',
           'CONFIDENCE_HEURISTIC', 'GROUP_ROS', 'GROUP_SELF', 'GROUP_OTHER']
