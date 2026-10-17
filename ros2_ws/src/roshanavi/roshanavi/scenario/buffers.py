"""Pre-subscription of every topic a scenario checks, with receive timestamps.

All topics are subscribed when the steps begin (after setup), before anything is
sent, so a response that arrives at once is never missed. Each message is
stored with its monotonic receive time; checks read them through cursors.
A topic whose type is not known yet (nobody publishes it, no ``type``/``kind``
in the scenario) is subscribed as soon as it appears in the graph.

Subscriptions go through ``RosRuntime.create_subscription`` (no QoS event
handlers, see ros_runtime). QoS: reliable when every current publisher is
reliable, else best effort (receives from both), volatile, depth 100.
"""

import logging
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from rclpy.qos import ReliabilityPolicy

from .. import msgutil
from ..ros_runtime import RosRuntime, is_self_node, make_qos
from .checks import Record
from .fields import plain_capped

LOG = logging.getLogger(__name__)

SUB_DEPTH = 100
MAX_RECORDS = 20000  # per topic; older records are dropped (cursors keep working)
MATCH_WAIT_SEC = 1.0


class TopicBuffer:
    def __init__(self, topic: str, clock: Callable[[], float] = time.monotonic):
        self.topic = topic
        self.type_name: Optional[str] = None
        self.subscription: Any = None
        self.error: Optional[str] = None
        self.subscribed_at: Optional[float] = None
        self._clock = clock
        self._lock = threading.Lock()
        self._records: List[Record] = []
        self._base = 0  # absolute index of _records[0]
        self.total = 0

    def on_message(self, msg: Any) -> None:
        """Executor-thread callback: convert once (arrays capped) and store."""
        rec = Record(self._clock(), time.time(), plain_capped(msg))
        with self._lock:
            self._records.append(rec)
            self.total += 1
            if len(self._records) > MAX_RECORDS:
                drop = len(self._records) - MAX_RECORDS // 2
                del self._records[:drop]
                self._base += drop

    def append(self, rec: Record) -> None:
        """Tests: inject a record without ROS."""
        with self._lock:
            self._records.append(rec)
            self.total += 1

    def since(self, cursor: int) -> Tuple[List[Record], int]:
        with self._lock:
            start = max(cursor - self._base, 0)
            return self._records[start:], self._base + len(self._records)


class Subscriptions:
    """One buffer per checked topic; ``pending`` ones subscribe when their type appears."""

    def __init__(self, runtime: Optional[RosRuntime], topics: Sequence[str],
                 type_hints: Dict[str, str], clock: Callable[[], float] = time.monotonic):
        self._runtime = runtime
        self._hints = dict(type_hints)
        self.buffers: Dict[str, TopicBuffer] = {t: TopicBuffer(t, clock) for t in topics}
        self._last_retry = 0.0

    def _graph_types(self) -> Dict[str, List[str]]:
        return dict(self._runtime.topic_names_and_types()) if self._runtime else {}

    def start(self) -> None:
        self.retry(force=True)

    def pending(self) -> List[str]:
        """Topics not subscribed yet (type unknown) and not failed."""
        return [t for t, b in self.buffers.items() if b.subscription is None and not b.error]

    def retry(self, force: bool = False) -> None:
        """Subscribe topics whose type became known (called from the run loop)."""
        now = time.monotonic()
        pending = [b for b in self.buffers.values() if b.subscription is None and not b.error]
        if not pending or (not force and now - self._last_retry < 0.2) or self._runtime is None:
            return
        self._last_retry = now
        graph = self._graph_types()
        for buf in pending:
            type_name = self._hints.get(buf.topic)
            types = graph.get(buf.topic, [])
            if type_name is None and len(types) == 1:
                type_name = types[0]
            elif type_name is None and len(types) > 1:
                buf.error = f'{buf.topic} は複数の型 ({", ".join(types)}) で使われているので購読できません'
                continue
            if type_name is None:
                continue
            self._subscribe(buf, type_name)

    def _subscribe(self, buf: TopicBuffer, type_name: str) -> None:
        try:
            msg_type = msgutil.resolve_type(type_name)
            pubs = self._runtime.publishers_info(buf.topic)
            # Nobody publishes yet: best effort receives from reliable and best-effort senders.
            reliable = bool(pubs) and all(p.qos_profile.reliability == ReliabilityPolicy.RELIABLE
                                          for p in pubs)
            qos = make_qos('reliable' if reliable else 'best_effort', 'volatile', SUB_DEPTH)
            buf.subscription = self._runtime.create_subscription(msg_type, buf.topic,
                                                                 buf.on_message, qos)
            buf.type_name = msgutil.normalize_type_name(type_name)
            buf.subscribed_at = time.monotonic()
        except msgutil.MsgUtilError as exc:
            buf.error = f'{buf.topic} の型 {type_name} が見つかりません: {exc}'
        except Exception as exc:  # rclpy raises several types
            LOG.warning('scenario: cannot subscribe %s: %s', buf.topic, exc)
            buf.error = f'{buf.topic} を購読できません: {exc}'

    def wait_matched(self, timeout: float = MATCH_WAIT_SEC) -> None:
        """Wait until our subscriptions see the publishers the graph already knows about."""
        if self._runtime is None:
            return
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            waiting = False
            for buf in self.buffers.values():
                if buf.subscription is None:
                    continue
                expected = len([p for p in self._runtime.publishers_info(buf.topic)
                                if not is_self_node(f'/{p.node_name}')])
                if buf.subscription.get_publisher_count() < expected:
                    waiting = True
            if not waiting:
                return
            time.sleep(0.02)

    def close(self) -> None:
        if self._runtime is None:
            return
        for buf in self.buffers.values():
            if buf.subscription is not None:
                self._runtime.destroy_subscription(buf.subscription)
                buf.subscription = None
