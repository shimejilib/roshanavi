"""On-demand viewers for image and audio topics (subscribed only while open).

Image topics: the latest message is kept; the WebSocket loop (<= 10 fps) turns
it into a JPEG no wider than 640 px. Audio topics: recent chunks are kept in a
bounded queue and forwarded as PCM S16LE (mono downmix) for the waveform and
WebAudio playback. audio_common topics also follow the sibling ``audio_info``
topic for the sample rate and channel count.

One deserializing subscription per topic is shared by all viewers (reference
counted), like the echo view. Callbacks only store data; conversion happens on
the reader side.
"""

import itertools
import logging
import threading
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import numpy as np

from .. import msgutil
from ..ros_runtime import RosRuntime
from . import adapters
from .adapters.audio import AUDIO_INFO_TYPE, audio_info_topic, check_wave
from .adapters.base import KIND_IMAGE, AudioChunk, ImageFrame, MediaAdapter, MediaSettings
from .errors import MediaError
from .imaging import encode_jpeg

LOG = logging.getLogger(__name__)

MAX_VIEWED_TOPICS = 16
VIEW_MAX_WIDTH = 640
VIEW_MAX_FPS = 10.0
AUDIO_QUEUE = 256  # chunks kept per audio topic (readers that fall behind skip ahead)


class _Channel:
    def __init__(self, adapter: MediaAdapter, settings: MediaSettings):
        self.adapter = adapter
        self.settings = settings
        self.lock = threading.Lock()
        self.latest: Any = None
        self.seq = 0
        self.chunks: Deque[Tuple[int, Any]] = deque(maxlen=AUDIO_QUEUE)
        self.info: Any = None
        self.refs = 0
        self.subscriptions: List[Any] = []

    def on_message(self, msg: Any) -> None:
        with self.lock:
            self.seq += 1
            if self.adapter.kind == KIND_IMAGE:
                self.latest = msg
            else:
                self.chunks.append((self.seq, msg))

    def on_info(self, msg: Any) -> None:
        with self.lock:
            self.info = msg


def downmix(chunk: AudioChunk) -> bytes:
    """Interleaved PCM -> mono PCM S16LE."""
    if chunk.channels == 1:
        return chunk.data
    usable = len(chunk.data) // (2 * chunk.channels) * chunk.channels
    pcm = np.frombuffer(chunk.data, dtype='<i2', count=usable).reshape(-1, chunk.channels)
    return pcm.mean(axis=1).astype('<i2').tobytes()


class MediaViewer:
    def __init__(self, runtime: RosRuntime):
        self._runtime = runtime
        self._lock = threading.Lock()
        self._channels: Dict[str, _Channel] = {}

    def _topic_type(self, topic: str) -> str:
        types = dict(self._runtime.topic_names_and_types()).get(topic)
        if not types:
            raise MediaError('not_found', f'unknown topic: {topic}', 404)
        if len(types) != 1:
            raise MediaError('media_type_ambiguous', f'{topic} has several types: {types}')
        return types[0]

    def acquire(self, topic: str, sample_rate: int = 16000, channels: int = 1) -> Dict[str, Any]:
        """Start (or join) viewing ``topic``; returns ``{type, kind}``."""
        with self._lock:
            channel = self._channels.get(topic)
            if channel is None:
                if len(self._channels) >= MAX_VIEWED_TOPICS:
                    raise MediaError('too_many', f'at most {MAX_VIEWED_TOPICS} viewers', 429)
                adapter = adapters.get(self._topic_type(topic))
                settings = MediaSettings(sample_rate=sample_rate, channels=channels)
                channel = _Channel(adapter, settings)
                self._subscribe(topic, channel)
                self._channels[topic] = channel
            channel.refs += 1
            return {'type': channel.adapter.type_name, 'kind': channel.adapter.kind}

    def _subscribe(self, topic: str, channel: _Channel) -> None:
        qos = self._runtime.subscription_qos_for(topic)
        msg_type = msgutil.resolve_type(channel.adapter.type_name)
        try:
            channel.subscriptions.append(self._runtime.create_subscription(
                msg_type, topic, channel.on_message, qos))
            if channel.adapter.type_name.startswith('audio_common_msgs/'):
                info = audio_info_topic(topic, channel.settings)
                channel.subscriptions.append(self._runtime.create_subscription(
                    msgutil.resolve_type(AUDIO_INFO_TYPE), info, channel.on_info,
                    self._runtime.subscription_qos_for(info)))
        except Exception as exc:  # rclpy raises several types
            for sub in channel.subscriptions:
                self._runtime.destroy_subscription(sub)
            raise MediaError('subscribe_failed', f'cannot subscribe {topic}: {exc}', 500) from exc

    def release(self, topic: str) -> None:
        with self._lock:
            channel = self._channels.get(topic)
            if channel is None:
                return
            channel.refs -= 1
            if channel.refs > 0:
                return
            del self._channels[topic]
        for sub in channel.subscriptions:
            self._runtime.destroy_subscription(sub)

    def _channel(self, topic: str) -> Optional[_Channel]:
        with self._lock:
            return self._channels.get(topic)

    def latest_image(self, topic: str, after_seq: int) -> Tuple[int, Optional[ImageFrame]]:
        """(seq, JPEG frame <= 640 px wide) if a newer image arrived, else (seq, None)."""
        channel = self._channel(topic)
        if channel is None:
            return after_seq, None
        with channel.lock:
            seq, msg = channel.seq, channel.latest
        if msg is None or seq == after_seq:
            return seq, None
        frame = channel.adapter.from_message(msg, channel.settings)
        return seq, encode_jpeg(frame, VIEW_MAX_WIDTH)

    def audio_since(self, topic: str, after_seq: int) -> Tuple[int, Optional[AudioChunk]]:
        """Mono PCM of the chunks newer than ``after_seq`` joined into one chunk."""
        channel = self._channel(topic)
        if channel is None:
            return after_seq, None
        with channel.lock:
            items = [(s, m) for s, m in channel.chunks if s > after_seq]
            info = channel.info
        if not items:
            return after_seq, None
        settings = channel.settings
        if info is not None:
            check_wave(info)
            settings = MediaSettings(sample_rate=int(info.sample_rate) or settings.sample_rate,
                                     channels=int(info.channels) or settings.channels)
        chunks = [channel.adapter.from_message(m, settings) for _, m in items]
        rate = chunks[0].sample_rate
        mono = b''.join(downmix(c) for c in chunks)
        return items[-1][0], AudioChunk(mono, rate, 1)

    def close(self) -> None:
        with self._lock:
            channels = list(self._channels.values())
            self._channels.clear()
        for sub in itertools.chain.from_iterable(c.subscriptions for c in channels):
            self._runtime.destroy_subscription(sub)
