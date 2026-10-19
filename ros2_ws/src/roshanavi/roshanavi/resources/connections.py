"""Sockets of the monitored processes: who talks to which host:port (metadata only).

Same source as ``psutil.net_connections`` (``/proc/net/{tcp,tcp6,udp,udp6}`` joined with
each process's socket inodes from ``/proc/<pid>/fd``), but the tables are read once per
sample and only the monitored processes' fds are listed, which keeps 1 Hz polling cheap.
No packets are captured and no payload is ever read.

- Listed: TCP sockets with a remote address (not LISTEN) and connected UDP sockets.
  Unconnected UDP sockets (DDS discovery / data) are only counted.
- Events: a connection seen for the first time -> ``open``, gone -> ``close``. Polling
  misses connections that live less than one sample period.
- Remote names come from a reverse DNS cache filled in the background (never blocks).
"""

import ipaddress
import logging
import os
import queue
import socket
import struct
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Deque, Dict, Iterable, List, Mapping, Optional, Set, Tuple

LOG = logging.getLogger(__name__)

PROC_ROOT = '/proc'
TABLES = (('tcp', 'tcp', socket.AF_INET), ('tcp6', 'tcp', socket.AF_INET6),
          ('udp', 'udp', socket.AF_INET), ('udp6', 'udp', socket.AF_INET6))
TCP_STATES = {'01': 'ESTABLISHED', '02': 'SYN_SENT', '03': 'SYN_RECV', '04': 'FIN_WAIT1',
              '05': 'FIN_WAIT2', '06': 'TIME_WAIT', '07': 'CLOSE', '08': 'CLOSE_WAIT',
              '09': 'LAST_ACK', '0A': 'LISTEN', '0B': 'CLOSING'}
MAX_EVENTS = 300
MAX_RDNS_CACHE = 1024  # remote hosts remembered; a scan of many addresses must not grow it
MAX_PER_PROCESS = 100
TABLE_REFRESH_SEC = 5.0


def decode_address(text: str, family: int) -> Tuple[str, int]:
    """``0100007F:1F90`` -> ``('127.0.0.1', 8080)`` (kernel little-endian words)."""
    host_hex, port_hex = text.split(':')
    raw = bytes.fromhex(host_hex)
    if family == socket.AF_INET:
        packed = struct.pack('<I', struct.unpack('>I', raw)[0])
    else:
        words = struct.unpack('>4I', raw)
        packed = struct.pack('<4I', *words)
    return socket.inet_ntop(family, packed), int(port_hex, 16)


@dataclass(frozen=True)
class SockEntry:
    inode: int
    proto: str
    laddr: Tuple[str, int]
    raddr: Optional[Tuple[str, int]]
    status: str


def parse_table(text: str, proto: str, family: int) -> List[SockEntry]:
    out: List[SockEntry] = []
    for line in text.splitlines()[1:]:
        parts = line.split()
        if len(parts) < 10:
            continue
        try:
            laddr = decode_address(parts[1], family)
            raddr = decode_address(parts[2], family)
            inode = int(parts[9])
        except (ValueError, struct.error, OSError):
            continue
        state = TCP_STATES.get(parts[3], parts[3]) if proto == 'tcp' else (
            'CONNECTED' if raddr[1] else 'NONE')
        unspecified = raddr[1] == 0 and ipaddress.ip_address(raddr[0]).is_unspecified
        out.append(SockEntry(inode, proto, laddr, None if unspecified else raddr, state))
    return out


def read_tables(root: str = PROC_ROOT) -> Dict[int, SockEntry]:
    by_inode: Dict[int, SockEntry] = {}
    for name, proto, family in TABLES:
        try:
            with open(os.path.join(root, 'net', name), encoding='ascii') as handle:
                text = handle.read()
        except OSError:
            continue
        for entry in parse_table(text, proto, family):
            by_inode[entry.inode] = entry
    return by_inode


def socket_inodes(pid: int, root: str = PROC_ROOT) -> Tuple[int, List[int]]:
    """(number of open fds, socket inodes) of one process; (-1, []) when unreadable."""
    fd_dir = os.path.join(root, str(pid), 'fd')
    inodes: List[int] = []
    count = 0
    try:
        with os.scandir(fd_dir) as entries:
            for entry in entries:
                count += 1
                try:
                    target = os.readlink(entry.path)
                except OSError:
                    continue
                if target.startswith('socket:['):
                    inodes.append(int(target[8:-1]))
    except OSError:
        return -1, []
    return count, inodes


