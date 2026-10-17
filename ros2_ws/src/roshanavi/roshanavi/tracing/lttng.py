"""Thin wrapper over the ``lttng`` command line and the session daemon (user space only).

No kernel tracing and no root: the session daemon is started with
``--no-kernel``. A daemon that is already running (the user's own, or one
left by another roshanavi) is reused and never stopped; one this module
started is stopped on :meth:`Lttng.close`, and is also tied to this process
with ``PR_SET_PDEATHSIG`` so it cannot outlive a SIGKILLed worker.
"""

import ctypes
import logging
import os
import re
import shutil
import signal
import subprocess
import time
import xml.etree.ElementTree as ET
from typing import Callable, Dict, Iterable, List, Optional, Sequence

import psutil

from .config import ChannelSize

LOG = logging.getLogger(__name__)

CMD_TIMEOUT_SEC = 15.0
SESSIOND_READY_SEC = 10.0
SESSIOND_STOP_SEC = 5.0
SESSIOND_EXIT_WAIT_SEC = 8.0   # a daemon that is shutting down is waited for, not duplicated
_READABLE = re.compile(r'is now readable at (\S+)')
_PR_SET_PDEATHSIG = 1


class LttngError(Exception):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def tools_installed() -> bool:
    return shutil.which('lttng') is not None and shutil.which('lttng-sessiond') is not None


def _die_with_parent() -> None:  # runs in the child between fork and exec
    try:
        ctypes.CDLL(None).prctl(_PR_SET_PDEATHSIG, signal.SIGTERM)
    except (OSError, AttributeError):
        pass


def _strip_ns(tag: str) -> str:
    return tag.rsplit('}', 1)[-1]


