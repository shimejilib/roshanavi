"""One child process in its own session/process group, with streamed output.

* argv list only (never a shell), ``start_new_session=True`` so the whole
  tree (``ros2 launch`` and every node it spawns) shares one process group.
* stdout/stderr are read line by line into a :class:`LogBuffer`, tagged with
  the stream name.
* :meth:`ProcessRunner.stop` escalates SIGINT -> SIGTERM -> SIGKILL on the
  group, then kills any descendant that escaped the group.
* Linux: every child gets ``PR_SET_PDEATHSIG`` (SIGTERM), so a SIGKILLed server
  does not leave its *direct* children behind. The kernel sends that
  signal when the *thread* that forked the child ends, not the process, so all
  children are forked from one long-lived spawner thread (:func:`spawn`) --
  never from a short-lived request / autostart / timer thread. Grandchildren
  (the node under a ``ros2 run`` / ``ros2 launch`` wrapper) are not covered by
  the kernel; they are recorded (:mod:`.proc_record`) and stopped by
  ``ros2 run roshanavi cleanup`` or the leftover banner on the next start.
"""

import ctypes
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Sequence

import psutil

from .errors import LauncherError
from .logbuf import LogBuffer

LOG = logging.getLogger(__name__)

SIGINT_TIMEOUT_SEC = 5.0
SIGTERM_TIMEOUT_SEC = 3.0
KILL_TIMEOUT_SEC = 2.0
POLL_SEC = 0.05
READER_JOIN_SEC = 2.0


_PR_SET_PDEATHSIG = 1
PDEATH_SIGNAL = signal.SIGTERM


def _load_prctl() -> Optional[Callable[..., int]]:
    """libc ``prctl`` looked up once, before any fork (nothing is loaded in the child)."""
    if not sys.platform.startswith('linux'):
        return None
    try:
        return ctypes.CDLL(None, use_errno=True).prctl
    except (OSError, AttributeError):
        return None


_PRCTL = _load_prctl()
_SPAWN_LOCK = threading.Lock()
_SPAWNER: Optional[ThreadPoolExecutor] = None


def pdeathsig_preexec(parent_pid: int) -> Optional[Callable[[], None]]:
    """``preexec_fn`` that makes the child get SIGTERM when its parent (thread) dies."""
    if _PRCTL is None:
        return None

    def setup() -> None:
        _PRCTL(_PR_SET_PDEATHSIG, int(PDEATH_SIGNAL), 0, 0, 0)
        if os.getppid() != parent_pid:  # the server died between fork and prctl
            os.kill(os.getpid(), PDEATH_SIGNAL)
    return setup


def _spawner() -> ThreadPoolExecutor:
    global _SPAWNER
    with _SPAWN_LOCK:
        if _SPAWNER is None:
            _SPAWNER = ThreadPoolExecutor(max_workers=1, thread_name_prefix='roshanavi-spawn')
        return _SPAWNER


def spawn(argv: Sequence[str], **kwargs: Any) -> subprocess.Popen:
    """``subprocess.Popen`` on the long-lived spawner thread, with the parent-death signal.

    ``PR_SET_PDEATHSIG`` fires when the forking *thread* exits; request handler threads
    (anyio's pool retires idle threads), the autostart thread and auto-restart timers are
    short-lived, so forking there would kill healthy children later.
    """
    kwargs.setdefault('preexec_fn', pdeathsig_preexec(os.getpid()))
    try:
        future = _spawner().submit(subprocess.Popen, list(argv), **kwargs)
    except RuntimeError:  # interpreter shutting down: no new futures, fork here instead
        return subprocess.Popen(list(argv), **kwargs)
    return future.result()


