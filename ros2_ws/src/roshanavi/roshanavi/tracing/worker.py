"""Tracing worker: a child process of the server that owns the LTTng sessions.

Run as ``python3 -m roshanavi.tracing.worker --prefix … --out …``. Parsing is
CPU heavy (babeltrace2 in Python), so it runs here instead of in the server:
the server's asyncio loop and rclpy executor never share a GIL with it.

Protocol (one JSON object per line):

* stdin  ``{"cmd": "enable", "exclude_pids": [...]}`` / ``{"cmd": "disable"}`` /
  ``{"cmd": "quit"}``; EOF on stdin (the server died) also quits.
* stdout ``{"type": "ready" | "state" | "snapshot" | "error", ...}``.

Every period (1 s while measuring, 5 s otherwise) each session is rotated, the
closed chunk is parsed into :class:`TraceModel` and deleted at once, so disk
use stays at about one chunk.
"""

import argparse
import json
import logging
import os
import queue
import resource
import shutil
import signal
import sys
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional

from . import config
from .lttng import Lttng, LttngError, destroy_stale_sessions
from .model import TraceModel
from .reader import ChunkInfo, read_chunk

LOG = logging.getLogger('roshanavi.tracing.worker')

ACTIVE_PERIOD_SEC = 1.0
IDLE_PERIOD_SEC = 5.0
MAX_CHUNK_BYTES = 64 * config.MIB   # a bigger chunk is dropped unparsed (counted as skipped)
FORGET_EVERY_SEC = 10.0
RECOVER_EVERY_SEC = 10.0


def dir_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def shm_free(path: str = '/dev/shm') -> Optional[int]:
    try:
        st = os.statvfs(path)
    except OSError:
        return None
    return st.f_bavail * st.f_frsize


