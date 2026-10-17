"""Server side of 詳細計測モード: the tracing worker's lifecycle and its latest results.

``--tracing auto`` (default): when lttng-tools and python3-bt2 are installed the
worker starts with the server and records only the per-node init events (no
per-message cost); 詳細計測モード (``enable``) adds the per-message session.
``--tracing off`` never starts it. Reasons are reported in :meth:`status`.
"""

import importlib.util
import json
import logging
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional

import psutil

from ..api_errors import ApiError
from . import config
from .lttng import tools_installed

LOG = logging.getLogger(__name__)

TRACING_AUTO = 'auto'
TRACING_OFF = 'off'
TRACING_MODES = (TRACING_AUTO, TRACING_OFF)
READY_TIMEOUT_SEC = 20.0
COMMAND_TIMEOUT_SEC = 20.0
STOP_TIMEOUT_SEC = 10.0
RESTART_DELAY_SEC = 5.0
MAX_RESTARTS = 3
SNAPSHOT_STALE_SEC = 8.0
LTTNG_DAEMONS = ('lttng-sessiond', 'lttng-consumerd')


class TracingError(ApiError):
    pass


def bt2_installed() -> bool:
    return importlib.util.find_spec('bt2') is not None


def availability() -> Optional[str]:
    """None when tracing can run, else ``not_installed`` / ``bt2_missing``."""
    if not tools_installed():
        return 'not_installed'
    return None if bt2_installed() else 'bt2_missing'


class _Cpu:
    """CPU % of roshanavi's own processes, sampled once per housekeeping tick."""

    def __init__(self) -> None:
        self._procs: Dict[int, psutil.Process] = {}
        self.values: Dict[str, Optional[float]] = {'server': None, 'worker': None, 'lttng': None}

    def _percent(self, pid: Optional[int]) -> Optional[float]:
        if pid is None:
            return None
        proc = self._procs.get(pid)
        try:
            if proc is None:
                proc = self._procs[pid] = psutil.Process(pid)
                proc.cpu_percent(None)  # first call only primes the counter
                return None
            return proc.cpu_percent(None)
        except psutil.Error:
            self._procs.pop(pid, None)
            return None

    def sample(self, worker_pid: Optional[int]) -> None:
        daemons = [p.pid for p in psutil.process_iter(['name'])
                   if (p.info.get('name') or '') in LTTNG_DAEMONS]
        lttng = [v for v in (self._percent(pid) for pid in daemons) if v is not None]
        self.values = {'server': self._percent(os.getpid()), 'worker': self._percent(worker_pid),
                       'lttng': round(sum(lttng), 1) if daemons else None}
        live = {os.getpid(), worker_pid, *daemons}
        for pid in [p for p in self._procs if p not in live]:
            del self._procs[pid]


