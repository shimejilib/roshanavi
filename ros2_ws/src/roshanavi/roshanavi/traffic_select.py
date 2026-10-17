"""Which topics to measure (shared by the C++ probe path and the Python fallback).

Rules (docs/design/map-and-traffic.md): live topics only, regex exclusions, heavy types opt-in
(``monitor_heavy`` or a per-topic override, which always wins). The selector
is shared by both measurement backends so per-topic toggles survive a switch
from the probe to the Python monitor.
"""

import logging
import re
import threading
from typing import Any, Dict, List, Sequence, Set

from rclpy.qos import ReliabilityPolicy

from .graph import RawGraph, topic_is_live
from .heavy_types import HEAVY_TYPES  # noqa: F401 - re-exported for existing imports

LOG = logging.getLogger(__name__)

DEFAULT_COLLAPSED = (r'^/rosout$', r'^/parameter_events$', r'^/events/write_split$')


class TopicSelector:
    def __init__(self, exclude: Sequence[str] = (), collapsed: Sequence[str] = DEFAULT_COLLAPSED,
                 monitor_heavy: bool = False, heavy_types: Sequence[str] = HEAVY_TYPES):
        self._exclude = [re.compile(p) for p in exclude]
        self._collapsed = [re.compile(p) for p in collapsed]
        self._monitor_heavy = monitor_heavy
        self._heavy_types = frozenset(heavy_types)
        self._lock = threading.Lock()
        self._overrides: Dict[str, bool] = {}

    def is_monitored(self, topic: str, type_name: str) -> bool:
        """Per-topic override wins; otherwise heavy types need ``monitor_heavy``."""
        with self._lock:
            override = self._overrides.get(topic)
        if override is not None:
            return override
        return self._monitor_heavy or type_name not in self._heavy_types

    def set_monitored(self, topic: str, enabled: bool) -> None:
        with self._lock:
            self._overrides[topic] = enabled
        LOG.info('traffic: monitoring of %s %s', topic, 'enabled' if enabled else 'disabled')

    def excluded(self, topic: str) -> bool:
        return any(p.search(topic) for p in self._exclude)

    def collapsed(self, topic: str) -> bool:
        return any(p.search(topic) for p in self._collapsed)

    def wanted(self, raw: RawGraph) -> Set[str]:
        """Live, non-excluded topics (the ones listed in the traffic table)."""
        return {t for t in raw.topics if topic_is_live(raw, t) and not self.excluded(t)}


def reliabilities(raw: RawGraph, topic: str) -> List[Any]:
    names = {'best_effort': ReliabilityPolicy.BEST_EFFORT, 'reliable': ReliabilityPolicy.RELIABLE}
    return [names.get(ep.qos.get('reliability'), ReliabilityPolicy.RELIABLE)
            for ep in raw.publishers.get(topic, [])]


def wants_best_effort(raw: RawGraph, topic: str) -> bool:
    """Subscribe BEST_EFFORT when any publisher is best effort (else RELIABLE)."""
    return ReliabilityPolicy.BEST_EFFORT in reliabilities(raw, topic)
