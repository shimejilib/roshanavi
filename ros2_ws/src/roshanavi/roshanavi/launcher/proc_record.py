"""Record of every process the launcher started, for cleaning up after a SIGKILL (#12).

The server writes ``<data_dir>/run/procs-<server pid>.json`` (atomic replace)
whenever the set of its target processes changes: the target's root process and
every descendant (``ros2 run`` / ``ros2 launch`` wrappers start the real node as
a grandchild), each with a fingerprint -- start time and a hash of the command
line -- so a PID the kernel has since given to another program is never taken
for ours. A normal shutdown stops the children and removes the file.

If the server is killed (SIGKILL, OOM) the file stays. The next server start, or
``ros2 run roshanavi cleanup``, reads the files whose server is gone, keeps the
entries that still match their fingerprint (plus their current descendants:
started by a recorded process) and stops them group by group: SIGINT -> SIGTERM
-> SIGKILL. Processes that are not in a record are never signalled.
"""

import hashlib
import json
import logging
import os
import re
import signal
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import psutil

from .dummy_config import write_atomic

LOG = logging.getLogger(__name__)

RECORD_DIR = 'run'
FILE_RE = re.compile(r'^procs-(\d+)(\.prev-\d+)?\.json$')
MAX_FILE_BYTES = 1024 * 1024
MAX_ENTRIES = 2000
CMD_TEXT_LEN = 300
TIME_TOLERANCE_SEC = 1.0  # only without /proc (start_ticks is exact)
STOP_STEPS: Tuple[Tuple[int, float], ...] = (
    (signal.SIGINT, 4.0), (signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0))
POLL_SEC = 0.1


def start_ticks(pid: int) -> Optional[int]:
    """When the process started, in clock ticks since boot (``/proc/<pid>/stat`` field 22).

    Unlike a wall-clock start time this never moves: psutil's ``create_time`` is
    boot time + ticks, and the boot time read from ``/proc/stat`` drifts on some
    kernels (WSL2), so two readings of the same process can differ by seconds.
    """
    try:
        with open(f'/proc/{pid}/stat', 'rb') as handle:
            data = handle.read()
        return int(data[data.rindex(b')') + 2:].split()[19])
    except (OSError, ValueError, IndexError):
        return None


def cmd_hash(cmdline: Sequence[str]) -> str:
    return hashlib.sha256('\0'.join(cmdline).encode('utf-8', 'replace')).hexdigest()[:32]


def _fingerprint(proc: psutil.Process) -> Optional[Dict[str, Any]]:
    try:
        with proc.oneshot():
            cmdline = proc.cmdline()
            return {'pid': proc.pid, 'pgid': os.getpgid(proc.pid),
                    'create_time': proc.create_time(), 'start_ticks': start_ticks(proc.pid),
                    'cmd_hash': cmd_hash(cmdline),
                    'cmd': ' '.join(cmdline)[:CMD_TEXT_LEN]}
    except (psutil.Error, OSError):
        return None


def tree_fingerprints(target_id: str, root_pid: int) -> List[Dict[str, Any]]:
    """The root process and its descendants, fingerprinted."""
    try:
        root = psutil.Process(root_pid)
        procs = [root, *root.children(recursive=True)]
    except psutil.Error:
        return []
    result = []
    for proc in procs:
        entry = _fingerprint(proc)
        if entry is not None:
            result.append({**entry, 'target': target_id})
    return result


def records_dir(data_dir: str) -> str:
    return os.path.join(data_dir, RECORD_DIR)


class ProcessRecord:
    """This server's record file; :meth:`update` is called from the housekeeping thread."""

    def __init__(self, data_dir: str, server_pid: Optional[int] = None):
        self._pid = server_pid or os.getpid()
        self.path = os.path.join(records_dir(data_dir), f'procs-{self._pid}.json')
        self._lock = threading.Lock()
        self._last: Optional[List[Tuple[int, int, str]]] = None
        self._server = _fingerprint(psutil.Process(self._pid)) or {'pid': self._pid}
        self._keep_previous()

    def _keep_previous(self) -> None:
        """A previous server with the same PID (common in containers) left its record here:
        move it aside so it is still found as leftovers and never overwritten."""
        if not os.path.exists(self.path):
            return
        aside = self.path[:-len('.json')] + f'.prev-{time.time_ns()}.json'
        try:
            os.replace(self.path, aside)
        except OSError as exc:
            LOG.warning('cannot keep the previous process record %s: %s', self.path, exc)

    def update(self, refs: Iterable[Tuple[str, float, int]]) -> None:
        """``refs``: (target id, started_at, root pid) of every live target."""
        entries = [e for target_id, _, pid in refs for e in tree_fingerprints(target_id, pid)]
        key = sorted((e['pid'], e['start_ticks'] or 0, e['cmd_hash']) for e in entries)
        with self._lock:
            if key == self._last:
                return
            self._last = key
            if not entries:
                self._remove()
                return
            payload = {'version': 1, 'server': self._server, 'written_at': time.time(),
                       'processes': entries[:MAX_ENTRIES]}
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                write_atomic(self.path, json.dumps(payload, indent=1))
            except OSError as exc:
                LOG.warning('cannot write the process record %s: %s', self.path, exc)
                self._last = None

    def _remove(self) -> None:
        try:
            os.unlink(self.path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            LOG.warning('cannot remove the process record %s: %s', self.path, exc)

    def close(self) -> None:
        """Normal shutdown (children already stopped): the record is no longer needed."""
        with self._lock:
            self._last = []
            self._remove()


@dataclass
class Leftover:
    proc: psutil.Process
    pgid: int
    target: str
    cmd: str
    record: str  # the record file it came from
    ticks: Optional[int] = None  # start time in ticks when found: the identity we signal

    def same_process(self) -> bool:
        if self.ticks is not None:
            return start_ticks(self.proc.pid) == self.ticks
        try:
            return self.proc.is_running()
        except psutil.Error:
            return False

    def to_dict(self) -> Dict[str, Any]:
        return {'pid': self.proc.pid, 'pgid': self.pgid, 'target': self.target, 'cmd': self.cmd}


def _same_start(proc: psutil.Process, entry: Dict[str, Any]) -> bool:
    ticks = entry.get('start_ticks')
    if ticks is not None:
        return start_ticks(proc.pid) == int(ticks)
    return abs(proc.create_time() - float(entry['create_time'])) <= TIME_TOLERANCE_SEC


def _matches(entry: Dict[str, Any]) -> Optional[psutil.Process]:
    try:
        proc = psutil.Process(int(entry['pid']))
        if not _same_start(proc, entry):
            return None
        if proc.status() == psutil.STATUS_ZOMBIE:
            return None
        if cmd_hash(proc.cmdline()) != entry.get('cmd_hash'):
            return None
        return proc
    except (psutil.Error, KeyError, TypeError, ValueError):
        return None


def _load(path: str) -> Optional[Dict[str, Any]]:
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            return None
        with open(path, encoding='utf-8') as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get('processes'), list):
        return None
    return data