def is_local(host: str) -> bool:
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


@dataclass(frozen=True)
class Conn:
    pid: int
    proto: str
    laddr: Tuple[str, int]
    raddr: Tuple[str, int]
    status: str

    @property
    def key(self) -> Tuple[int, str, Tuple[str, int], Tuple[str, int]]:
        return (self.pid, self.proto, self.laddr, self.raddr)


@dataclass
class ProcSockets:
    fds: int
    conns: List[Conn]
    udp_open: int  # unconnected UDP sockets (DDS)
    listening: int


def _join(pid: int, fds: int, inodes: List[int], tables: Mapping[int, SockEntry]) -> ProcSockets:
    conns: List[Conn] = []
    udp_open = listening = 0
    for inode in inodes:
        entry = tables.get(inode)
        if entry is None:
            continue
        if entry.status == 'LISTEN':
            listening += 1
        elif entry.raddr is None:
            udp_open += entry.proto == 'udp'
        elif len(conns) < MAX_PER_PROCESS:
            conns.append(Conn(pid, entry.proto, entry.laddr, entry.raddr, entry.status))
    return ProcSockets(fds, conns, udp_open, listening)


def collect(pids: Iterable[int], root: str = PROC_ROOT) -> Dict[int, ProcSockets]:
    """One-shot: list the fds of ``pids`` and join them with the socket tables."""
    tables = read_tables(root)
    out: Dict[int, ProcSockets] = {}
    for pid in pids:
        fds, inodes = socket_inodes(pid, root)
        if fds >= 0:
            out[pid] = _join(pid, fds, inodes, tables)
    return out


class SocketCollector:
    """:func:`collect` for 1 Hz polling, with two caches (measured: ~1000 ``readlink`` calls
    and ~1 ms per table read in a lab with tracing on were most of the sampler's cost):

    - a process's socket inodes are re-read (one ``readlink`` per fd) only when its set of
      fd numbers changed, or every ``refresh_sec``. A socket closed and another opened on
      the same fd number within that time is seen late, like any connection shorter than
      the polling period;
    - the kernel's socket tables are re-read only when the set of socket inodes changed, or
      every ``refresh_sec`` (TCP state changes).
    """

    def __init__(self, root: str = PROC_ROOT, refresh_sec: float = TABLE_REFRESH_SEC):
        self._root = root
        self._refresh = refresh_sec
        self._tables: Dict[int, SockEntry] = {}
        self._inodes: frozenset = frozenset()
        self._read_at: Optional[float] = None
        self._fds: Dict[int, Tuple[frozenset, List[int], float]] = {}

    def _process(self, pid: int, now: float) -> Optional[Tuple[int, List[int]]]:
        try:
            names = frozenset(os.listdir(os.path.join(self._root, str(pid), 'fd')))
        except OSError:
            self._fds.pop(pid, None)
            return None
        cached = self._fds.get(pid)
        if cached is not None and cached[0] == names and now - cached[2] < self._refresh:
            return len(names), cached[1]
        fds, inodes = socket_inodes(pid, self._root)
        if fds < 0:
            return None
        self._fds[pid] = (names, inodes, now)
        return fds, inodes

    def collect(self, pids: Iterable[int], now: float) -> Dict[int, ProcSockets]:
        listed: Dict[int, Tuple[int, List[int]]] = {}
        for pid in pids:
            found = self._process(pid, now)
            if found is not None:
                listed[pid] = found
        for pid in [p for p in self._fds if p not in listed]:
            del self._fds[pid]
        inodes_now = frozenset(i for _, inodes in listed.values() for i in inodes)
        stale = self._read_at is None or now - self._read_at >= self._refresh
        if stale or inodes_now != self._inodes:
            self._tables = read_tables(self._root)
            self._read_at = now
        self._inodes = inodes_now
        return {pid: _join(pid, fds, inodes, self._tables) for pid, (fds, inodes) in listed.items()}


