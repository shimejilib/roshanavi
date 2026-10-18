"""Diagnostics that need memory of earlier snapshots (docs/design/map-and-traffic.md#診断).

- ``subscriber_lost`` / ``publisher_lost`` (warning): a topic had subscribers (publishers)
  within the last ``window_sec`` (default 5 min), now has none, and the other side is still
  there: "さっきまで /x が受信していましたが、いなくなりました". The absence must last
  ``debounce_sec`` so a node that restarts within a moment does not flash a warning. The detail
  holds no elapsed time: it would change the snapshot every second and re-push the graph.
- ``mine_no_input`` (warning): a node with role ``mine`` subscribes to a topic nobody
  publishes, for longer than ``grace_sec`` (3 s) since the node appeared and the topic has been
  without publisher: "開発中のノード /n の入力 /t に送信元がいません". It replaces
  ``publisher_lost`` for the same topic (the more specific message).

:class:`GraphHistory` is fed one snapshot per housekeeping tick with an explicit ``now``
(monotonic seconds) and never reads a clock itself, so tests drive it with any timeline.
Endpoints are counted like :func:`roshanavi.diagnostics.topic_sides`: infrastructure nodes
(``_ros2cli_*``, roshanavi's own viewer / echo / probe) are not users, hidden topics are
ignored.
"""

from dataclasses import dataclass, field
from typing import Any, Collection, Dict, FrozenSet, List, Mapping, Set, Tuple

from .diagnostics import is_hidden_topic, make_diag, topic_sides

LOST_WINDOW_SEC = 300.0
LOST_DEBOUNCE_SEC = 3.0
MINE_GRACE_SEC = 3.0
ROLE_MINE = 'mine'


@dataclass
class _Seen:
    """When a side of a topic was last present, and who was there."""
    at: float
    nodes: FrozenSet[str]


@dataclass
class GraphHistory:
    window_sec: float = LOST_WINDOW_SEC
    debounce_sec: float = LOST_DEBOUNCE_SEC
    grace_sec: float = MINE_GRACE_SEC
    _last_sub: Dict[str, _Seen] = field(default_factory=dict)
    _last_pub: Dict[str, _Seen] = field(default_factory=dict)
    _publess_since: Dict[str, float] = field(default_factory=dict)
    _node_first: Dict[str, float] = field(default_factory=dict)

    def update(self, now: float, snapshot: Mapping[str, Any],
               quiet_topics: Collection[str] = ()) -> List[Dict[str, Any]]:
        """Record ``snapshot`` and return the time-dependent diagnostics (unsorted).
        ``quiet_topics`` (class nodes' action topics) are one-sided on purpose: ignored."""
        sides = topic_sides(snapshot, quiet_topics)
        self._observe(now, snapshot, sides)
        mine = self._mine_no_input(now, snapshot, sides)
        covered = {d['topic'] for d in mine}
        return mine + self._lost(now, sides, covered)

    # ---- recording -------------------------------------------------------------------------
    def _observe(self, now: float, snapshot: Mapping[str, Any],
                 sides: Mapping[str, Tuple[Set[str], Set[str]]]) -> None:
        for topic, (pubs, subs) in sides.items():
            if is_hidden_topic(topic):
                continue
            if subs:
                self._last_sub[topic] = _Seen(now, frozenset(subs))
            if pubs:
                self._last_pub[topic] = _Seen(now, frozenset(pubs))
                self._publess_since.pop(topic, None)
            else:
                self._publess_since.setdefault(topic, now)
        for topic in [t for t in self._publess_since if t not in sides]:
            del self._publess_since[topic]
        current = {n['id'] for n in snapshot.get('nodes', [])}
        for node in current:
            self._node_first.setdefault(node, now)
        for node in [n for n in self._node_first if n not in current]:
            del self._node_first[node]
        for table in (self._last_sub, self._last_pub):
            for topic in [t for t, seen in table.items() if now - seen.at > self.window_sec]:
                del table[topic]

    # ---- the diagnostics -------------------------------------------------------------------
    def _lost(self, now: float, sides: Mapping[str, Tuple[Set[str], Set[str]]],
              covered: Set[str]) -> List[Dict[str, Any]]:
        out: List[Dict[str, Any]] = []
        for topic, (pubs, subs) in sorted(sides.items()):
            if is_hidden_topic(topic):
                continue
            seen = self._last_sub.get(topic)
            if pubs and not subs and seen and now - seen.at >= self.debounce_sec:
                out.append(make_diag('subscriber_lost', 'warning', topic, pubs,
                                 {'lost': sorted(seen.nodes)}))
            seen = self._last_pub.get(topic)
            if (subs and not pubs and seen and topic not in covered
                    and now - seen.at >= self.debounce_sec):
                out.append(make_diag('publisher_lost', 'warning', topic, subs,
                                 {'lost': sorted(seen.nodes)}))
        return out

    def _mine_no_input(self, now: float, snapshot: Mapping[str, Any],
                       sides: Mapping[str, Tuple[Set[str], Set[str]]]) -> List[Dict[str, Any]]:
        mine = {n['id'] for n in snapshot.get('nodes', []) if n.get('role') == ROLE_MINE}
        out: List[Dict[str, Any]] = []
        for topic, (pubs, subs) in sorted(sides.items()):
            since = self._publess_since.get(topic)
            if pubs or since is None or is_hidden_topic(topic) or now - since < self.grace_sec:
                continue
            for node in sorted(subs & mine):
                if now - self._node_first.get(node, now) < self.grace_sec:
                    continue
                out.append(make_diag('mine_no_input', 'warning', topic, [node], {'node': node}))
        return out
