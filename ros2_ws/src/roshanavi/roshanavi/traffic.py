"""Per-topic traffic statistics from raw (non-deserialized) subscriptions.

:class:`TopicStats` is pure and clock-injectable (unit-testable without ROS).
:class:`TrafficMonitor` discovers topics from a :class:`RawGraph`, subscribes
with ``raw=True`` and feeds stats. Callbacks only append to ring buffers.
"""

import logging
import threading
import time
from typing import Any, Dict, List, Mapping, Optional, Sequence

from rclpy.callback_groups import ReentrantCallbackGroup

from .graph import RawGraph
from .msgutil import MsgUtilError, resolve_type
from .ros_runtime import RosRuntime, compatible_sub_qos
from .stats import (Clock, DEFAULT_WINDOW_SEC, HISTORY_LEN, MAX_SAMPLES,  # noqa: F401
                    WINDOWS_SEC, Sample, TopicStats, compute_stats)
from .traffic_select import (DEFAULT_COLLAPSED, HEAVY_TYPES, TopicSelector,  # noqa: F401
                             reliabilities, wants_best_effort)

LOG = logging.getLogger(__name__)
EMPTY_STATS: Dict[str, Any] = {
    'hz': 0.0, 'hz_basis': 'receive', 'hz_recv': 0.0, 'hz_source': None,
    'bytes_per_sec': 0.0, 'avg_size': 0.0, 'jitter_ms': 0.0, 'jitter_recv_ms': 0.0,
    'dropped': None, 'drop_ratio': None, 'latency_ms': None,
    'last_seen': None, 'total_count': 0, 'recent_count': 0, 'history': [],
    'rate_window_sec': None, 'rate_note': None, 'stale': False}


class _Tracked:
    def __init__(self, type_name: str, stats: Optional[TopicStats], subscription: Any,
                 status: str, error: Optional[str] = None, best_effort: bool = False,
                 monitored: bool = True):
        self.best_effort = best_effort
        self.monitored = monitored
        self.type_name = type_name
        self.stats = stats
        self.subscription = subscription
        self.status = status
        self.error = error


class TrafficMonitor:
    """Keeps one raw subscription per live topic and exposes its statistics."""

    def __init__(self, runtime: RosRuntime, window_sec: float = DEFAULT_WINDOW_SEC,
                 exclude: Sequence[str] = (), collapsed: Sequence[str] = DEFAULT_COLLAPSED,
                 clock: Clock = time.monotonic, wall_clock: Clock = time.time,
                 monitor_heavy: bool = False, heavy_types: Sequence[str] = HEAVY_TYPES,
                 selector: Optional[TopicSelector] = None):
        self.selector = selector or TopicSelector(exclude, collapsed, monitor_heavy, heavy_types)
        self._runtime = runtime
        self._window = window_sec
        self._clock, self._wall = clock, wall_clock
        self._lock = threading.Lock()
        self._topics: Dict[str, _Tracked] = {}
        self._group = ReentrantCallbackGroup()

    def is_monitored(self, topic: str, type_name: str) -> bool:
        return self.selector.is_monitored(topic, type_name)

    def set_monitored(self, topic: str, enabled: bool) -> None:
        """Record an override; the subscription follows on the next ``sync``."""
        self.selector.set_monitored(topic, enabled)

    def sync(self, raw: RawGraph) -> None:
        """Subscribe new live topics, drop vanished ones. Runs on the executor thread."""
        with self._lock:
            known = set(self._topics)
        wanted = self.selector.wanted(raw)
        for topic in sorted(wanted - known):
            self._add(topic, raw)
        for topic in sorted(known - wanted):
            self._remove(topic)
        for topic in sorted(known & wanted):
            if self._needs_resubscribe(topic, raw):
                LOG.info('traffic: QoS or monitoring of %s changed, resubscribing', topic)
                self._remove(topic)
                self._add(topic, raw)

    def _needs_resubscribe(self, topic: str, raw: RawGraph) -> bool:
        with self._lock:
            tracked = self._topics.get(topic)
        if tracked is None:
            return False
        if tracked.status == 'unsupported':
            return False
        if self.is_monitored(topic, tracked.type_name) != tracked.monitored:
            return True
        return tracked.subscription is not None and (
            wants_best_effort(raw, topic) != tracked.best_effort)

    def _add(self, topic: str, raw: RawGraph) -> None:
        types = raw.topics.get(topic, [])
        type_name = types[0] if types else ''
        if len(types) != 1:
            self._store(topic, _Tracked(type_name, None, None, 'unsupported',
                                        f'topic has {len(types)} types: {types}'))
            return
        try:
            msg_type = resolve_type(type_name)
        except MsgUtilError as exc:
            LOG.info('traffic: %s unsupported: %s', topic, exc)
            self._store(topic, _Tracked(type_name, None, None, 'unsupported', str(exc)))
            return
        if not self.is_monitored(topic, type_name):
            self._store(topic, _Tracked(type_name, None, None, 'not_monitored', monitored=False))
            return
        stats = TopicStats(self._window, self._clock, self._wall)
        best_effort = wants_best_effort(raw, topic)
        qos = compatible_sub_qos(reliabilities(raw, topic))
        try:
            sub = self._runtime.create_subscription(
                msg_type, topic, _recorder(stats), qos, raw=True,
                group=self._group)
        except Exception as exc:  # rclpy raises several types; record and keep going
            LOG.warning('traffic: failed to subscribe %s: %s', topic, exc)
            self._store(topic, _Tracked(type_name, None, None, 'error', str(exc)))
            return
        self._store(topic, _Tracked(type_name, stats, sub, 'ok', best_effort=best_effort))

    def _store(self, topic: str, tracked: _Tracked) -> None:
        with self._lock:
            self._topics[topic] = tracked

    def _remove(self, topic: str) -> None:
        with self._lock:
            tracked = self._topics.pop(topic, None)
        if tracked is not None and tracked.subscription is not None:
            self._runtime.destroy_subscription(tracked.subscription)

    def tick(self) -> None:
        with self._lock:
            stats = [t.stats for t in self._topics.values() if t.stats is not None]
        for s in stats:
            s.tick()

    def snapshot(self, window_sec: Optional[float] = None) -> List[Dict[str, Any]]:
        """All tracked topics; rates averaged over ``window_sec`` (default window if None)."""
        window = window_sec or self._window
        with self._lock:
            items = sorted(self._topics.items())
        result = []
        for topic, tracked in items:
            entry: Dict[str, Any] = {
                'topic': topic, 'type': tracked.type_name, 'status': tracked.status,
                'monitored': self.is_monitored(topic, tracked.type_name),
                'collapsed': self.selector.collapsed(topic), 'measurement': 'python'}
            if tracked.stats is not None:
                entry.update(tracked.stats.snapshot(window))
            else:
                entry.update({**EMPTY_STATS, 'history': [], 'window_sec': window,
                              'error': tracked.error})
            result.append(entry)
        return result

    def close(self) -> None:
        with self._lock:
            topics = list(self._topics)
        for topic in topics:
            self._remove(topic)


def _recorder(stats: TopicStats) -> Any:
    """Raw-subscription callback; the 2-arg form makes rclpy pass ``MessageInfo``."""
    def on_message(data: bytes, info: Optional[Mapping[str, Any]]) -> None:
        stats.record(len(data), info)
    return on_message
