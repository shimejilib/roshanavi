"""Traffic statistics measured by the C++ probe (docs/design/map-and-traffic.md, probe path).

Same interface and entry shape as :class:`traffic.TrafficMonitor` (the Python
fallback). Topic selection stays here (``TopicSelector``); the probe gets the
selected set on ``/roshanavi/_probe/config`` (latched, so a restarted probe
picks it up by itself) and reports per-(topic, window) statistics with
per-publisher ``endpoints`` on ``/roshanavi/_probe/stats`` once per second.
"""

import logging
import math
import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

from rclpy.qos import DurabilityPolicy, HistoryPolicy, QoSProfile, ReliabilityPolicy

from .graph import RawGraph, fq_name
from .probe_process import ProbeProcess
from .ros_runtime import RosRuntime
from .stats import Clock, DEFAULT_WINDOW_SEC, HISTORY_LEN, WINDOWS_SEC
from .traffic_select import TopicSelector, wants_best_effort

LOG = logging.getLogger(__name__)

CONFIG_TOPIC = '/roshanavi/_probe/config'
STATS_TOPIC = '/roshanavi/_probe/stats'
PROBE_STALE_SEC = 3.5  # no statistics for this long: the probe is considered down
PROBE_HUNG_SEC = 15.0  # alive but silent this long (or since start): restart it
MEASUREMENT = 'probe'

ProbeSpec = Tuple[str, str, bool]  # (topic, type, best_effort)

EMPTY_PROBE_STATS: Dict[str, Any] = {
    'hz': 0.0, 'hz_basis': 'receive', 'hz_recv': 0.0, 'hz_source': None,
    'bytes_per_sec': 0.0, 'avg_size': 0.0, 'jitter_ms': 0.0, 'jitter_recv_ms': 0.0,
    'dropped': None, 'drop_ratio': None, 'latency_ms': None,
    'last_seen': None, 'total_count': 0, 'recent_count': 0,
    'rate_window_sec': None, 'rate_note': None, 'stale': False, 'endpoints': []}


def _num(value: float) -> Optional[float]:
    return None if value is None or math.isnan(value) else float(value)


def _int(value: int) -> Optional[int]:
    return None if value < 0 else int(value)


def _stamp(t: Any) -> Optional[float]:
    return None if not (t.sec or t.nanosec) else t.sec + t.nanosec / 1e9


def endpoint_to_dict(ep: Any) -> Dict[str, Any]:
    node = fq_name(ep.node_name, ep.node_namespace) if ep.resolved else None
    return {'gid': bytes(ep.publisher_gid).hex(), 'node': node, 'resolved': bool(ep.resolved),
            'hz': float(ep.hz), 'bps': float(ep.bps), 'count': int(ep.count),
            'bytes': int(ep.bytes), 'dropped': _int(ep.dropped), 'stale': bool(ep.stale),
            'rate_note': ep.rate_note or None,
            'first_source_stamp': _stamp(ep.first_source_stamp),
            'last_source_stamp': _stamp(ep.last_source_stamp)}


def topic_stats_to_dict(ts: Any) -> Dict[str, Any]:
    """A roshanavi_msgs/TopicStats as the traffic entry fields (NaN / -1 -> None)."""
    return {'status': ts.status, 'error': ts.error or None,
            'hz': float(ts.hz), 'hz_basis': ts.hz_basis, 'hz_recv': float(ts.hz_recv),
            'hz_source': _num(ts.hz_source), 'bytes_per_sec': float(ts.bytes_per_sec),
            'avg_size': float(ts.avg_size), 'jitter_ms': float(ts.jitter_ms),
            'jitter_recv_ms': float(ts.jitter_recv_ms), 'dropped': _int(ts.dropped),
            'drop_ratio': _num(ts.drop_ratio), 'latency_ms': _num(ts.latency_ms),
            'last_seen': _stamp(ts.last_seen), 'total_count': int(ts.total_count),
            'recent_count': int(ts.recent_count), 'window_sec': float(ts.window_sec),
            'rate_window_sec': float(ts.rate_window_sec), 'rate_note': ts.rate_note or None,
            'stale': bool(ts.stale), 'endpoints': [endpoint_to_dict(e) for e in ts.endpoints]}


def gid_resolution(entries: Sequence[Dict[str, Any]]) -> str:
    """matched: publisher gids map to graph endpoints; unmatched: none do (RMW limitation)."""
    endpoints = [e for entry in entries for e in entry.get('endpoints') or []]
    if not endpoints:
        return 'unknown'
    return 'matched' if any(e['resolved'] for e in endpoints) else 'unmatched'


class _Topic:
    def __init__(self, type_name: str, status: str, error: Optional[str] = None,
                 monitored: bool = True):
        self.type_name, self.status, self.error, self.monitored = type_name, status, error, monitored
        self.history: Deque[float] = deque(maxlen=HISTORY_LEN)


