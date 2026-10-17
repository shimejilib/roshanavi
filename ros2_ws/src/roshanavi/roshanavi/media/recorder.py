"""Recording with ``ros2 bag record`` (mcap) into ``data_dir/recordings/<time>_<name>/``.

One recording at a time. Stop sends SIGINT to the recorder's process group so
rosbag2 finalizes the file (writes ``metadata.yaml``); SIGTERM / SIGKILL only
if it hangs. A monitor thread watches the process and the free disk space:
below the warning threshold the status carries a warning, below the stop
threshold the recording is stopped automatically (``stop_reason: disk_full``).
Finished recordings are bag directories, so bag mode can play them directly.
"""

import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from typing import Any, Callable, Deque, Dict, List, Optional, Sequence

import yaml

from ..jobs import validate_topic
from .diskguard import DiskGuard
from .errors import MediaError

LOG = logging.getLogger(__name__)

RECORDINGS_DIR = 'recordings'
NAME_RE = re.compile(r'^[A-Za-z0-9_-]{0,40}$')
DIR_RE = re.compile(r'^\d{8}-\d{6}(_[A-Za-z0-9_-]{1,40})?(-\d{1,3})?$')
MAX_TOPICS = 100
STOP_TIMEOUTS = (10.0, 5.0)  # SIGINT -> wait -> SIGTERM -> wait -> SIGKILL
MONITOR_PERIOD_SEC = 1.0


def dir_size(path: str) -> int:
    total = 0
    for current, _, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(current, name))
            except OSError:
                continue  # file rotated away while walking
    return total


def read_metadata(path: str) -> Optional[Dict[str, Any]]:
    """Summary of a finished bag (``metadata.yaml``) or None if it is not finalized."""
    meta = os.path.join(path, 'metadata.yaml')
    try:
        with open(meta, encoding='utf-8') as fh:
            info = (yaml.safe_load(fh) or {}).get('rosbag2_bagfile_information') or {}
    except FileNotFoundError:
        return None
    except (OSError, yaml.YAMLError) as exc:
        LOG.warning('cannot read %s: %s', meta, exc)
        return None
    topics = [{'name': t.get('topic_metadata', {}).get('name'),
               'type': t.get('topic_metadata', {}).get('type'),
               'count': t.get('message_count', 0)}
              for t in info.get('topics_with_message_count') or []]
    return {'duration_sec': (info.get('duration') or {}).get('nanoseconds', 0) / 1e9,
            'started_at': (info.get('starting_time') or {}).get('nanoseconds_since_epoch', 0) / 1e9,
            'message_count': info.get('message_count', 0), 'topics': topics}