class TracingService:
    def __init__(self, mode: str = TRACING_OFF, rt_per_cpu: int = config.DEFAULT_RT_PER_CPU,
                 check: Callable[[], Optional[str]] = availability,
                 clock: Callable[[], float] = time.monotonic):
        if mode not in TRACING_MODES:
            raise ValueError(f'tracing must be one of {TRACING_MODES}')
        self._mode, self._rt_per_cpu, self._check, self._clock = mode, rt_per_cpu, check, clock
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._ready = threading.Event()
        self._reply: Optional[Dict[str, Any]] = None
        self._reply_event = threading.Event()
        self._command_lock = threading.Lock()
        self._snapshot: Optional[Dict[str, Any]] = None
        self._snapshot_at = 0.0
        self._error: Optional[Dict[str, Any]] = None
        self._reason: Optional[str] = 'disabled' if mode == TRACING_OFF else None
        self._active = False
        self._active_since: Optional[float] = None
        self._started_at: Optional[float] = None  # init capture start (monotonic)
        self._started_wall: Optional[float] = None
        self._restarts = 0
        self._restart_at: Optional[float] = None
        self._closing = False
        self._cpu = _Cpu()
        self.out_dir: Optional[str] = None
        # Fixed for the server's lifetime: a restarted worker replaces its sessions by name.
        self.prefix = f'roshanavi-{os.getpid()}-{uuid.uuid4().hex[:8]}'

    # -- lifecycle -------------------------------------------------------------------
    def start(self) -> None:
        if self._mode == TRACING_OFF:
            return
        reason = self._check()
        if reason is not None:
            self._reason = reason
            LOG.info('tracing: unavailable (%s)', reason)
            return
        self._spawn()

    def _spawn(self) -> None:
        self.out_dir = tempfile.mkdtemp(prefix='roshanavi-trace-')
        argv = [sys.executable, '-m', 'roshanavi.tracing.worker', '--prefix', self.prefix,
                '--out', self.out_dir, '--rt-per-cpu', str(self._rt_per_cpu)]
        self._ready.clear()
        try:
            self._proc = subprocess.Popen(argv, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                          text=True, bufsize=1, start_new_session=True)
        except OSError as exc:
            self._fail('worker_failed', f'cannot start the tracing worker: {exc}')
            return
        threading.Thread(target=self._read, args=(self._proc,), name='tracing-reader',
                         daemon=True).start()
        if not self._ready.wait(READY_TIMEOUT_SEC):
            self._fail('worker_failed', 'the tracing worker did not become ready')
            return
        if self._reason is None:
            self._started_at, self._started_wall = self._clock(), time.time()
            LOG.info('tracing: recording node init events (worker pid %d)', self._proc.pid)

    def _fail(self, code: str, message: str) -> None:
        LOG.error('tracing: %s', message)
        self._error = {'code': code, 'message': message}
        self._reason = 'failed'
        self._ready.set()

    def _read(self, proc: subprocess.Popen) -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            try:
                msg = json.loads(line)
            except ValueError:
                continue
            self._on_message(msg)
        if not self._closing:
            LOG.error('tracing: worker exited (code %s)', proc.wait())
            with self._lock:
                self._active, self._active_since = False, None
                self._error = {'code': 'worker_exited', 'message': 'tracing worker exited'}
                self._restart_at = self._clock() + RESTART_DELAY_SEC
            self._reply_event.set()

    def _on_message(self, msg: Dict[str, Any]) -> None:
        kind = msg.get('type')
        if kind == 'ready':
            self._reason, self._error = None, None
            self._ready.set()
        elif kind == 'snapshot':
            with self._lock:
                self._snapshot, self._snapshot_at = msg, self._clock()
        elif kind == 'state':
            self._reply = msg
            self._reply_event.set()
        elif kind == 'error':
            LOG.warning('tracing: %s', msg.get('message'))
            with self._lock:
                self._error = {'code': msg.get('code'), 'message': msg.get('message')}
            if msg.get('fatal'):
                self._reason = 'failed'
                self._ready.set()

    def poll(self) -> None:
        """Housekeeping (1 s): CPU samples and restart of a crashed worker."""
        proc = self._proc
        self._cpu.sample(proc.pid if proc is not None and proc.poll() is None else None)
        with self._lock:
            due = self._restart_at is not None and self._clock() >= self._restart_at
            if due:
                self._restart_at = None
        if not due or self._closing:
            return
        if self._restarts >= MAX_RESTARTS:
            self._reason = 'failed'
            return
        self._restarts += 1
        self._cleanup_dir()
        self._spawn()

    def close(self) -> None:
        self._closing = True
        proc, self._proc = self._proc, None
        if proc is not None and proc.poll() is None:
            try:
                self._send(proc, {'cmd': 'quit'})
                proc.wait(timeout=STOP_TIMEOUT_SEC)
            except (OSError, subprocess.TimeoutExpired):
                LOG.warning('tracing: worker did not quit; killing it')
                proc.kill()
                proc.wait(timeout=STOP_TIMEOUT_SEC)
        self._cleanup_dir()

    def _cleanup_dir(self) -> None:
        if self.out_dir and os.path.isdir(self.out_dir):
            shutil.rmtree(self.out_dir, ignore_errors=True)

    # -- commands --------------------------------------------------------------------
    @staticmethod
    def _send(proc: subprocess.Popen, cmd: Dict[str, Any]) -> None:
        assert proc.stdin is not None
        proc.stdin.write(json.dumps(cmd) + '\n')
        proc.stdin.flush()

    def _command(self, cmd: Dict[str, Any]) -> Dict[str, Any]:
        proc = self._proc
        if self._reason is not None or proc is None or proc.poll() is not None:
            raise TracingError('tracing_unavailable', self.unavailable_message(), status=409)
        with self._command_lock:
            self._reply_event.clear()
            self._reply = None
            try:
                self._send(proc, cmd)
            except OSError as exc:
                raise TracingError('tracing_failed', f'tracing worker: {exc}', status=500)
            if not self._reply_event.wait(COMMAND_TIMEOUT_SEC) or self._reply is None:
                raise TracingError('tracing_failed', 'the tracing worker did not answer',
                                   status=500)
            return self._reply

    def set_enabled(self, enabled: bool, exclude_pids: List[int]) -> None:
        reply = self._command({'cmd': 'enable', 'exclude_pids': exclude_pids} if enabled
                              else {'cmd': 'disable'})
        with self._lock:
            self._active = bool(reply.get('active'))
            self._active_since = self._clock() if self._active else None
            self._snapshot = None
        if reply.get('error'):
            status = 507 if reply['error'] == 'shm_too_small' else 500
            raise TracingError(str(reply['error']), str(reply.get('message') or ''),
                               status=status)

    def unavailable_message(self) -> str:
        return {'disabled': 'tracing is disabled (--tracing off)',
                'not_installed': 'lttng-tools is not installed',
                'bt2_missing': 'python3-bt2 (babeltrace2) is not installed'}.get(
                    self._reason or '', 'tracing is not running')

    # -- results ---------------------------------------------------------------------
    def snapshot(self) -> Optional[Dict[str, Any]]:
        """Latest worker snapshot while 詳細計測モード is on and fresh, else None."""
        with self._lock:
            if not self._active or self._snapshot is None or not self._snapshot.get('active'):
                return None
            if self._clock() - self._snapshot_at > SNAPSHOT_STALE_SEC:
                return None
            return self._snapshot

    @property
    def active(self) -> bool:
        return self._active

    @property
    def started_wall(self) -> Optional[float]:
        """Wall time from which new nodes are mapped (processes older need a restart)."""
        return self._started_wall

    def worker_pid(self) -> Optional[int]:
        proc = self._proc
        return proc.pid if proc is not None and proc.poll() is None else None

    def status(self) -> Dict[str, Any]:
        with self._lock:
            snap, active, error = self._snapshot, self._active, self._error
            since = self._active_since
        data = snap if active and snap else {}
        cpu = dict(self._cpu.values)
        if data.get('cpu_percent') is not None:  # includes the lttng CLI calls it makes
            cpu['worker'] = data['cpu_percent']
        known = [v for v in cpu.values() if v is not None]
        cpu['total'] = round(sum(known), 1) if known else None
        return {'available': self._reason is None, 'reason': self._reason, 'active': active,
                'active_sec': None if since is None else round(self._clock() - since, 1),
                'receiving': bool(active and self.snapshot() is not None),
                'error': error, 'events_per_sec': data.get('events_per_sec'),
                'discarded': data.get('discarded', 0), 'disk_bytes': data.get('disk_bytes'),
                'parse_ms': data.get('parse_ms'), 'buffer_per_cpu': data.get('buffer_per_cpu'),
                'skipped_chunks': data.get('skipped_chunks', 0),
                'cpu_percent': cpu,
                'restarts': self._restarts}