class ProbeTrafficMonitor:
    def __init__(self, runtime: RosRuntime, selector: TopicSelector, process: ProbeProcess,
                 instance: str, window_sec: float = DEFAULT_WINDOW_SEC,
                 windows: Sequence[float] = WINDOWS_SEC, clock: Clock = time.monotonic):
        from roshanavi_msgs.msg import ProbeConfig, ProbeStats  # only importable when built
        self.selector, self.process, self.instance = selector, process, instance
        self._runtime, self._window, self._windows = runtime, window_sec, tuple(windows)
        self._clock = clock
        self._config_type = ProbeConfig
        self._lock = threading.Lock()
        self._topics: Dict[str, _Topic] = {}
        self._stats: Dict[Tuple[str, float], Dict[str, Any]] = {}
        self._probe_info: Dict[str, Any] = {}
        self._last_rx: Optional[float] = None
        self._sent: Optional[List[ProbeSpec]] = None
        latched = QoSProfile(depth=1, history=HistoryPolicy.KEEP_LAST,
                             reliability=ReliabilityPolicy.RELIABLE,
                             durability=DurabilityPolicy.TRANSIENT_LOCAL)
        self._config_pub = runtime.create_publisher(ProbeConfig, CONFIG_TOPIC, latched)
        stats_qos = QoSProfile(depth=2, reliability=ReliabilityPolicy.RELIABLE,
                               durability=DurabilityPolicy.VOLATILE)
        self._stats_sub = runtime.create_subscription(ProbeStats, STATS_TOPIC, self._on_stats,
                                                      stats_qos)

    # ---- selection (same API as TrafficMonitor) ---------------------------
    def is_monitored(self, topic: str, type_name: str) -> bool:
        return self.selector.is_monitored(topic, type_name)

    def set_monitored(self, topic: str, enabled: bool) -> None:
        self.selector.set_monitored(topic, enabled)

    def sync(self, raw: RawGraph) -> None:
        """Recompute the topic set, (re)send the config when it changed, keep the probe alive."""
        topics: Dict[str, _Topic] = {}
        specs: List[ProbeSpec] = []
        with self._lock:
            previous = dict(self._topics)
        for topic in sorted(self.selector.wanted(raw)):
            types = raw.topics.get(topic, [])
            type_name = types[0] if types else ''
            if len(types) != 1:
                entry = _Topic(type_name, 'unsupported', f'topic has {len(types)} types: {types}')
            elif not self.is_monitored(topic, type_name):
                entry = _Topic(type_name, 'not_monitored', monitored=False)
            else:
                entry = _Topic(type_name, 'ok')
                specs.append((topic, type_name, wants_best_effort(raw, topic)))
            old = previous.get(topic)
            if old is not None and old.status == entry.status and old.type_name == type_name:
                entry.history = old.history
            topics[topic] = entry
        with self._lock:
            self._topics = topics
        if specs != self._sent:
            self._send_config(specs)
        self._restart_if_hung()
        self.process.poll()

    def _restart_if_hung(self) -> None:
        uptime = self.process.uptime()
        if uptime is None or uptime < PROBE_HUNG_SEC:
            return
        with self._lock:
            last = self._last_rx
        if last is None or self._clock() - last >= PROBE_HUNG_SEC:
            self.process.restart_hung()

    def _send_config(self, specs: List[ProbeSpec]) -> None:
        from roshanavi_msgs.msg import ProbeTopic
        msg = self._config_type(instance=self.instance, windows_sec=list(self._windows),
                                topics=[ProbeTopic(topic=t, type=ty, best_effort=be)
                                        for t, ty, be in specs])
        self._config_pub.publish(msg)
        self._sent = specs
        LOG.info('probe: monitoring %d topics', len(specs))

    def _on_stats(self, msg: Any) -> None:
        if msg.instance != self.instance:
            return  # another roshanavi server's probe on the same domain
        stats = {(ts.topic, round(float(ts.window_sec), 3)): topic_stats_to_dict(ts)
                 for ts in msg.topics}
        info = {'rmw': msg.rmw_implementation, 'cpu_percent': round(msg.cpu_percent, 2),
                'rss_bytes': int(msg.rss_bytes)}
        with self._lock:
            self._stats, self._probe_info, self._last_rx = stats, info, self._clock()
        self.process.mark_healthy()

    def _fresh(self) -> bool:
        return self._last_rx is not None and self._clock() - self._last_rx <= PROBE_STALE_SEC

    def tick(self) -> None:
        with self._lock:
            for topic, entry in self._topics.items():
                stats = self._stats.get((topic, round(self._window, 3))) if self._fresh() else None
                entry.history.append(stats['hz'] if stats else 0.0)

    def snapshot(self, window_sec: Optional[float] = None) -> List[Dict[str, Any]]:
        window = window_sec or self._window
        with self._lock:
            items = sorted(self._topics.items())
            stats = dict(self._stats) if self._fresh() else None
            started = self._last_rx is not None
        result = []
        for topic, tracked in items:
            entry: Dict[str, Any] = {
                'topic': topic, 'type': tracked.type_name, 'status': tracked.status,
                'monitored': self.is_monitored(topic, tracked.type_name),
                'collapsed': self.selector.collapsed(topic), 'measurement': MEASUREMENT,
                **EMPTY_PROBE_STATS, 'history': list(tracked.history), 'window_sec': window,
                'error': tracked.error}
            measured = stats.get((topic, round(window, 3))) if stats is not None else None
            if tracked.status == 'ok' and measured is not None:
                entry.update(measured)
            elif tracked.status == 'ok' and stats is None and started:
                entry.update(status='error', error='probe_unavailable')
            result.append(entry)
        return result

    def status(self) -> Dict[str, Any]:
        with self._lock:
            info, fresh = dict(self._probe_info), self._fresh()
            entries = list(self._stats.values()) if fresh else []
        return {'mode': MEASUREMENT, 'reason': None, 'state': self.process.state,
                'pid': self.process.pid, 'restarts': self.process.restarts,
                'receiving': fresh, 'cpu_percent': info.get('cpu_percent') if fresh else None,
                'rss_bytes': info.get('rss_bytes') if fresh else None, 'rmw': info.get('rmw'),
                'gid_resolution': gid_resolution(entries)}

    def close(self) -> None:
        try:
            self.process.stop()
        finally:
            self._runtime.destroy_subscription(self._stats_sub)
            self._runtime.destroy_publisher(self._config_pub)
