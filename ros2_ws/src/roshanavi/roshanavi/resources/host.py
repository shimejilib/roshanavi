"""Whole-PC counters (CPU per core, memory / swap, the data_dir volume, NICs, UDP buffers).

Rates come from deltas between two calls of :meth:`HostSampler.sample`, so the first
call returns ``None`` for every rate. CPU is computed from ``cpu_times`` deltas here
(not ``psutil.cpu_percent``, whose hidden state other callers would disturb).

What is *not* covered (shown in the UI): other PCs, and traffic inside this PC: ROS
communication on the same PC goes through loopback or shared memory, which never shows
up on a physical NIC (loopback interfaces are excluded on purpose).
"""

import os
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Tuple

import psutil

from ..media.diskguard import DiskGuard
from .snmp import read_udp

UDP_RECENT_SEC = 60.0
MOUNT_REFRESH_SEC = 60.0


def _busy_total(times: Any) -> Tuple[float, float]:
    total = sum(float(v) for v in times)
    idle = float(getattr(times, 'idle', 0.0)) + float(getattr(times, 'iowait', 0.0))
    return total - idle, total


def cpu_percents(prev: List[Any], cur: List[Any]) -> List[float]:
    """Per-core busy % between two ``cpu_times(percpu=True)`` readings."""
    out: List[float] = []
    for before, after in zip(prev, cur):
        busy0, total0 = _busy_total(before)
        busy1, total1 = _busy_total(after)
        span = total1 - total0
        out.append(0.0 if span <= 0 else max(0.0, min(100.0, (busy1 - busy0) / span * 100.0)))
    return out


def is_loopback(name: str) -> bool:
    return name == 'lo' or name.startswith('lo:') or name.startswith('loopback')


def volume_device(path: str, partitions: List[Any]) -> Optional[str]:
    """Kernel disk name (``sda1``, ``dm-0``) of the mount holding ``path``; None if unknown."""
    real = os.path.realpath(path)
    best: Optional[Any] = None
    for part in partitions:
        mount = part.mountpoint.rstrip('/') or '/'
        if real == mount or real.startswith(mount + '/') or mount == '/':
            if best is None or len(mount) > len(best.mountpoint.rstrip('/') or '/'):
                best = part
    if best is None or not best.device.startswith('/dev/'):
        return None
    return os.path.basename(os.path.realpath(best.device))


def _rate(cur: float, prev: Optional[float], dt: float) -> Optional[float]:
    if prev is None or dt <= 0:
        return None
    return max(0.0, (cur - prev) / dt)


