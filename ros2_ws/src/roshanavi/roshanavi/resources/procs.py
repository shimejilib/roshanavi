"""Per-process sampling straight from ``/proc`` (two passes, rates from deltas between calls).

Pass 1 (:meth:`ProcessTable.scan`) reads one file per visible process,
``/proc/<pid>/stat`` (parent, name, CPU time, threads, start time, RSS), plus the command
line once per process. Going through psutil's ``process_iter`` cost ~5 file opens per
process and made the 1 Hz sampler too heavy with ~70 processes (measured 3 % of a core).
Pass 2 (:meth:`ProcessTable.detail`) reads the extras only for the processes we report
on (ROS nodes and roshanavi itself): disk I/O (``/proc/<pid>/io``) and USS
(``/proc/<pid>/smaps_rollup``, every ``uss_period_sec``, like psutil's ``uss``).

Visibility: only processes of the current user unless we run as root (a container);
other users' processes are skipped entirely, not just their protected fields.
CPU % follows ``top``: 100 = one core fully busy (``cpu_norm_pct`` divides by cores).
"""

import os
from dataclasses import dataclass, replace
from typing import Callable, Dict, Iterator, Mapping, Optional, Tuple

import psutil

PROC_ROOT = '/proc'
USS_PERIOD_SEC = 5.0
COMM_LEN = 15  # the kernel truncates /proc/<pid>/stat names to 15 characters
CLK_TCK = os.sysconf('SC_CLK_TCK') if hasattr(os, 'sysconf') else 100
PAGE_SIZE = os.sysconf('SC_PAGE_SIZE') if hasattr(os, 'sysconf') else 4096

Key = Tuple[int, float]  # (pid, create_time): survives pid reuse


@dataclass(frozen=True)
class ProcRow:
    pid: int
    ppid: int
    name: str
    cmdline: Tuple[str, ...]
    create_time: float
    cpu_seconds: float
    rss: int
    threads: Optional[int] = None
    cpu_pct: Optional[float] = None  # None until a second sample exists
    uss: Optional[int] = None
    fds: Optional[int] = None
    read_bps: Optional[float] = None
    write_bps: Optional[float] = None

    @property
    def key(self) -> Key:
        return (self.pid, self.create_time)

    @property
    def exe_name(self) -> str:
        """Program basename, skipping an interpreter (``python3 script``)."""
        for item in self.cmdline[:2]:
            base = os.path.basename(item)
            if base and not base.startswith('python'):
                return base
        return self.name


@dataclass(frozen=True)
class RawProc:
    """One ``/proc/<pid>/stat`` reading (cumulative counters)."""
    pid: int
    ppid: int
    comm: str
    cpu_seconds: float
    threads: int
    create_time: float
    rss: int
    uid: Optional[int] = None


def visible_all() -> bool:
    """Root (typically a container) sees every process; others only their own."""
    return hasattr(os, 'geteuid') and os.geteuid() == 0


def parse_stat(pid: int, text: str, boot_time: float) -> Optional[RawProc]:
    """Fields of ``/proc/<pid>/stat`` (the name may contain spaces and parentheses)."""
    head, sep, tail = text.rpartition(')')
    if not sep:
        return None
    comm = head.partition('(')[2]
    fields = tail.split()
    if len(fields) < 22:
        return None
    try:
        return RawProc(pid=pid, ppid=int(fields[1]), comm=comm,
                       cpu_seconds=(int(fields[11]) + int(fields[12])) / CLK_TCK,
                       threads=int(fields[17]), create_time=boot_time + int(fields[19]) / CLK_TCK,
                       rss=int(fields[21]) * PAGE_SIZE)
    except ValueError:
        return None


def read_procs(root: str = PROC_ROOT, uid: Optional[int] = None,
               boot_time: Optional[float] = None) -> Iterator[RawProc]:
    """Every process under ``root`` (only ``uid``'s when given)."""
    boot = psutil.boot_time() if boot_time is None else boot_time
    try:
        names = os.listdir(root)
    except OSError:
        return
    for name in names:
        if not name.isdigit():
            continue
        path = os.path.join(root, name)
        try:
            if uid is not None and os.stat(path).st_uid != uid:
                continue
            with open(os.path.join(path, 'stat'), encoding='utf-8', errors='replace') as handle:
                raw = parse_stat(int(name), handle.read(), boot)
        except OSError:  # exited between listdir and open, or not ours
            continue
        if raw is not None:
            yield raw


def read_cmdline(pid: int, root: str = PROC_ROOT) -> Tuple[str, ...]:
    try:
        with open(os.path.join(root, str(pid), 'cmdline'), 'rb') as handle:
            data = handle.read()
    except OSError:
        return ()
    return tuple(part.decode('utf-8', 'replace') for part in data.split(b'\0') if part)


def read_io(pid: int, root: str = PROC_ROOT) -> Optional[Tuple[int, int]]:
    """(read_bytes, write_bytes) that reached the storage layer; None if unreadable."""
    try:
        with open(os.path.join(root, str(pid), 'io'), encoding='ascii') as handle:
            text = handle.read()
    except OSError:
        return None
    values: Dict[str, int] = {}
    for line in text.splitlines():
        key, _, value = line.partition(':')
        if key in ('read_bytes', 'write_bytes'):
            values[key] = int(value)
    if len(values) != 2:
        return None
    return values['read_bytes'], values['write_bytes']


