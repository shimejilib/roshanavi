"""Turn one sample (process rows + attribution) into the JSON the API serves (pure).

CPU units: ``cpu_pct`` is per process like ``top`` (100 = one core); ``cpu_norm_pct`` and
every whole-PC figure are shares of all cores (100 = the whole machine).
"""

from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .attribution import GROUP_OTHER, GROUP_ROS, GROUP_SELF, Attribution, NodeAttr
from .procs import ProcRow

TOP_N = 5
OTHER_LIST = 10


def _r(value: Optional[float], digits: int = 1) -> Optional[float]:
    return None if value is None else round(value, digits)


def process_dict(row: ProcRow, attr: Attribution, ncpu: int, extra: Mapping[str, Any]
                 ) -> Dict[str, Any]:
    role = attr.procs.get(row.pid)
    return {'pid': row.pid, 'ppid': row.ppid, 'name': row.name, 'exe': row.exe_name,
            'group': role.group if role else GROUP_OTHER,
            'label': role.label if role else row.name,
            'role': role.role if role else None, 'target_id': role.target_id if role else None,
            'nodes': list(role.nodes) if role else [],
            'cpu_pct': _r(row.cpu_pct), 'cpu_norm_pct': _r(None if row.cpu_pct is None
                                                           else row.cpu_pct / ncpu, 2),
            'rss': row.rss, 'uss': row.uss, 'threads': row.threads, 'fds': row.fds,
            'read_bps': _r(row.read_bps, 0), 'write_bps': _r(row.write_bps, 0),
            'started_at': row.create_time, **extra}


def _sum(values: Iterable[Optional[float]]) -> Optional[float]:
    found = [v for v in values if v is not None]
    return sum(found) if found else None


def node_dict(attr: NodeAttr, procs: Mapping[int, Mapping[str, Any]]) -> Dict[str, Any]:
    members = [procs[pid] for pid in attr.pids if pid in procs]
    single = members[0] if len(members) == 1 else None
    return {**attr.to_dict(), 'node': attr.node,
            'cpu_pct': _r(_sum(m['cpu_pct'] for m in members)),
            'cpu_norm_pct': _r(_sum(m['cpu_norm_pct'] for m in members), 2),
            'rss': _sum(m['rss'] for m in members), 'uss': _sum(m['uss'] for m in members),
            'threads': _sum(m['threads'] for m in members),
            'fds': _sum(m['fds'] for m in members),
            'read_bps': _sum(m['read_bps'] for m in members),
            'write_bps': _sum(m['write_bps'] for m in members),
            'gpu_mem': _sum(m.get('gpu_mem') for m in members),
            'connections': sum(len(m.get('connections') or ()) for m in members),
            'leak': single.get('leak') if single else None,
            'gpu_leak': single.get('gpu_leak') if single else None,
            'name': single['name'] if single else None,
            'scope': 'process' if single else 'target'}


def _top(rows: Sequence[ProcRow], ncpu: int, top_n: int) -> Tuple[List[Dict[str, Any]],
                                                                    List[Dict[str, Any]]]:
    by_name: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        item = by_name.setdefault(row.name, {'name': row.name, 'cpu_norm_pct': 0.0, 'rss': 0,
                                             'count': 0})
        item['cpu_norm_pct'] += (row.cpu_pct or 0.0) / ncpu
        item['rss'] += row.rss
        item['count'] += 1
    items = list(by_name.values())
    for item in items:
        item['cpu_norm_pct'] = round(item['cpu_norm_pct'], 2)
    by_cpu = sorted(items, key=lambda i: -i['cpu_norm_pct'])[:top_n]
    by_mem = sorted(items, key=lambda i: -i['rss'])[:top_n]
    return by_cpu, by_mem


def breakdown(rows: Mapping[int, ProcRow], attr: Attribution, ncpu: int,
              host_cpu_pct: Optional[float], mem_used: Optional[int],
              top_n: int = TOP_N) -> Dict[str, Any]:
    """Whole-PC CPU / memory split into ROS nodes / roshanavi itself / other."""
    groups: Dict[str, List[ProcRow]] = {GROUP_ROS: [], GROUP_SELF: [], GROUP_OTHER: []}
    for row in rows.values():
        groups[attr.group_of(row.pid)].append(row)

    def cpu(group: str) -> float:
        return sum((r.cpu_pct or 0.0) for r in groups[group]) / ncpu

    def mem(group: str) -> int:
        return sum(r.rss for r in groups[group])
    ros_cpu, self_cpu = cpu(GROUP_ROS), cpu(GROUP_SELF)
    top_cpu, top_mem = _top(groups[GROUP_OTHER], ncpu, top_n)
    other_cpu = None if host_cpu_pct is None else max(0.0, host_cpu_pct - ros_cpu - self_cpu)
    other_mem = None if mem_used is None else max(0, mem_used - mem(GROUP_ROS) - mem(GROUP_SELF))
    return {'cpu': {'ros': round(ros_cpu, 2), 'self': round(self_cpu, 2),
                    'other': _r(other_cpu, 2), 'total': host_cpu_pct, 'other_top': top_cpu},
            'mem': {'ros': mem(GROUP_ROS), 'self': mem(GROUP_SELF), 'other': other_mem,
                    'total': mem_used, 'other_top': top_mem},
            'counts': {g: len(v) for g, v in groups.items()}}


def other_list(rows: Mapping[int, ProcRow], attr: Attribution, ncpu: int,
               limit: int = OTHER_LIST) -> List[ProcRow]:
    others = [r for r in rows.values() if attr.group_of(r.pid) == GROUP_OTHER]
    return sorted(others, key=lambda r: (-(r.cpu_pct or 0.0), -r.rss))[:limit]