class HostSampler:
    def __init__(self, data_dir: str, guard: DiskGuard, ps: Any = psutil,
                 udp: Callable[[], Optional[Dict[str, int]]] = read_udp):
        self._data_dir = data_dir
        self._guard = guard
        self._ps = ps
        self._udp = udp
        self._cpu_prev: Optional[List[Any]] = None
        self._prev_t: Optional[float] = None
        self._nic_prev: Dict[str, Any] = {}
        self._disk_prev: Optional[Any] = None
        self._udp_prev: Optional[Dict[str, int]] = None
        self._udp_hist: Deque[Tuple[float, int]] = deque()
        self._device: Optional[str] = None
        self._device_at = -MOUNT_REFRESH_SEC
        self.ncpu = ps.cpu_count() or 1

    # ---- parts ----------------------------------------------------------------------------
    def _cpu(self) -> Dict[str, Any]:
        cur = self._ps.cpu_times(percpu=True)
        prev, self._cpu_prev = self._cpu_prev, cur
        if prev is None or len(prev) != len(cur):
            return {'total_pct': None, 'per_core': [], 'cores': len(cur)}
        per_core = cpu_percents(prev, cur)
        total = sum(per_core) / len(per_core) if per_core else None
        return {'total_pct': None if total is None else round(total, 1),
                'per_core': [round(v, 1) for v in per_core], 'cores': len(cur)}

    def _memory(self) -> Dict[str, Any]:
        vm, sw = self._ps.virtual_memory(), self._ps.swap_memory()
        used = vm.total - vm.available
        return {'total': vm.total, 'available': vm.available, 'used': used,
                'pct': round(100.0 * used / vm.total, 1) if vm.total else None,
                'swap_total': sw.total, 'swap_used': sw.used,
                'swap_pct': round(sw.percent, 1) if sw.total else None}

    def _disk(self, now: float, dt: float) -> Dict[str, Any]:
        try:
            level = self._guard.check()
        except OSError as exc:
            return {'path': self._data_dir, 'error': str(exc)}
        if now - self._device_at >= MOUNT_REFRESH_SEC:
            self._device_at = now
            try:
                self._device = volume_device(self._data_dir, self._ps.disk_partitions(all=False))
            except OSError:
                self._device = None
        out: Dict[str, Any] = {'path': self._data_dir, 'device': self._device,
                               'free': level['free_bytes'], 'total': level['total_bytes'],
                               'free_pct': level['free_pct'], 'level': level['level'],
                               'thresholds': vars(self._guard.thresholds),
                               'read_bps': None, 'write_bps': None}
        counters = None
        if self._device:
            try:
                counters = (self._ps.disk_io_counters(perdisk=True) or {}).get(self._device)
            except (OSError, RuntimeError):
                counters = None
        if counters is not None:
            prev, self._disk_prev = self._disk_prev, counters
            if prev is not None:
                out['read_bps'] = _rate(counters.read_bytes, prev.read_bytes, dt)
                out['write_bps'] = _rate(counters.write_bytes, prev.write_bytes, dt)
        return out

    def _nics(self, dt: float) -> List[Dict[str, Any]]:
        try:
            counters = self._ps.net_io_counters(pernic=True) or {}
        except OSError:
            return []
        nics: List[Dict[str, Any]] = []
        prev_all, self._nic_prev = self._nic_prev, {}
        for name in sorted(counters):
            if is_loopback(name):
                continue
            cur = counters[name]
            self._nic_prev[name] = cur
            prev = prev_all.get(name)

            def rate(field: str) -> Optional[float]:
                return _rate(getattr(cur, field), getattr(prev, field) if prev else None, dt)
            nics.append({'name': name, 'rx_bps': rate('bytes_recv'), 'tx_bps': rate('bytes_sent'),
                         'rx_pps': rate('packets_recv'), 'tx_pps': rate('packets_sent'),
                         'errin': cur.errin, 'errout': cur.errout, 'dropin': cur.dropin,
                         'dropout': cur.dropout,
                         'err_per_sec': (None if prev is None else
                                         _rate(cur.errin + cur.errout,
                                               prev.errin + prev.errout, dt)),
                         'drop_per_sec': (None if prev is None else
                                          _rate(cur.dropin + cur.dropout,
                                                prev.dropin + prev.dropout, dt))})
        return nics

    def _udp_counters(self, now: float, dt: float) -> Optional[Dict[str, Any]]:
        counters = self._udp()
        if not counters:
            return None
        prev, self._udp_prev = self._udp_prev, counters
        rcv = counters.get('RcvbufErrors', 0)
        self._udp_hist.append((now, rcv))
        while self._udp_hist and self._udp_hist[0][0] < now - UDP_RECENT_SEC:
            self._udp_hist.popleft()
        recent = rcv - self._udp_hist[0][1] if self._udp_hist else 0
        return {'rcvbuf_errors': rcv, 'sndbuf_errors': counters.get('SndbufErrors', 0),
                'in_errors': counters.get('InErrors', 0),
                'in_datagrams': counters.get('InDatagrams', 0),
                'rcvbuf_per_sec': (None if prev is None else
                                   _rate(rcv, prev.get('RcvbufErrors', 0), dt)),
                'sndbuf_per_sec': (None if prev is None else
                                   _rate(counters.get('SndbufErrors', 0),
                                         prev.get('SndbufErrors', 0), dt)),
                'rcvbuf_recent': max(0, recent), 'recent_sec': UDP_RECENT_SEC}

    # ---- all ------------------------------------------------------------------------------
    def sample(self, now: float) -> Dict[str, Any]:
        dt = 0.0 if self._prev_t is None else now - self._prev_t
        self._prev_t = now
        return {'cpu': self._cpu(), 'mem': self._memory(), 'disk': self._disk(now, dt),
                'nics': self._nics(dt), 'udp': self._udp_counters(now, dt)}
