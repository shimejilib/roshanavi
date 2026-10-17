"""Pure model of the trace: handles -> node / topic / callback, and windowed statistics.

Handles are pointers inside one process, so every key includes the vpid.
The init events build the chain
``rcl_node_init`` (node handle -> name) -> ``rcl_subscription_init``
(subscription -> node, rmw handle, topic) -> ``rclcpp_subscription_init``
(rcl subscription -> rclcpp subscription) -> ``rclcpp_subscription_callback_added``
(rclcpp subscription -> callback). Per-message events then count:

* ``rmw_take`` (successful takes only, filtered in LTTng) -> received,
* ``callback_start`` / ``callback_end`` paired per (vpid, vtid) -> processed + duration,
* ``rmw_publish`` -> sent (cross-check of the probe's per-publisher rates).

rclpy emits the rcl / rmw events but no callback events (Jazzy), so Python
subscriptions get a received count only (``lang: "py"``).
"""

import math
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from ..stats import window_rate

K_NODE, K_RCL_SUB, K_CPP_SUB, K_CB_ADDED, K_CB_REGISTER, K_RCL_PUB = range(6)
K_TAKE, K_CB_START, K_CB_END, K_PUBLISH = range(10, 14)
SYMBOL_MAX = 160
WINDOWS_SEC = (1, 5, 10)
NS = 1_000_000_000

Key = Tuple[int, int]  # (vpid, handle)


def fq_name(name: str, namespace: str) -> str:
    namespace = namespace.rstrip('/')
    return f'{namespace}/{name}' if namespace else f'/{name}'


@dataclass
class Sub:
    pid: int
    node: str
    topic: str
    lang: str = 'py'
    callback: Optional[int] = None
    symbol: Optional[str] = None
    intra: bool = False
    takes: Deque[int] = field(default_factory=deque)
    done: Deque[Tuple[int, int]] = field(default_factory=deque)  # (end ts, duration ns)


@dataclass
class Pub:
    pid: int
    node: str
    topic: str
    sent: Deque[int] = field(default_factory=deque)


def _p95(sorted_values: Sequence[int]) -> int:
    return sorted_values[max(0, math.ceil(0.95 * len(sorted_values)) - 1)]


def _cb_stats(durations: List[int]) -> Optional[Dict[str, float]]:
    if not durations:
        return None
    durations.sort()
    return {'avg': round(sum(durations) / len(durations) / 1e6, 3),
            'p95': round(_p95(durations) / 1e6, 3), 'max': round(durations[-1] / 1e6, 3)}