def read_uss(pid: int, root: str = PROC_ROOT) -> Optional[int]:
    """Unique set size: private pages (``Private_*`` of ``smaps_rollup``)."""
    try:
        with open(os.path.join(root, str(pid), 'smaps_rollup'), encoding='ascii') as handle:
            text = handle.read()
    except OSError:
        return None
    total = 0
    found = False
    for line in text.splitlines():
        if line.startswith(('Private_Clean:', 'Private_Dirty:', 'Private_Hugetlb:')):
            total += int(line.split()[1]) * 1024
            found = True
    return total if found else None


def _display_name(comm: str, cmdline: Tuple[str, ...]) -> str:
    """A readable name: the script of ``python3 script`` / ``python3 -m mod``, the untruncated
    program name when the kernel cut it at 15 characters, else the kernel's name."""
    if comm.startswith('python') and len(cmdline) > 1:
        if cmdline[1] == '-m' and len(cmdline) > 2:
            return cmdline[2]
        if not cmdline[1].startswith('-'):
            return os.path.basename(cmdline[1])
    if len(comm) >= COMM_LEN and cmdline:
        for item in cmdline[:2]:
            base = os.path.basename(item)
            if base.startswith(comm):
                return base
    return comm


class ProcessTable:
    """Keeps the previous counters per process to turn them into rates."""

    def __init__(self, own_uid: Optional[int] = None, see_all: Optional[bool] = None,
                 reader: Optional[Callable[[Optional[int]], Iterator[RawProc]]] = None,
                 root: str = PROC_ROOT, uss_period_sec: float = USS_PERIOD_SEC,
                 cmdline: Optional[Callable[[int], Tuple[str, ...]]] = None):
        self._uid = os.getuid() if own_uid is None else own_uid
        self.see_all = visible_all() if see_all is None else see_all
        self._root = root
        self._reader = reader or (lambda uid: read_procs(root, uid))
        self._read_cmdline = cmdline or (lambda pid: read_cmdline(pid, root))
        self._uss_period = uss_period_sec
        self._cmdlines: Dict[Key, Tuple[str, ...]] = {}
        self._cpu_prev: Dict[Key, Tuple[float, float]] = {}
        self._io_prev: Dict[Key, Tuple[float, int, int]] = {}
        self._uss: Dict[Key, Tuple[float, Optional[int]]] = {}

    def scan(self, now: float) -> Dict[int, ProcRow]:
        """Pass 1 over all visible processes; ``now`` is monotonic seconds."""
        rows: Dict[int, ProcRow] = {}
        cpu_prev: Dict[Key, Tuple[float, float]] = {}
        for raw in self._reader(None if self.see_all else self._uid):
            key = (raw.pid, raw.create_time)
            prev = self._cpu_prev.get(key)
            pct = None
            if prev is not None and now > prev[0]:
                pct = max(0.0, (raw.cpu_seconds - prev[1]) / (now - prev[0]) * 100.0)
            cpu_prev[key] = (now, raw.cpu_seconds)
            cmdline = self._cmdlines.get(key)
            if cmdline is None:
                cmdline = self._cmdlines[key] = self._read_cmdline(raw.pid)
            rows[raw.pid] = ProcRow(
                pid=raw.pid, ppid=raw.ppid, name=_display_name(raw.comm, cmdline),
                cmdline=cmdline, create_time=raw.create_time, cpu_seconds=raw.cpu_seconds,
                rss=raw.rss, threads=raw.threads, cpu_pct=pct)
        self._cpu_prev = cpu_prev
        for cache in (self._cmdlines, self._io_prev, self._uss):
            for key in [k for k in cache if k not in cpu_prev]:
                del cache[key]
        return rows

    def detail(self, row: ProcRow, now: float) -> ProcRow:
        """Pass 2 extras for one process (I/O rates, USS); missing fields stay None.

        Open fds are counted by :func:`.connections.collect`, which lists them anyway."""
        extra: Dict[str, object] = {}
        io = read_io(row.pid, self._root)
        if io is not None:
            prev = self._io_prev.get(row.key)
            if prev is not None and now > prev[0]:
                extra['read_bps'] = max(0.0, (io[0] - prev[1]) / (now - prev[0]))
                extra['write_bps'] = max(0.0, (io[1] - prev[2]) / (now - prev[0]))
            self._io_prev[row.key] = (now, io[0], io[1])
        cached = self._uss.get(row.key)
        if cached is None or now - cached[0] >= self._uss_period:
            cached = self._uss[row.key] = (now, read_uss(row.pid, self._root))
        extra['uss'] = cached[1]
        return replace(row, **extra)  # type: ignore[arg-type]


def children_map(rows: Mapping[int, ProcRow]) -> Dict[int, Tuple[int, ...]]:
    children: Dict[int, list] = {}
    for row in rows.values():
        children.setdefault(row.ppid, []).append(row.pid)
    return {pid: tuple(sorted(kids)) for pid, kids in children.items()}


def descendants(rows: Mapping[int, ProcRow], root: int,
                children: Optional[Dict[int, Tuple[int, ...]]] = None) -> Tuple[int, ...]:
    """``root`` and every descendant present in ``rows`` (breadth first)."""
    if root not in rows:
        return ()
    kids = children_map(rows) if children is None else children
    out, queue, seen = [], [root], {root}
    while queue:
        pid = queue.pop(0)
        out.append(pid)
        for child in kids.get(pid, ()):
            if child not in seen:
                seen.add(child)
                queue.append(child)
    return tuple(out)