def _chunk_index(name: str) -> int:
    """``<begin>-<end>-<index>`` -> index (chunks must be read in order)."""
    tail = name.rsplit('-', 1)[-1]
    return int(tail) if tail.isdigit() else -1


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Worker:
    def __init__(self, prefix: str, out_dir: str, rt_per_cpu: int, emit: Any,
                 lttng: Optional[Lttng] = None):
        self.prefix, self.out_dir, self._rt_per_cpu = prefix, out_dir, rt_per_cpu
        self._emit = emit
        self.lttng = lttng or Lttng()
        self.model = TraceModel()
        self.init_name = config.session_name(prefix, 'init')
        self.rt_name = config.session_name(prefix, 'rt')
        self.active_since: Optional[int] = None
        self.rt_size: Optional[config.ChannelSize] = None
        self._events_total = 0
        self._discarded_trace = 0
        self._discarded_lttng = 0
        self._skipped_chunks = 0
        self._parse_errors = 0
        self._issued: Dict[str, Deque[int]] = {}    # rotation request times, per session
        self._chunk_end: Dict[str, int] = {}         # end time of the last parsed chunk
        self._last_cycle: Optional[float] = None
        self._last_forget = 0.0
        self._last_recover = 0.0
        self._usage = self._cpu_seconds()
        self._usage_at = time.monotonic()

    # -- sessions --------------------------------------------------------------------
    def start(self) -> None:
        self.lttng.ensure_sessiond()
        destroy_stale_sessions(self.lttng, config.stale_owner_pid)
        self._create_init()

    def _create_init(self) -> None:
        self.lttng.destroy(self.init_name)
        shutil.rmtree(os.path.join(self.out_dir, 'init'), ignore_errors=True)
        self._issued.pop(self.init_name, None)
        self.lttng.create(self.init_name, os.path.join(self.out_dir, 'init'), 'init',
                          config.init_channel_size(), config.INIT_EVENTS, config.INIT_CONTEXTS)

    def enable(self, exclude_pids: List[int]) -> None:
        if self.active_since is not None:
            return
        size = config.rt_channel_size(config.possible_cpus(), shm_free(), self._rt_per_cpu)
        excl = config.exclude_filter(exclude_pids)
        filtered = {config.TAKE_EVENT: config.take_filter(exclude_pids)}
        if excl:
            filtered.update({event: excl for event in config.RT_EVENTS})
        self.lttng.destroy(self.rt_name)
        shutil.rmtree(os.path.join(self.out_dir, 'rt'), ignore_errors=True)
        started = self.lttng.create(self.rt_name, os.path.join(self.out_dir, 'rt'), 'rt', size,
                                    (config.TAKE_EVENT, *config.RT_EVENTS), config.RT_CONTEXTS,
                                    filtered=filtered)
        self._issued.pop(self.rt_name, None)
        self._chunk_end.pop(self.rt_name, None)
        self._last_cycle = None
        self.rt_size = size
        self.active_since = started
        self._discarded_trace = self._discarded_lttng = 0

    def disable(self) -> None:
        if self.active_since is None:
            return
        self.lttng.destroy(self.rt_name)
        shutil.rmtree(os.path.join(self.out_dir, 'rt'), ignore_errors=True)
        self.active_since = None
        self.model.clear_rates()

    def close(self) -> None:
        try:
            self.lttng.destroy(self.rt_name)
            self.lttng.destroy(self.init_name)
        finally:  # the daemon this worker started must go even when destroying failed
            self.lttng.close()
            shutil.rmtree(self.out_dir, ignore_errors=True)

    # -- one rotation ------------------------------------------------------------------
    def _archives(self, kind: str) -> List[str]:
        """Completed chunks of a session, oldest first (LTTng moves them in when done)."""
        root = os.path.join(self.out_dir, kind, 'archives')
        try:
            names = os.listdir(root)
        except FileNotFoundError:
            return []
        return [os.path.join(root, n) for n in sorted(names, key=_chunk_index)]

    def _parse(self, path: str) -> int:
        info = ChunkInfo()
        try:
            if dir_bytes(path) > MAX_CHUNK_BYTES:
                self._skipped_chunks += 1
                LOG.warning('tracing: chunk %s too large; dropped unparsed', path)
            else:
                self.model.feed(read_chunk(path, info))
        except Exception as exc:  # a corrupt chunk must not stop measuring
            self._parse_errors += 1
            LOG.warning('tracing: cannot read chunk %s: %s', path, exc)
        finally:
            shutil.rmtree(path, ignore_errors=True)
        self._discarded_trace += info.discarded
        return info.events

    def _consume(self, name: str, kind: str) -> int:
        """Parse and delete the completed chunks; returns the number of events."""
        issued = self._issued.setdefault(name, deque())
        events = 0
        for path in self._archives(kind):
            events += self._parse(path)
            if issued:  # one chunk per rotation, in order: its end time
                self._chunk_end[name] = issued.popleft()
        if self.lttng.request_rotation(name):
            issued.append(time.monotonic_ns())
        return events

    def cycle(self, emit: bool = True) -> None:
        started = time.monotonic()
        try:
            events = self._consume(self.init_name, 'init')
            if self.active_since is not None:
                events += self._consume(self.rt_name, 'rt')
                self._discarded_lttng = self.lttng.discarded(self.rt_name)
        except LttngError as exc:
            self._on_lttng_error(exc)
            return
        self._events_total += events
        if time.monotonic() - self._last_forget >= FORGET_EVERY_SEC:
            self._last_forget = time.monotonic()
            self.model.forget_processes({p for p in self.model.pids() if _alive(p)})
        if not emit:
            return
        # Rates end where the last parsed rt chunk ends (data after it is not read yet).
        end = self._chunk_end.get(self.rt_name, self.active_since) \
            if self.active_since is not None else time.monotonic_ns()
        now = time.monotonic()
        elapsed = None if self._last_cycle is None else now - self._last_cycle
        self._last_cycle = now if self.active_since is not None else None
        self._emit({'type': 'snapshot', **self._status(events, elapsed, started),
                    **self.model.snapshot(end, self.active_since)})

    def _status(self, events: int, elapsed: Optional[float], started: float) -> Dict[str, Any]:
        rate = None if not elapsed or elapsed <= 0 or self.active_since is None \
            else round(events / elapsed, 1)
        return {'active': self.active_since is not None, 'events_per_sec': rate,
                'events_total': self._events_total,
                'discarded': max(self._discarded_lttng, self._discarded_trace),
                'skipped_chunks': self._skipped_chunks, 'parse_errors': self._parse_errors,
                'parse_ms': round((time.monotonic() - started) * 1000, 1),
                'disk_bytes': dir_bytes(self.out_dir), 'cpu_percent': self._cpu_percent(),
                'buffer_per_cpu': self.rt_size.per_cpu if self.rt_size else None}

    def _on_lttng_error(self, exc: LttngError) -> None:
        self._emit({'type': 'error', 'code': exc.code, 'message': str(exc)})
        if time.monotonic() - self._last_recover < RECOVER_EVERY_SEC:
            return
        self._last_recover = time.monotonic()
        was_active = self.active_since is not None
        try:  # the session daemon may have died: start again (nodes must then restart)
            self.lttng.ensure_sessiond()
            self._create_init()
            self.active_since = None
            if was_active:
                self.enable([])
        except (LttngError, config.ShmTooSmall) as again:
            LOG.error('tracing: recovery failed: %s', again)

    @staticmethod
    def _cpu_seconds() -> float:
        own = resource.getrusage(resource.RUSAGE_SELF)
        kids = resource.getrusage(resource.RUSAGE_CHILDREN)  # the lttng CLI calls
        return own.ru_utime + own.ru_stime + kids.ru_utime + kids.ru_stime

    def _cpu_percent(self) -> float:
        now, usage = time.monotonic(), self._cpu_seconds()
        span = max(now - self._usage_at, 1e-3)
        percent = (usage - self._usage) / span * 100.0
        self._usage, self._usage_at = usage, now
        return round(percent, 1)

    @property
    def period(self) -> float:
        return ACTIVE_PERIOD_SEC if self.active_since is not None else IDLE_PERIOD_SEC