class TraceModel:
    def __init__(self, windows: Sequence[int] = WINDOWS_SEC):
        self.windows = tuple(windows)
        self._keep_ns = max(self.windows) * NS
        self._nodes: Dict[Key, str] = {}
        self._procnames: Dict[int, str] = {}
        self._subs: Dict[Key, Sub] = {}
        self._by_rmw: Dict[Key, Sub] = {}
        self._by_cpp: Dict[Key, Sub] = {}
        self._by_cb: Dict[Key, Sub] = {}
        self._symbols: Dict[Key, str] = {}
        self._pubs: Dict[Key, Pub] = {}
        self._open: Dict[Key, Tuple[int, int, bool]] = {}  # (vpid, vtid) -> cb, start, intra
        self._unknown: Dict[int, int] = {}  # vpid -> per-message events without init info

    # -- feeding ---------------------------------------------------------------------
    def feed(self, events: Iterable[Tuple[Any, ...]]) -> None:
        for ev in events:
            kind = ev[0]
            if kind == K_TAKE:
                self._take(ev)
            elif kind == K_CB_START:
                self._cb_start(ev)
            elif kind == K_CB_END:
                self._cb_end(ev)
            elif kind == K_PUBLISH:
                pub = self._pubs.get((ev[2], ev[3]))
                if pub is None:
                    self._mark_unknown(ev[2])
                else:
                    pub.sent.append(ev[1])
            else:
                self._init(ev)

    def _mark_unknown(self, pid: int) -> None:
        self._unknown[pid] = self._unknown.get(pid, 0) + 1

    def _take(self, ev: Tuple[Any, ...]) -> None:
        sub = self._by_rmw.get((ev[2], ev[3]))
        if sub is None:
            self._mark_unknown(ev[2])
        else:
            sub.takes.append(ev[1])

    def _cb_start(self, ev: Tuple[Any, ...]) -> None:
        _, ts, pid, tid, callback, intra = ev
        if (pid, callback) in self._by_cb:
            self._open[(pid, tid)] = (callback, ts, intra)

    def _cb_end(self, ev: Tuple[Any, ...]) -> None:
        _, ts, pid, tid, callback = ev
        started = self._open.pop((pid, tid), None)
        if started is None or started[0] != callback:
            return
        sub = self._by_cb.get((pid, callback))
        if sub is not None:
            sub.done.append((ts, ts - started[1]))
            sub.intra = sub.intra or started[2]

    def _init(self, ev: Tuple[Any, ...]) -> None:
        kind, _ts, pid, procname = ev[0], ev[1], ev[2], ev[3]
        if procname:
            self._procnames[pid] = procname
        if kind == K_NODE:
            self._nodes[(pid, ev[4])] = fq_name(ev[5], ev[6])
        elif kind == K_RCL_SUB:
            node = self._nodes.get((pid, ev[5]))
            if node is not None:
                sub = Sub(pid, node, ev[7])
                self._subs[(pid, ev[4])] = sub
                self._by_rmw[(pid, ev[6])] = sub
        elif kind == K_CPP_SUB:
            sub = self._subs.get((pid, ev[4]))
            if sub is not None:
                sub.lang = 'cpp'
                self._by_cpp[(pid, ev[5])] = sub
        elif kind == K_CB_ADDED:
            sub = self._by_cpp.get((pid, ev[4]))
            if sub is not None:
                sub.callback = ev[5]
                sub.symbol = self._symbols.get((pid, ev[5]))
                self._by_cb[(pid, ev[5])] = sub
        elif kind == K_CB_REGISTER:
            self._symbols[(pid, ev[4])] = ev[5]
            sub = self._by_cb.get((pid, ev[4]))
            if sub is not None:
                sub.symbol = ev[5]
        elif kind == K_RCL_PUB:
            node = self._nodes.get((pid, ev[5]))
            if node is not None:
                self._pubs[(pid, ev[6])] = Pub(pid, node, ev[7])

    # -- housekeeping ----------------------------------------------------------------
    def forget_processes(self, alive: Set[int]) -> None:
        """Drop everything of processes that exited (their handles may be reused)."""
        def gone(key: Key) -> bool:
            return key[0] not in alive
        for table in (self._nodes, self._subs, self._by_rmw, self._by_cpp, self._by_cb,
                      self._symbols, self._pubs, self._open):
            for key in [k for k in table if gone(k)]:
                del table[key]
        for pid in [p for p in self._procnames if p not in alive]:
            del self._procnames[pid]
        for pid in [p for p in self._unknown if p not in alive]:
            del self._unknown[pid]

    def clear_rates(self) -> None:
        """Per-message data is gone with the rt session; the handle registry stays."""
        for sub in self._subs.values():
            sub.takes.clear()
            sub.done.clear()
        for pub in self._pubs.values():
            pub.sent.clear()
        self._open.clear()
        self._unknown.clear()

    def pids(self) -> Set[int]:
        return {k[0] for k in self._nodes} | set(self._unknown)

    def _trim(self, now: int) -> None:
        oldest = now - self._keep_ns
        for sub in self._subs.values():
            while sub.takes and sub.takes[0] <= oldest:
                sub.takes.popleft()
            while sub.done and sub.done[0][0] <= oldest:
                sub.done.popleft()
        for pub in self._pubs.values():
            while pub.sent and pub.sent[0] <= oldest:
                pub.sent.popleft()

    # -- output ----------------------------------------------------------------------
    def snapshot(self, now: int, active_since: Optional[int]) -> Dict[str, Any]:
        """Rates per window; ``active_since`` None = per-message events are not recorded."""
        self._trim(now)
        live = active_since is not None
        nodes: Dict[Tuple[int, str], Dict[str, Any]] = {}
        for (pid, _h), name in self._nodes.items():
            nodes[(pid, name)] = {'node': name, 'pid': pid, 'lang': 'py',
                                  'procname': self._procnames.get(pid, '')}
        subs = []
        for sub in self._subs.values():
            if sub.lang == 'cpp' and (sub.pid, sub.node) in nodes:
                nodes[(sub.pid, sub.node)]['lang'] = 'cpp'
            subs.append({'node': sub.node, 'topic': sub.topic, 'pid': sub.pid, 'lang': sub.lang,
                         'intra': sub.intra, 'symbol': sub.symbol,
                         'windows': {str(w): self._sub_window(sub, now, w, live)
                                     for w in self.windows}})
        pubs = [{'node': p.node, 'topic': p.topic, 'pid': p.pid,
                 'windows': {str(w): {'hz': self._rate(p.sent, now, w, live)}
                             for w in self.windows}}
                for p in self._pubs.values()]
        traced = {k[0] for k in self._nodes}
        unknown = sorted(p for p in self._unknown if p not in traced)
        return {'nodes': sorted(nodes.values(), key=lambda n: (n['node'], n['pid'])),
                'subscriptions': subs, 'publishers': pubs, 'unknown_pids': unknown}

    @staticmethod
    def _rate(times: Iterable[int], now: int, window: int, live: bool) -> Optional[float]:
        """Probe-equivalent rate (stats.window_rate); None = still measuring."""
        if not live:
            return None
        hz, _note = window_rate([t / NS for t in times], now / NS, float(window))
        return None if hz is None else round(hz, 3)

    def _sub_window(self, sub: Sub, now: int, window: int, live: bool
                    ) -> Dict[str, Any]:
        start = now - window * NS
        durations = [d for end, d in sub.done if start < end <= now]
        cpp = sub.lang == 'cpp'
        return {'hz_recv': None if sub.intra else self._rate(sub.takes, now, window, live),
                'hz_processed': (self._rate((end for end, _d in sub.done), now, window, live)
                                 if cpp else None),
                'cb_ms': _cb_stats(durations) if cpp else None}
