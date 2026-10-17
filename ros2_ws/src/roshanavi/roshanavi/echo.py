"""On-demand deserializing subscriptions for the echo view.

One subscription per topic is shared by all watchers (reference counted) and
destroyed when the last watcher leaves. The ROS callback only stores the latest
message object; conversion to a display dict happens on the reader side
(``latest()``), which is throttled by the caller (WS loop at <= 10 Hz).
"""

import logging
import threading
from typing import Any, Dict, Optional, Tuple

from rclpy.serialization import serialize_message

from . import msgutil
from .ros_runtime import RosRuntime

LOG = logging.getLogger(__name__)

MAX_ECHO_TOPICS = 32
# The transform preview computes on the whole latest message (not the 32-item display copy), but
# only up to this many serialized bytes; a bigger message falls back to the display copy.
MAX_SAMPLE_BYTES = 256 * 1024


class EchoError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class _Channel:
    def __init__(self, type_name: str):
        self.type_name = type_name
        self.lock = threading.Lock()
        self.msg: Any = None
        self.seq = 0
        self.refs = 0
        self.subscription: Any = None

    def on_message(self, msg: Any) -> None:
        with self.lock:
            self.msg = msg
            self.seq += 1


class EchoManager:
    def __init__(self, runtime: RosRuntime):
        self._runtime = runtime
        self._lock = threading.Lock()
        self._channels: Dict[str, _Channel] = {}

    def _topic_type(self, topic: str) -> str:
        types = dict(self._runtime.topic_names_and_types()).get(topic)
        if not types:
            raise EchoError('not_found', f'unknown topic: {topic}', 404)
        if len(types) != 1:
            raise EchoError('unsupported', f'topic {topic} has multiple types: {types}')
        return types[0]

    def acquire(self, topic: str) -> str:
        """Start (or join) watching ``topic``. Returns its type name.

        Holding ``self._lock`` across runtime calls is safe: the runtime lock
        is a leaf lock (its holders never call back into module code).
        """
        with self._lock:
            channel = self._channels.get(topic)
            if channel is not None:
                channel.refs += 1
                return channel.type_name
            if len(self._channels) >= MAX_ECHO_TOPICS:
                raise EchoError('too_many', f'at most {MAX_ECHO_TOPICS} echoed topics', 429)
            type_name = self._topic_type(topic)
            try:
                msg_type = msgutil.resolve_type(type_name)
            except msgutil.MsgUtilError as exc:
                raise EchoError('unsupported', str(exc)) from exc
            channel = _Channel(type_name)
            try:
                qos = self._runtime.subscription_qos_for(topic)
                channel.subscription = self._runtime.create_subscription(
                    msg_type, topic, channel.on_message, qos)
            except Exception as exc:  # rclpy raises several types; report as API error
                LOG.warning('echo: cannot subscribe %s: %s', topic, exc)
                raise EchoError('subscribe_failed', f'cannot subscribe {topic}: {exc}',
                                500) from exc
            channel.refs = 1
            self._channels[topic] = channel
            return type_name

    def release(self, topic: str) -> None:
        with self._lock:
            channel = self._channels.get(topic)
            if channel is None:
                return
            channel.refs -= 1
            if channel.refs > 0:
                return
            del self._channels[topic]
            self._runtime.destroy_subscription(channel.subscription)

    def latest(self, topic: str) -> Tuple[int, Optional[Dict[str, Any]]]:
        """(sequence number, display dict or None if nothing received yet)."""
        with self._lock:
            channel = self._channels.get(topic)
        if channel is None:
            return 0, None
        with channel.lock:
            seq, msg = channel.seq, channel.msg
        return seq, (msgutil.to_display(msg) if msg is not None else None)

    def latest_sample(self, topic: str, max_bytes: int = MAX_SAMPLE_BYTES
                      ) -> Tuple[int, Optional[Dict[str, Any]], bool, int]:
        """(seq, untruncated message dict or None, capped, serialized size) for the transform preview.

        ``capped`` is True when the message is larger than ``max_bytes``; ``msg`` is then the
        usual display copy (long arrays / strings truncated), so the caller can say so.
        """
        with self._lock:
            channel = self._channels.get(topic)
        if channel is None:
            return 0, None, False, 0
        with channel.lock:
            seq, msg = channel.seq, channel.msg
        if msg is None:
            return seq, None, False, 0
        size = len(serialize_message(msg))
        if size > max_bytes:
            return seq, msgutil.to_display(msg), True, size
        return seq, msgutil.to_plain(msg), False, size

    def close(self) -> None:
        with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        for channel in channels:
            if channel.subscription is not None:
                self._runtime.destroy_subscription(channel.subscription)
