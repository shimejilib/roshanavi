"""The 1 Hz resource sampler (own thread) and the snapshots the API reads.

Runs off the asyncio loop and off the rclpy executor: one daemon thread samples, builds
an immutable snapshot and swaps it in under a lock; API handlers only copy references.
The thread measures its own CPU time (``sampler.cpu_pct``) so the observer effect is
visible next to roshanavi's other processes.
"""

import logging
import os
import socket
import threading
import time
from collections import deque
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Deque, Dict, List, Mapping, Optional, Sequence, Tuple

from ..media.diskguard import DiskGuard
from ..process_map import NodeMapping
from .attribution import (GROUP_OTHER, GROUP_ROS, GROUP_SELF, Attribution, NodeAttr, SelfPids,
                          attribute)
from .connections import ConnectionTracker, ReverseDns, SocketCollector, conn_dict
from .diagnose import diagnose
from .gpu import GpuReader
from .host import HostSampler
from .leak import LeakConfig, LeakDetector
from .procs import ProcessTable, ProcRow
from .summary import breakdown, node_dict, other_list, process_dict

LOG = logging.getLogger(__name__)

PERIOD_SEC = 1.0
HISTORY_POINTS = 300  # 5 min at 1 Hz
COST_WINDOW = 10
LIVE_FIELDS = ('cpu_pct', 'cpu_norm_pct', 'rss', 'confidence', 'shared', 'scope', 'pid')


@dataclass(frozen=True)
class ResourceContext:
    """What the rest of roshanavi knows, read once per sample."""
    nodes: Tuple[str, ...] = ()
    launcher: Mapping[str, NodeMapping] = field(default_factory=dict)
    targets: Tuple[Tuple[str, float, Optional[int]], ...] = ()
    roles: Mapping[str, str] = field(default_factory=dict)
    own: SelfPids = field(default_factory=lambda: SelfPids(server=os.getpid()))
    traffic: Callable[[], Sequence[Mapping[str, Any]]] = lambda: ()  # read only when needed
    recording: bool = False


class _History:
    FIELDS = ('t', 'cpu_pct', 'rss', 'read_bps', 'write_bps', 'gpu_mem', 'connections')

    def __init__(self, points: int):
        self._points = points
        self._series: Dict[str, Tuple[Tuple[int, ...], Deque[Tuple[Any, ...]]]] = {}

    def add(self, key: str, pids: Tuple[int, ...], values: Mapping[str, Any], t: float) -> None:
        current = self._series.get(key)
        if current is None or current[0] != pids:  # restarted: a new process, a new series
            current = self._series[key] = (pids, deque(maxlen=self._points))
        current[1].append(tuple([t, *(values.get(f) for f in self.FIELDS[1:])]))

    def retain(self, keys: Sequence[str]) -> None:
        keep = set(keys)
        for key in [k for k in self._series if k not in keep]:
            del self._series[key]

    def get(self, key: str) -> Optional[Dict[str, Any]]:
        current = self._series.get(key)
        if current is None:
            return None
        rows = list(current[1])
        return {'pids': list(current[0]),
                **{f: [r[i] for r in rows] for i, f in enumerate(self.FIELDS)}}