def _server_alive(server: Any, own_pid: int) -> bool:
    if not isinstance(server, dict) or int(server.get('pid') or 0) == own_pid:
        return False
    return _matches(server) is not None if 'create_time' in server else False


def find_leftovers(data_dir: str, own_pid: Optional[int] = None,
                   remove_stale: bool = True) -> List[Leftover]:
    """Processes recorded by servers that are gone, still matching their fingerprint."""
    own_pid = own_pid or os.getpid()
    directory = records_dir(data_dir)
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return []
    found: Dict[int, Leftover] = {}
    for name in names:
        if not FILE_RE.match(name) or name == f'procs-{own_pid}.json':
            continue  # not a record, or this server's own (live) record
        path = os.path.join(directory, name)
        data = _load(path)
        if data is None or _server_alive(data.get('server'), own_pid):
            continue
        before = len(found)
        for entry in data['processes'][:MAX_ENTRIES]:
            proc = _matches(entry) if isinstance(entry, dict) else None
            if proc is None or proc.pid in found or proc.pid == own_pid:
                continue
            found[proc.pid] = Leftover(proc, int(entry.get('pgid') or proc.pid),
                                       str(entry.get('target') or ''), str(entry.get('cmd') or ''),
                                       path, start_ticks(proc.pid))
        if len(found) == before and remove_stale:
            _unlink(path)  # nothing of it is left
    _add_descendants(found)
    return sorted(found.values(), key=lambda l: (l.target, l.proc.pid))


def _add_descendants(found: Dict[int, Leftover]) -> None:
    """Children started by a recorded process after the last record update."""
    for leftover in list(found.values()):
        try:
            children = leftover.proc.children(recursive=True)
        except psutil.Error:
            continue
        for child in children:
            if child.pid in found:
                continue
            try:
                cmd = ' '.join(child.cmdline())[:CMD_TEXT_LEN]
                pgid = os.getpgid(child.pid)
            except (psutil.Error, OSError):
                continue
            found[child.pid] = Leftover(child, pgid, leftover.target, cmd, leftover.record,
                                        start_ticks(child.pid))


def _unlink(path: str) -> None:
    try:
        os.unlink(path)
    except OSError:
        pass


def _alive(leftover: Leftover) -> bool:
    try:
        return leftover.same_process() and leftover.proc.status() != psutil.STATUS_ZOMBIE
    except psutil.Error:
        return False


def _signal(leftover: Leftover, sig: int) -> None:
    if not leftover.same_process():  # same start time: never a reused PID
        return
    try:
        os.kill(leftover.proc.pid, sig)
    except OSError:
        pass


def stop_leftovers(leftovers: Sequence[Leftover],
                   steps: Sequence[Tuple[int, float]] = STOP_STEPS,
                   report: Callable[[str], None] = lambda line: None) -> Dict[str, Any]:
    """SIGINT -> SIGTERM -> SIGKILL, group by group (all groups at once), then tidy the files."""
    groups: Dict[int, List[Leftover]] = {}
    for leftover in leftovers:
        groups.setdefault(leftover.pgid, []).append(leftover)
    remaining = [l for l in leftovers if _alive(l)]
    for sig, timeout in steps:
        if not remaining:
            break
        for pgid, members in groups.items():
            alive = [m for m in members if m in remaining]
            if alive:
                report(f'{signal.Signals(sig).name} -> group {pgid}: '
                       + ', '.join(f'pid {m.proc.pid} ({m.target})' for m in alive))
            for member in alive:
                _signal(member, sig)
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            remaining = [l for l in remaining if _alive(l)]
            if not remaining:
                break
            time.sleep(POLL_SEC)
    survivors = [l for l in leftovers if _alive(l)]
    for record in {l.record for l in leftovers}:
        if not any(l.record == record for l in survivors):
            _unlink(record)
    return {'stopped': [l.to_dict() for l in leftovers if l not in survivors],
            'survivors': [l.to_dict() for l in survivors]}


def describe(leftovers: Sequence[Leftover]) -> Dict[str, Any]:
    alive = [l for l in leftovers if _alive(l)]
    return {'count': len(alive), 'processes': [l.to_dict() for l in alive]}