def group_alive(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _signal_group(pgid: int, sig: int) -> None:
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass
    except PermissionError as exc:
        LOG.warning('cannot signal process group %d: %s', pgid, exc)


def descendants(pid: int) -> List[psutil.Process]:
    try:
        return psutil.Process(pid).children(recursive=True)
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return []


class ProcessRunner:
    """Spawns ``argv``; calls ``on_exit(returncode)`` from a watcher thread."""

    def __init__(self, argv: Sequence[str], env: Dict[str, str], cwd: str, log: LogBuffer,
                 on_exit: Callable[[int], None],
                 timeouts: Sequence[float] = (SIGINT_TIMEOUT_SEC, SIGTERM_TIMEOUT_SEC)):
        self.argv = list(argv)
        self._env = env
        self._cwd = cwd
        self._log = log
        self._on_exit = on_exit
        self._timeouts = tuple(timeouts)
        self._proc: Optional[subprocess.Popen] = None
        self._readers: List[threading.Thread] = []
        self._stop_lock = threading.Lock()
        self.started_at = 0.0  # time.monotonic()

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc else None

    def alive(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self) -> None:
        try:
            self._proc = spawn(
                self.argv, cwd=self._cwd, env=self._env, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True,
                text=True, encoding='utf-8', errors='replace', bufsize=1)
        except OSError as exc:
            raise LauncherError('spawn_failed', f'cannot start {self.argv[0]}: {exc}', 500) from exc
        self.started_at = time.monotonic()
        self._log.append('system', '$ ' + ' '.join(self.argv))
        for name, stream in (('stdout', self._proc.stdout), ('stderr', self._proc.stderr)):
            reader = threading.Thread(target=self._read, args=(name, stream),
                                      name=f'log-{self._proc.pid}-{name}', daemon=True)
            reader.start()
            self._readers.append(reader)
        threading.Thread(target=self._watch, name=f'watch-{self._proc.pid}', daemon=True).start()

    def _read(self, name: str, stream) -> None:
        try:
            for line in iter(stream.readline, ''):
                self._log.append(name, line)
        except (OSError, ValueError) as exc:
            LOG.debug('log reader %s ended: %s', name, exc)
        finally:
            stream.close()

    def _watch(self) -> None:
        code = self._proc.wait()
        for reader in self._readers:
            reader.join(timeout=READER_JOIN_SEC)
        self._log.append('system', f'[exit {code}]')
        try:
            self._on_exit(code)
        except Exception:  # never let a callback bug kill the watcher silently
            LOG.exception('on_exit callback failed for pid %s', self._proc.pid)

    def stop(self) -> Optional[int]:
        """Stop the whole process group; returns the leader's exit code."""
        with self._stop_lock:
            proc = self._proc
            if proc is None:
                return None
            pgid = proc.pid  # session leader: pgid == pid
            escaped = descendants(proc.pid)
            for sig, timeout in ((signal.SIGINT, self._timeouts[0]),
                                 (signal.SIGTERM, self._timeouts[1]),
                                 (signal.SIGKILL, KILL_TIMEOUT_SEC)):
                if not group_alive(pgid) and proc.poll() is not None:
                    break
                if sig != signal.SIGINT:
                    LOG.warning('pid %d did not stop, sending %s', proc.pid, sig.name)
                    self._log.append('system', f'[sending {sig.name}]')
                _signal_group(pgid, sig)
                self._wait_group(proc, pgid, timeout)
            self._kill_escaped(escaped)
            try:
                return proc.wait(timeout=KILL_TIMEOUT_SEC)
            except subprocess.TimeoutExpired:
                LOG.error('pid %d survived SIGKILL', proc.pid)
                return None

    @staticmethod
    def _wait_group(proc: subprocess.Popen, pgid: int, timeout: float) -> None:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if proc.poll() is not None and not group_alive(pgid):
                return
            time.sleep(POLL_SEC)

    @staticmethod
    def _kill_escaped(procs: List[psutil.Process]) -> None:
        for child in procs:
            try:
                if child.is_running() and child.status() != psutil.STATUS_ZOMBIE:
                    LOG.warning('killing escaped descendant pid %d', child.pid)
                    child.kill()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def tree_pids(self) -> List[int]:
        if not self.alive():
            return []
        return [self._proc.pid, *(p.pid for p in descendants(self._proc.pid))]
