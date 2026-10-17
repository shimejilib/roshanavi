"""Chooses how traffic is measured: the C++ probe, or the Python monitor as fallback.

``--probe auto`` (default) uses the probe when ``roshanavi_probe`` is built and
falls back to the Python :class:`TrafficMonitor` when it is not, or when the
probe keeps crashing. ``--probe off`` always uses the Python monitor. The
reason is reported in :meth:`TrafficService.status` so the UI can explain it.
"""

import logging
import threading
import time
import uuid
from typing import Any, Callable, Dict, List, Optional, Sequence

from .graph import RawGraph
from .probe_process import ProbeProcess, find_probe_executable
from .ros_runtime import RosRuntime
from .stats import Clock, DEFAULT_WINDOW_SEC
from .traffic import TrafficMonitor
from .traffic_select import TopicSelector

LOG = logging.getLogger(__name__)

PROBE_AUTO = 'auto'
PROBE_OFF = 'off'
PROBE_MODES = (PROBE_AUTO, PROBE_OFF)
REASON_DISABLED = 'disabled'
REASON_NOT_BUILT = 'not_built'
REASON_CRASHED = 'crashed'
REASON_UNAVAILABLE = 'unavailable'  # built, but roshanavi_msgs cannot be imported


class TrafficService:
    """Facade over the active backend; same methods as TrafficMonitor plus ``status()``."""

    def __init__(self, runtime: RosRuntime, probe: str = PROBE_OFF,
                 window_sec: float = DEFAULT_WINDOW_SEC, exclude: Sequence[str] = (),
                 monitor_heavy: bool = False, clock: Clock = time.monotonic,
                 find_executable: Callable[[], Optional[str]] = find_probe_executable):
        if probe not in PROBE_MODES:
            raise ValueError(f'probe must be one of {PROBE_MODES}')
        self.selector = TopicSelector(exclude=exclude, monitor_heavy=monitor_heavy)
        self._runtime, self._window, self._clock = runtime, window_sec, clock
        self._probe, self._find = probe, find_executable
        self._lock = threading.Lock()
        self._reason: Optional[str] = REASON_DISABLED
        self._backend: Any = None

    def start(self) -> None:
        """Pick the backend; needs a running runtime (the probe path creates pub/sub)."""
        backend = None
        if self._probe == PROBE_AUTO:
            executable = self._find()
            self._reason = REASON_NOT_BUILT if executable is None else None
            if executable is not None:
                backend = self._start_probe(executable)
        if backend is None:
            backend = self._python()
        with self._lock:
            previous, self._backend = self._backend, backend
        if previous is not None:  # a Python monitor used before start()
            previous.close()
        if self._reason not in (None, REASON_DISABLED):
            LOG.warning('traffic: measuring in Python (%s)', self._reason)

    def _python(self) -> TrafficMonitor:
        return TrafficMonitor(self._runtime, window_sec=self._window, clock=self._clock,
                              selector=self.selector)

    def _start_probe(self, executable: str) -> Any:
        try:
            from .probe_traffic import ProbeTrafficMonitor
            # A letter first: an all-digit id would be parsed as an integer ROS parameter.
            instance = 'r' + uuid.uuid4().hex[:12]
            process = ProbeProcess(executable, instance)
            monitor = ProbeTrafficMonitor(self._runtime, self.selector, process, instance,
                                          window_sec=self._window, clock=self._clock)
        except ImportError as exc:  # roshanavi_msgs not built for Python
            LOG.error('probe: roshanavi_msgs unavailable: %s', exc)
            self._reason = REASON_UNAVAILABLE
            return None
        process.start()
        LOG.info('traffic: measuring with the C++ probe (%s)', executable)
        return monitor

    @property
    def backend(self) -> Any:
        with self._lock:
            if self._backend is None:  # before start(): the Python monitor needs no node
                self._backend = self._python()
            return self._backend

    def is_monitored(self, topic: str, type_name: str) -> bool:
        return self.selector.is_monitored(topic, type_name)

    def set_monitored(self, topic: str, enabled: bool) -> None:
        self.selector.set_monitored(topic, enabled)

    def sync(self, raw: RawGraph) -> None:
        backend = self.backend
        backend.sync(raw)
        process = getattr(backend, 'process', None)
        if process is not None and process.gave_up:
            self._fall_back(backend)
            self.backend.sync(raw)

    def _fall_back(self, failed: Any) -> None:
        LOG.error('traffic: the probe keeps crashing; switching to the Python monitor')
        replacement = self._python()
        with self._lock:
            self._backend, self._reason = replacement, REASON_CRASHED
        failed.close()

    def tick(self) -> None:
        self.backend.tick()

    def snapshot(self, window_sec: Optional[float] = None) -> List[Dict[str, Any]]:
        return self.backend.snapshot(window_sec)

    def status(self) -> Dict[str, Any]:
        backend = self.backend
        if hasattr(backend, 'status'):
            return backend.status()
        with self._lock:
            reason = self._reason
        return {'mode': 'python', 'reason': reason, 'state': None, 'pid': None, 'restarts': 0,
                'receiving': True, 'cpu_percent': None, 'rss_bytes': None, 'rmw': None,
                'gid_resolution': 'unknown'}

    def close(self) -> None:
        self.backend.close()