class ReverseDns:
    """Background reverse lookups with a cache; :meth:`name` never blocks."""

    def __init__(self, resolve: Callable[[str], str] = lambda ip: socket.gethostbyaddr(ip)[0],
                 ttl_sec: float = 600.0, negative_ttl_sec: float = 300.0, workers: int = 2,
                 max_pending: int = 64, clock: Callable[[], float] = time.monotonic,
                 enabled: bool = True, max_cache: int = MAX_RDNS_CACHE):
        self._resolve = resolve
        self._max_cache = max_cache
        self._ttl, self._neg_ttl = ttl_sec, negative_ttl_sec
        self._clock = clock
        self._cache: Dict[str, Tuple[Optional[str], float]] = {}
        self._pending: Set[str] = set()
        self._lock = threading.Lock()
        self._queue: 'queue.Queue[Optional[str]]' = queue.Queue(maxsize=max_pending)
        self._threads: List[threading.Thread] = []
        self.enabled = enabled
        if enabled:
            for i in range(workers):
                thread = threading.Thread(target=self._work, name=f'rdns-{i}', daemon=True)
                thread.start()
                self._threads.append(thread)

    def name(self, ip: str) -> Optional[str]:
        if is_local(ip):
            return 'localhost'
        if not self.enabled:
            return None
        now = self._clock()
        with self._lock:
            cached = self._cache.get(ip)
            if cached is not None and cached[1] > now:
                return cached[0]
            if ip in self._pending:
                return cached[0] if cached else None
            try:
                self._queue.put_nowait(ip)
            except queue.Full:
                return cached[0] if cached else None
            self._pending.add(ip)
        return cached[0] if cached else None

    def _work(self) -> None:
        while True:
            ip = self._queue.get()
            if ip is None:
                return
            try:
                name: Optional[str] = self._resolve(ip)
            except (OSError, UnicodeError, ValueError):
                name = None
            ttl = self._ttl if name else self._neg_ttl
            with self._lock:
                self._cache[ip] = (name, self._clock() + ttl)
                self._pending.discard(ip)
                self._trim_cache()

    def _trim_cache(self) -> None:
        """Keep at most ``max_cache`` entries: expired ones first, then the soonest to expire."""
        if len(self._cache) <= self._max_cache:
            return
        now = self._clock()
        for ip in [i for i, (_n, until) in self._cache.items() if until <= now]:
            del self._cache[ip]
        excess = len(self._cache) - self._max_cache
        if excess > 0:
            for ip in sorted(self._cache, key=lambda i: self._cache[i][1])[:excess]:
                del self._cache[ip]

    def close(self) -> None:
        for _ in self._threads:
            try:
                self._queue.put_nowait(None)
            except queue.Full:
                break


class ConnectionTracker:
    """Current connection list + open / close events between samples."""

    def __init__(self, max_events: int = MAX_EVENTS):
        self._current: Dict[tuple, Conn] = {}
        self._first = True
        self.events: Deque[Dict[str, object]] = deque(maxlen=max_events)
        self._seq = 0

    def update(self, conns: Iterable[Conn], wall: float,
               label: Callable[[int], Mapping[str, object]],
               rdns: Optional[ReverseDns] = None) -> List[Dict[str, object]]:
        """Diff against the previous sample; returns the new events (oldest first)."""
        cur = {c.key: c for c in conns}
        new: List[Dict[str, object]] = []
        if not self._first:
            for key in cur.keys() - self._current.keys():
                new.append(self._event('open', cur[key], wall, label, rdns))
            for key in self._current.keys() - cur.keys():
                new.append(self._event('close', self._current[key], wall, label, rdns))
        self._first = False
        self._current = cur
        new.sort(key=lambda e: (e['kind'] != 'close', str(e['raddr'])))
        self.events.extend(new)
        return new

    def _event(self, kind: str, conn: Conn, wall: float,
               label: Callable[[int], Mapping[str, object]],
               rdns: Optional[ReverseDns]) -> Dict[str, object]:
        self._seq += 1
        return {'seq': self._seq, 'kind': kind, 't': wall, **conn_dict(conn, rdns),
                **label(conn.pid)}


def conn_dict(conn: Conn, rdns: Optional[ReverseDns]) -> Dict[str, object]:
    host = conn.raddr[0]
    return {'pid': conn.pid, 'proto': conn.proto, 'laddr': f'{_hostport(conn.laddr)}',
            'raddr': _hostport(conn.raddr), 'rhost': rdns.name(host) if rdns else None,
            'status': conn.status, 'local': is_local(host)}


def _hostport(addr: Tuple[str, int]) -> str:
    host, port = addr
    return f'[{host}]:{port}' if ':' in host else f'{host}:{port}'