def _stdin_reader(commands: 'queue.Queue[Dict[str, Any]]') -> None:
    for line in sys.stdin:
        try:
            commands.put(json.loads(line))
        except ValueError:
            LOG.warning('tracing: ignored malformed command %r', line[:80])
    commands.put({'cmd': 'quit'})  # EOF: the server is gone


def _handle(worker: Worker, cmd: Dict[str, Any], emit: Any) -> bool:
    """Run one command; False means quit."""
    name = cmd.get('cmd')
    if name == 'quit':
        return False
    try:
        if name == 'enable':
            worker.enable([int(p) for p in cmd.get('exclude_pids') or []])
        elif name == 'disable':
            worker.disable()
        emit({'type': 'state', 'active': worker.active_since is not None, 'error': None})
    except config.ShmTooSmall as exc:
        emit({'type': 'state', 'active': False, 'error': 'shm_too_small', 'message': str(exc)})
    except LttngError as exc:
        emit({'type': 'state', 'active': worker.active_since is not None, 'error': exc.code,
              'message': str(exc)})
    return True


def run(worker: Worker, emit: Any) -> None:
    commands: 'queue.Queue[Dict[str, Any]]' = queue.Queue()
    threading.Thread(target=_stdin_reader, args=(commands,), daemon=True).start()
    signal.signal(signal.SIGTERM, lambda *_: commands.put({'cmd': 'quit'}))
    parent = os.getppid()
    next_cycle = time.monotonic() + worker.period
    while True:
        try:
            cmd = commands.get(timeout=max(0.0, next_cycle - time.monotonic()))
        except queue.Empty:
            if os.getppid() != parent:
                return
            worker.cycle()
            next_cycle = time.monotonic() + worker.period
            continue
        if not _handle(worker, cmd, emit):
            return
        next_cycle = min(next_cycle, time.monotonic() + worker.period)


def _emitter() -> Any:
    lock = threading.Lock()

    def emit(obj: Dict[str, Any]) -> None:
        with lock:
            try:
                sys.stdout.write(json.dumps(obj, separators=(',', ':')) + '\n')
                sys.stdout.flush()
            except BrokenPipeError:
                os._exit(0)  # the server is gone; sessions are cleaned by the next start
    return emit


def _raise_fd_limit() -> None:
    """Headroom for the lttng CLI pipes and bt2 file handles (the soft limit is often 1024)."""
    soft, hard = resource.getrlimit(resource.RLIMIT_NOFILE)
    want = hard if hard != resource.RLIM_INFINITY else 65536
    if soft < want:
        try:
            resource.setrlimit(resource.RLIMIT_NOFILE, (min(want, 65536), hard))
        except (ValueError, OSError):
            pass


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog='roshanavi tracing worker')
    parser.add_argument('--prefix', required=True)
    parser.add_argument('--out', required=True)
    parser.add_argument('--rt-per-cpu', type=int, default=config.DEFAULT_RT_PER_CPU)
    args = parser.parse_args(argv)
    logging.basicConfig(level='INFO', stream=sys.stderr,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    _raise_fd_limit()
    emit = _emitter()
    worker = Worker(args.prefix, args.out, args.rt_per_cpu, emit)
    try:
        worker.start()
    except LttngError as exc:
        emit({'type': 'error', 'code': exc.code, 'message': str(exc), 'fatal': True})
        worker.close()
        return 1
    emit({'type': 'ready', 'owns_sessiond': worker.lttng.owns_sessiond,
          'sessiond_pid': worker.lttng.sessiond_pid})
    try:
        run(worker, emit)
    finally:
        worker.close()
    return 0


if __name__ == '__main__':
    sys.exit(main())
