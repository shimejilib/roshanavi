"""The C++ measurement probe (``roshanavi_probe``) as a managed child process.

Started directly (not via ``ros2 run``) in its own session so it can be
signalled as a group; restarted with a growing back-off when it exits. The
probe itself exits when its parent (this server) goes away, so even SIGKILL
of the server leaves no orphan behind for longer than one probe period.
"""

import logging
import os
import signal
import subprocess
import time
from typing import Callable, List, Optional, Sequence

LOG = logging.getLogger(__name__)

PROBE_PACKAGE = 'roshanavi_probe'
PROBE_EXECUTABLE = 'probe'
BACKOFF_SEC = (1.0, 2.0, 4.0, 8.0, 16.0, 30.0)
GIVE_UP_AFTER = 5  # consecutive crashes without a healthy period in between
STOP_TIMEOUT_SEC = 3.0
# Statistics only count as "healthy" after this long up: a probe that crashes a few
# seconds after every start must still reach GIVE_UP_AFTER.
HEALTHY_AFTER_SEC = 30.0

Clock = Callable[[], float]


def find_probe_executable() -> Optional[str]:
    """Path of the built probe, or None when the package is not built / sourced."""
    try:
        from ament_index_python.packages import PackageNotFoundError, get_package_prefix
    except ImportError:  # pragma: no cover - always present with rclpy
        return None
    try:
        prefix = get_package_prefix(PROBE_PACKAGE)
    except PackageNotFoundError:
        return None
    path = os.path.join(prefix, 'lib', PROBE_PACKAGE, PROBE_EXECUTABLE)
    return path if os.access(path, os.X_OK) else None


class ProbeProcess:
    """Owns one probe process; ``poll()`` (housekeeping, 1 s) restarts it when it died."""

    def __init__(self, executable: str, instance: str, clock: Clock = time.monotonic,
                 backoff: Sequence[float] = BACKOFF_SEC, give_up_after: int = GIVE_UP_AFTER,
                 extra_args: Sequence[str] = ()):
        self._argv: List[str] = [executable, '--ros-args', '-p', f'instance:={instance}',
                                 *extra_args]
        self._clock = clock
        self._backoff = tuple(backoff)
        self._give_up_after = give_up_after
        self._proc: Optional[subprocess.Popen] = None
        self._crashes = 0  # consecutive, reset by mark_healthy()
        self._restart_at: Optional[float] = None
        self._started_at: Optional[float] = None
        self.restarts = 0
        self.last_exit: Optional[int] = None
        self.gave_up = False

    @property
    def pid(self) -> Optional[int]:
        return self._proc.pid if self._proc is not None and self._proc.poll() is None else None

    @property
    def state(self) -> str:
        if self.gave_up:
            return 'failed'
        if self.pid is not None:
            return 'running'
        return 'restarting' if self._restart_at is not None else 'stopped'

    def start(self) -> None:
        if self.pid is not None:
            return
        try:
            self._proc = subprocess.Popen(self._argv, start_new_session=True,
                                          stdin=subprocess.DEVNULL)
        except OSError as exc:
            LOG.error('probe: cannot start %s: %s', self._argv[0], exc)
            self._proc = None
            self._on_exit(-1)
            return
        self._restart_at = None
        self._started_at = self._clock()
        LOG.info('probe: started pid %d', self._proc.pid)

    def mark_healthy(self) -> None:
        """Statistics arrived: once up long enough, the next crash restarts the back-off."""
        if self._started_at is not None and self._clock() - self._started_at >= HEALTHY_AFTER_SEC:
            self._crashes = 0

    def uptime(self) -> Optional[float]:
        return None if self.pid is None or self._started_at is None \
            else self._clock() - self._started_at

    def restart_hung(self) -> None:
        """Alive but silent: stop it and let ``poll`` restart it (counts as a crash)."""
        LOG.warning('probe: no statistics from pid %s; restarting it', self.pid)
        self._kill_group(signal.SIGKILL)

    def poll(self) -> None:
        if self.gave_up:
            return
        if self._proc is not None:
            code = self._proc.poll()
            if code is None:
                return
            self._proc = None
            self._on_exit(code)
        if self._restart_at is not None and self._clock() >= self._restart_at:
            self.restarts += 1
            self.start()

    def _on_exit(self, code: int) -> None:
        self.last_exit = code
        self._crashes += 1
        if self._crashes >= self._give_up_after:
            LOG.error('probe: exited %d times in a row (last code %s); giving up',
                      self._crashes, code)
            self.gave_up = True
            self._restart_at = None
            return
        delay = self._backoff[min(self._crashes - 1, len(self._backoff) - 1)]
        LOG.warning('probe: exited with code %s; restarting in %.0f s', code, delay)
        self._restart_at = self._clock() + delay

    def kill(self) -> None:
        """Test hook / crash simulation: SIGKILL the running probe."""
        self._kill_group(signal.SIGKILL)

    def _kill_group(self, sig: int) -> None:
        pid = self.pid
        if pid is None:
            return
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass

    def stop(self) -> None:
        self._restart_at = None
        proc, self._proc = self._proc, None
        if proc is None or proc.poll() is not None:
            return
        try:
            os.killpg(proc.pid, signal.SIGTERM)
            proc.wait(timeout=STOP_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            LOG.warning('probe: did not stop on SIGTERM; killing')
            try:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=STOP_TIMEOUT_SEC)
            except (ProcessLookupError, subprocess.TimeoutExpired) as exc:
                LOG.error('probe: could not reap pid %d: %s', proc.pid, exc)
        except ProcessLookupError:
            pass