class Recorder:
    def __init__(self, data_dir: str, guard: Optional[DiskGuard] = None,
                 clock: Callable[[], float] = time.time,
                 timeouts: Sequence[float] = STOP_TIMEOUTS,
                 monitor_period: float = MONITOR_PERIOD_SEC):
        self.root = os.path.join(os.path.realpath(data_dir), RECORDINGS_DIR)
        self._data_dir = os.path.realpath(data_dir)
        self._guard = guard or DiskGuard(self._data_dir)
        self._clock = clock
        self._timeouts = tuple(timeouts)
        self._period = monitor_period
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen] = None
        self._active: Optional[Dict[str, Any]] = None
        self._last: Optional[Dict[str, Any]] = None
        self._stderr: Deque[str] = deque(maxlen=20)
        self._done = threading.Event()  # set when the current recording is finalized

    # ---- start / stop --------------------------------------------------------
    def start(self, topics: Sequence[str], name: str = '') -> Dict[str, Any]:
        topics = self._check_topics(topics)
        if not NAME_RE.match(name or ''):
            raise MediaError('invalid_request', 'name may use letters, digits, "_" and "-" '
                             '(up to 40)')
        disk = self._guard.check()
        if disk['level'] == 'stop':
            raise MediaError('disk_full', 'not enough free disk space to record', 507)
        with self._lock:
            if self._active is not None:
                raise MediaError('recording_active', 'a recording is already running', 409)
            path = self._new_dir(name)
            self._done.clear()
            argv = ['ros2', 'bag', 'record', '-s', 'mcap', '-o', path, '--topics', *topics]
            self._proc = self._spawn(argv)
            self._active = {'name': os.path.basename(path), 'path': self._rel(path),
                            'topics': topics, 'started_at': self._clock(), 'disk': disk,
                            'warning': disk['level'] == 'warn', 'pid': self._proc.pid}
            proc, info = self._proc, dict(self._active)
        threading.Thread(target=self._monitor, args=(proc,), name='recorder', daemon=True).start()
        LOG.info('recording %s: %s', info['path'], ' '.join(topics))
        return info

    @staticmethod
    def _check_topics(topics: Sequence[str]) -> List[str]:
        unique = list(dict.fromkeys(topics))
        if not unique:
            raise MediaError('invalid_request', 'choose at least one topic to record')
        if len(unique) > MAX_TOPICS:
            raise MediaError('invalid_request', f'at most {MAX_TOPICS} topics')
        return [validate_topic(t) for t in unique]

    def _new_dir(self, name: str) -> str:
        os.makedirs(self.root, exist_ok=True)
        base = time.strftime('%Y%m%d-%H%M%S', time.localtime(self._clock()))
        base = f'{base}_{name}' if name else base
        path = os.path.join(self.root, base)
        for i in range(2, 100):
            if not os.path.exists(path):
                return path  # rosbag2 creates it (it refuses an existing directory)
            path = os.path.join(self.root, f'{base}-{i}')
        raise MediaError('recording_failed', 'cannot pick a new recording directory', 500)

    def _spawn(self, argv: List[str]) -> subprocess.Popen:
        self._stderr.clear()
        try:
            proc = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                    stderr=subprocess.PIPE, start_new_session=True)
        except OSError as exc:
            raise MediaError('recording_failed', f'cannot start ros2 bag record: {exc}',
                             500) from exc
        threading.Thread(target=self._drain, args=(proc,), daemon=True).start()
        return proc

    def _drain(self, proc: subprocess.Popen) -> None:
        for raw in iter(proc.stderr.readline, b''):
            line = raw.decode('utf-8', 'replace').rstrip()
            if line:
                self._stderr.append(line)

    def _rel(self, path: str) -> str:
        return os.path.relpath(path, self._data_dir)

    def stop(self, reason: str = 'user') -> Dict[str, Any]:
        with self._lock:
            proc, active = self._proc, self._active
            if proc is None or active is None:
                raise MediaError('not_recording', 'no recording is running', 409)
            active['stop_reason'] = reason
        self._terminate(proc)
        return self._finish(proc, reason)

    def _terminate(self, proc: subprocess.Popen) -> None:
        for sig, timeout in ((signal.SIGINT, self._timeouts[0]),
                             (signal.SIGTERM, self._timeouts[1]), (signal.SIGKILL, None)):
            if proc.poll() is not None:
                return
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                return
            try:
                proc.wait(timeout=timeout)
                return
            except subprocess.TimeoutExpired:
                LOG.warning('ros2 bag record ignored %s', sig.name)

    def _finish(self, proc: subprocess.Popen, reason: str) -> Dict[str, Any]:
        with self._lock:
            winner = self._proc is proc  # else the other path (monitor / stop) finishes it
            if winner:
                info = dict(self._active or {})
                self._proc, self._active = None, None
        if not winner:
            self._done.wait(timeout=sum(self._timeouts) + 5.0)
            with self._lock:
                return dict(self._last or {})
        code = proc.wait()
        info.update(stop_reason=info.get('stop_reason', reason), exit_code=code,
                    stopped_at=self._clock())
        meta = read_metadata(os.path.join(self._data_dir, info['path']))
        if meta is None:
            detail = ' | '.join(list(self._stderr)[-3:]) or 'no data was recorded'
            info['error'] = f'the recording was not finalized: {detail}'
        with self._lock:
            self._last = info
        self._done.set()
        LOG.info('recording %s finished (%s, exit %s)', info['path'], info['stop_reason'], code)
        return info

    def _monitor(self, proc: subprocess.Popen) -> None:
        while True:
            try:
                proc.wait(timeout=self._period)
                self._finish(proc, 'exited')  # died on its own
                return
            except subprocess.TimeoutExpired:
                pass
            with self._lock:
                if self._proc is not proc:
                    return
            disk = self._guard.check()
            with self._lock:
                if self._active is not None:
                    self._active.update(disk=disk, warning=disk['level'] != 'ok')
            if disk['level'] == 'stop':
                LOG.warning('free disk space below the limit, stopping the recording')
                try:
                    self.stop('disk_full')
                except MediaError:
                    pass  # stopped concurrently by the user
                return

    # ---- status / list / delete ------------------------------------------------
    def status(self) -> Dict[str, Any]:
        with self._lock:
            active = dict(self._active) if self._active else None
            last = dict(self._last) if self._last else None
        if active:
            active['elapsed_sec'] = self._clock() - active['started_at']
            active['size'] = dir_size(os.path.join(self._data_dir, active['path']))
        return {'active': active, 'last': last, 'thresholds': vars(self._guard.thresholds)}

    def list(self) -> List[Dict[str, Any]]:
        if not os.path.isdir(self.root):
            return []
        with self._lock:
            active = self._active['name'] if self._active else None
        items = []
        for name in sorted(os.listdir(self.root), reverse=True):
            path = os.path.join(self.root, name)
            if not os.path.isdir(path) or os.path.islink(path):
                continue
            meta = read_metadata(path)
            items.append({'name': name, 'path': self._rel(path), 'size': dir_size(path),
                          'active': name == active, 'finalized': meta is not None,
                          **(meta or {'duration_sec': None, 'started_at': None,
                                      'message_count': None, 'topics': []})})
        return items

    def delete(self, name: str) -> Dict[str, Any]:
        if not DIR_RE.match(name or ''):
            raise MediaError('invalid_request', f'not a recording name: {name!r}')
        path = os.path.realpath(os.path.join(self.root, name))
        if os.path.dirname(path) != os.path.realpath(self.root) or not os.path.isdir(path):
            raise MediaError('not_found', f'no such recording: {name}', 404)
        with self._lock:
            if self._active is not None and self._active['name'] == name:
                raise MediaError('recording_active', 'stop the recording before deleting it', 409)
        shutil.rmtree(path)
        LOG.info('deleted recording %s', name)
        return {'deleted': name}

    def close(self) -> None:
        with self._lock:
            running = self._proc is not None
        if running:
            try:
                self.stop('shutdown')
            except MediaError:
                pass  # finished concurrently