class Lttng:
    def __init__(self, timeout: float = CMD_TIMEOUT_SEC):
        self._timeout = timeout
        self._sessiond: Optional[subprocess.Popen] = None

    # -- low level -----------------------------------------------------------------
    def run(self, args: Sequence[str], timeout: Optional[float] = None) -> str:
        try:
            proc = subprocess.run(['lttng', *args], capture_output=True, text=True,
                                  timeout=timeout or self._timeout, stdin=subprocess.DEVNULL)
        except FileNotFoundError as exc:
            raise LttngError('not_installed', 'lttng is not installed') from exc
        except subprocess.TimeoutExpired as exc:
            raise LttngError('timeout', f'lttng {args[0]} timed out') from exc
        except OSError as exc:  # e.g. EMFILE / ENOMEM at fork or pipe(): never escapes as a crash
            raise LttngError('os_error', f'lttng {args[0]}: {exc}') from exc
        if proc.returncode != 0:
            text = (proc.stderr or proc.stdout).strip().splitlines()
            message = text[-1] if text else f'exit code {proc.returncode}'
            code = 'no_sessiond' if 'No session daemon' in message else 'command_failed'
            raise LttngError(code, f'lttng {args[0]}: {message}')
        return proc.stdout

    def _mi(self, args: Sequence[str]) -> ET.Element:
        out = self.run(['--mi', 'xml', *args])
        try:
            return ET.fromstring(out)
        except ET.ParseError as exc:
            raise LttngError('bad_output', f'lttng {args[0]}: unreadable MI output') from exc

    # -- session daemon --------------------------------------------------------------
    def sessiond_alive(self) -> bool:
        try:
            self.run(['list'], timeout=5.0)
            return True
        except LttngError as exc:
            if exc.code == 'no_sessiond':
                return False
            raise

    @property
    def owns_sessiond(self) -> bool:
        return self._sessiond is not None and self._sessiond.poll() is None

    @property
    def sessiond_pid(self) -> Optional[int]:
        return self._sessiond.pid if self.owns_sessiond else None

    def ensure_sessiond(self) -> None:
        """Reuse a running daemon, otherwise start one owned by this process."""
        if self.sessiond_alive():
            return
        self._wait_for_dying_sessiond()
        if self.sessiond_alive():
            return
        try:
            self._sessiond = subprocess.Popen(
                ['lttng-sessiond', '--no-kernel'], stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                preexec_fn=_die_with_parent)
        except OSError as exc:
            raise LttngError('sessiond_failed', f'lttng-sessiond: {exc}') from exc
        deadline = time.monotonic() + SESSIOND_READY_SEC
        while time.monotonic() < deadline:
            if self._sessiond.poll() is not None:
                raise LttngError('sessiond_failed',
                                 f'lttng-sessiond exited with {self._sessiond.returncode}')
            if self.sessiond_alive():
                LOG.info('tracing: started lttng-sessiond pid %d', self._sessiond.pid)
                return
            time.sleep(0.1)
        raise LttngError('sessiond_failed', 'lttng-sessiond did not become ready')

    @staticmethod
    def _own_sessiond_pids() -> List[int]:
        return [p.pid for p in psutil.process_iter(['name', 'uids'])
                if p.info.get('name') == 'lttng-sessiond'
                and getattr(p.info.get('uids'), 'real', None) == os.getuid()]

    def _wait_for_dying_sessiond(self) -> None:
        """A previous worker's daemon (SIGTERMed by PR_SET_PDEATHSIG) may still be exiting.

        Starting a second one next to it left two sessiond / consumerd pairs behind.
        """
        deadline = time.monotonic() + SESSIOND_EXIT_WAIT_SEC
        while self._own_sessiond_pids() and time.monotonic() < deadline:
            if self.sessiond_alive():
                return
            time.sleep(0.2)

    def close(self) -> None:
        proc, self._sessiond = self._sessiond, None
        if proc is None or proc.poll() is not None:
            return
        proc.send_signal(signal.SIGTERM)  # the daemon stops its consumer daemons itself
        try:
            proc.wait(timeout=SESSIOND_STOP_SEC)
        except subprocess.TimeoutExpired:
            LOG.warning('tracing: lttng-sessiond ignored SIGTERM; killing it')
            proc.kill()
            proc.wait(timeout=SESSIOND_STOP_SEC)

    # -- sessions --------------------------------------------------------------------
    def create(self, name: str, output_dir: str, channel: str, size: ChannelSize,
               events: Iterable[str], contexts: Iterable[str],
               filtered: Optional[Dict[str, str]] = None) -> int:
        """Create, configure and start a user-space session with per-UID buffers.

        ``filtered`` maps an event name to its own filter expression. Returns the
        CLOCK_MONOTONIC time (ns) taken just before ``lttng start``: recording
        begins before that command returns, so this is the start of the data.
        """
        self.run(['create', name, f'--output={output_dir}'])
        try:
            self.run(['enable-channel', '-u', '-s', name, channel, '--buffers-uid',
                      f'--subbuf-size={size.subbuf_bytes}', f'--num-subbuf={size.subbuf_count}'])
            plain = [e for e in events if e not in (filtered or {})]
            if plain:
                self.run(['enable-event', '-u', '-s', name, '-c', channel, ','.join(plain)])
            for event, expression in (filtered or {}).items():
                self.run(['enable-event', '-u', '-s', name, '-c', channel, event,
                          '--filter', expression])
            ctx_args: List[str] = []
            for ctx in contexts:
                ctx_args += ['-t', ctx]
            self.run(['add-context', '-u', '-s', name, '-c', channel, *ctx_args])
            started = time.monotonic_ns()
            self.run(['start', name])
        except LttngError:
            self.destroy(name)
            raise
        return started

    def rotate(self, name: str) -> Optional[str]:
        """Close the current trace chunk and wait; returns the archived chunk directory."""
        out = self.run(['rotate', name])
        match = _READABLE.search(out)
        return match.group(1) if match else None

    def request_rotation(self, name: str) -> bool:
        """Ask for a rotation without waiting (completes 0.3–1 s later into ``archives/``).

        False when the previous one is still pending.
        """
        try:
            self.run(['rotate', '--no-wait', name])
        except LttngError as exc:
            if 'already pending' in str(exc):
                return False
            raise
        return True

    def destroy(self, name: str) -> None:
        try:
            self.run(['destroy', name])
        except LttngError as exc:
            LOG.debug('tracing: destroy %s: %s', name, exc)

    def sessions(self) -> List[str]:
        root = self._mi(['list'])
        return [child.text or '' for el in root.iter() if _strip_ns(el.tag) == 'session'
                for child in el if _strip_ns(child.tag) == 'name']

    def discarded(self, name: str) -> int:
        """Events LTTng dropped because a ring buffer was full (cumulative, all channels)."""
        root = self._mi(['list', name])
        total = 0
        for el in root.iter():
            if _strip_ns(el.tag) == 'discarded_events' and (el.text or '').isdigit():
                total += int(el.text)
        return total


def destroy_stale_sessions(lttng: Lttng, owner_of: Callable[[str], Optional[int]]) -> List[str]:
    """Destroy ``roshanavi-<pid>-…`` sessions whose server pid is gone (e.g. SIGKILL)."""
    removed = []
    try:
        names = lttng.sessions()
    except LttngError as exc:
        LOG.debug('tracing: cannot list sessions: %s', exc)
        return removed
    for name in names:
        pid = owner_of(name)
        if pid is None or pid == os.getpid() or _pid_alive(pid):
            continue
        lttng.destroy(name)
        removed.append(name)
    return removed


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True