class ResourceService:
    def __init__(self, context: Callable[[], ResourceContext], data_dir: str,
                 guard: Optional[DiskGuard] = None, period_sec: float = PERIOD_SEC,
                 clock: Callable[[], float] = time.monotonic,
                 wall: Callable[[], float] = time.time,
                 table: Optional[ProcessTable] = None, host: Optional[HostSampler] = None,
                 gpu: Optional[GpuReader] = None, rdns: Optional[ReverseDns] = None,
                 leak_config: LeakConfig = LeakConfig(), proc_root: str = '/proc',
                 history_points: int = HISTORY_POINTS, reverse_dns: bool = True,
                 enabled: bool = True):
        self._context = context
        self._period = period_sec
        self._clock, self._wall = clock, wall
        self._table = table or ProcessTable(root=proc_root)
        self._host = host or HostSampler(data_dir, guard or DiskGuard(data_dir))
        self._gpu_reader = gpu
        self._rdns = rdns
        self._reverse_dns = reverse_dns
        self._leak = LeakDetector(leak_config)
        self._gpu_leak = LeakDetector(leak_config)
        self._tracker = ConnectionTracker()
        self._history = _History(history_points)
        self._sockets = SocketCollector(proc_root)
        self._lock = threading.Lock()
        self.enabled = enabled
        self._snapshot: Dict[str, Any] = {'available': False,
                                          'reason': 'starting' if enabled else 'off'}
        self._attr = Attribution()
        self._costs: Deque[Tuple[float, float]] = deque(maxlen=COST_WINDOW)
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.ticks = 0

    # ---- lifecycle -------------------------------------------------------------------------
    def start(self) -> 'ResourceService':
        if not self.enabled:
            return self
        if self._gpu_reader is None:
            self._gpu_reader = GpuReader()
        if self._rdns is None:
            self._rdns = ReverseDns(enabled=self._reverse_dns)
        self._thread = threading.Thread(target=self._run, name='resources', daemon=True)
        self._thread.start()
        return self

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5.0)
            self._thread = None
        if self._rdns is not None:
            self._rdns.close()
        if self._gpu_reader is not None:
            self._gpu_reader.close()

    def _run(self) -> None:
        deadline = self._clock()
        while not self._stop.is_set():
            try:
                self.tick()
            except Exception:  # keep sampling; a crash would silently freeze every number
                LOG.exception('resource sampling failed')
            deadline += self._period
            delay = deadline - self._clock()
            if delay < 0:  # fell behind (busy machine): skip, do not burst
                deadline, delay = self._clock(), 0.0
            self._stop.wait(delay)

    # ---- one sample ------------------------------------------------------------------------
    def _ctx(self) -> ResourceContext:
        try:
            return self._context()
        except Exception:
            LOG.exception('resource context failed')
            return ResourceContext()

    def tick(self) -> Dict[str, Any]:
        cost0 = time.thread_time()
        now, wall = self._clock(), self._wall()
        ctx = self._ctx()
        rows = self._table.scan(now)
        attr = attribute(rows, ctx.nodes, ctx.launcher, ctx.targets, ctx.roles, ctx.own)
        tracked = [pid for pid in rows if attr.group_of(pid) != GROUP_OTHER]
        sockets = self._sockets.collect(tracked, now)
        gpu = self._gpu_reader.read() if self._gpu_reader else {'available': False,
                                                                 'reason': 'off', 'procs': {}}
        host = self._host.sample(now)
        ncpu = self._host.ncpu
        procs: Dict[int, Dict[str, Any]] = {}
        for pid in tracked:
            row = self._table.detail(rows[pid], now)
            socks = sockets.get(pid)
            if socks is not None:
                row = replace(row, fds=socks.fds)
            procs[pid] = self._proc_entry(row, attr, ncpu, now, wall, socks, gpu)
        self._leak.retain(rows[p].key for p in tracked)
        self._gpu_leak.retain(rows[p].key for p in tracked)
        nodes = {n: node_dict(a, procs) for n, a in attr.nodes.items()}
        conns = [c for pid in tracked for c in (sockets[pid].conns if pid in sockets else ())]
        self._tracker.update(conns, wall, lambda pid: _conn_label(procs.get(pid)), self._rdns)
        others = [process_dict(r, attr, ncpu, {}) for r in other_list(rows, attr, ncpu)]
        snapshot = self._build(now, wall, ctx, rows, attr, procs, nodes, others, host, gpu, ncpu)
        self._record_history(wall, nodes, procs, host)
        cost = time.thread_time() - cost0
        self._costs.append((now, cost))
        snapshot['sampler'] = self._cost(len(rows), cost)
        with self._lock:
            self._snapshot, self._attr = snapshot, attr
        self.ticks += 1
        return snapshot

    def _proc_entry(self, row: ProcRow, attr: Attribution, ncpu: int, now: float, wall: float,
                    socks: Any, gpu: Mapping[str, Any]) -> Dict[str, Any]:
        first_seen = now - max(0.0, wall - row.create_time)  # warm-up counts from start-up
        leak = self._leak.observe(row.key, now, row.rss, first_seen)
        gpu_mem = gpu.get('procs', {}).get(row.pid)
        gpu_leak = (self._gpu_leak.observe(row.key, now, gpu_mem, first_seen)
                    if gpu_mem is not None else None)
        conns = [conn_dict(c, self._rdns) for c in socks.conns] if socks else []
        return process_dict(row, attr, ncpu, {
            'gpu_mem': gpu_mem, 'leak': leak.to_dict(),
            'gpu_leak': gpu_leak.to_dict() if gpu_leak else None, 'connections': conns,
            'udp_sockets': socks.udp_open if socks else None,
            'listening': socks.listening if socks else None})

    def _build(self, now: float, wall: float, ctx: ResourceContext, rows: Mapping[int, ProcRow],
               attr: Attribution, procs: Mapping[int, Dict[str, Any]],
               nodes: Mapping[str, Dict[str, Any]], others: List[Dict[str, Any]],
               host: Dict[str, Any], gpu: Dict[str, Any], ncpu: int) -> Dict[str, Any]:
        mem_used = host['mem'].get('used')
        listed = list(procs.values())
        diags = diagnose(listed, host.get('disk'), ctx.recording, host.get('udp'), ctx.traffic)
        connections = [{**c, **_conn_label(p)} for p in listed for c in p['connections']]
        return {
            'available': True, 'scope': 'this_host', 'hostname': socket.gethostname(),
            'ncpu': ncpu, 'own_user_only': not self._table.see_all, 'sampled_at': wall,
            'period_sec': self._period,
            'host': {**host, 'gpu': {k: v for k, v in gpu.items() if k != 'procs'}},
            'breakdown': breakdown(rows, attr, ncpu, host['cpu'].get('total_pct'), mem_used),
            'processes': sorted(listed, key=_proc_order),
            'others': others, 'nodes': dict(nodes), 'connections': connections,
            'events': list(self._tracker.events)[-100:], 'diagnostics': diags,
        }

    def _record_history(self, wall: float, nodes: Mapping[str, Dict[str, Any]],
                        procs: Mapping[int, Dict[str, Any]], host: Mapping[str, Any]) -> None:
        for node, info in nodes.items():
            self._history.add('node:' + node, tuple(info['pids']), info, wall)
        own = [p for p in procs.values() if p['group'] == GROUP_SELF]
        self._history.add('self', (), {
            'cpu_pct': sum(p['cpu_pct'] or 0.0 for p in own),
            'rss': sum(p['rss'] for p in own)}, wall)
        self._history.add('host', (), {'cpu_pct': host['cpu'].get('total_pct'),
                                       'rss': host['mem'].get('used')}, wall)
        self._history.retain(['self', 'host', *('node:' + n for n in nodes)])

    def _cost(self, n_procs: int, last: float) -> Dict[str, Any]:
        costs = list(self._costs)
        span = costs[-1][0] - costs[0][0] if len(costs) > 1 else 0.0
        used = sum(c for _, c in costs[1:]) if len(costs) > 1 else 0.0
        return {'cpu_pct': round(used / span * 100.0, 2) if span > 0 else None,
                'last_ms': round(last * 1000.0, 2), 'processes': n_procs}

    # ---- readers ---------------------------------------------------------------------------
    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            return self._snapshot

    def live(self) -> Dict[str, Any]:
        """Compact per-node figures for ``/ws/live`` (map badges, diagnostics)."""
        snap = self.snapshot()
        if not snap.get('available'):
            return {'available': False, 'nodes': {}, 'diagnostics': []}
        own = [p for p in snap['processes'] if p['group'] == GROUP_SELF]
        return {'available': True,
                'nodes': {n: {k: v.get(k) for k in (*LIVE_FIELDS, 'leak')}
                          for n, v in snap['nodes'].items()},
                'host': {'cpu_pct': snap['host']['cpu'].get('total_pct'),
                         'mem_pct': snap['host']['mem'].get('pct')},
                'self': {'cpu_pct': round(sum(p['cpu_pct'] or 0.0 for p in own), 1),
                         'rss': sum(p['rss'] for p in own)},
                'sampler': snap.get('sampler'), 'diagnostics': snap['diagnostics']}

    def history(self, node: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """``node`` = a node id, or None for roshanavi itself; ``'host'`` via :meth:`host_history`."""
        return self._history.get('node:' + node if node else 'self')

    def host_history(self) -> Optional[Dict[str, Any]]:
        return self._history.get('host')

    def resolve(self, node: str) -> Optional[NodeAttr]:
        with self._lock:
            return self._attr.nodes.get(node)


def _proc_order(proc: Mapping[str, Any]) -> Tuple[bool, bool, float]:
    return (proc['group'] != GROUP_ROS, proc['group'] != GROUP_SELF, -(proc['cpu_pct'] or 0.0))


def _conn_label(proc: Optional[Mapping[str, Any]]) -> Dict[str, Any]:
    if not proc:
        return {'group': None, 'label': None, 'name': None, 'nodes': []}
    return {'group': proc['group'], 'label': proc['label'], 'name': proc['name'],
            'nodes': proc['nodes']}
