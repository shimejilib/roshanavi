"""Browser capture (microphone / camera) -> ROS messages through the adapters.

The browser streams binary WebSocket frames: PCM S16LE chunks (mic) or JPEG
images (camera). A :class:`CaptureJob` is an inject job (mode ``capture``)
registered with the injector, so it shows on the map as a dummy source, in the
jobs list and can be stopped like any job. One capture per topic.

Stamps are the server receive time: the browser, the WebSocket hop and the
JPEG encode add tens of milliseconds compared to a real camera / microphone.
"""

import logging
import time
from typing import Any, Callable, Dict, List, Literal, Optional, Tuple

from pydantic import BaseModel, confloat, conint, constr
from rclpy.duration import Duration

from .. import msgutil
from ..jobs import InjectSpec, Job
from ..ros_runtime import RosRuntime, make_qos
from .adapters.base import (KIND_AUDIO, KIND_IMAGE, AudioChunk, Companion, ImageFrame,
                            MediaAdapter, MediaSettings)
from .errors import MediaError
from .imaging import jpeg_size

LOG = logging.getLogger(__name__)

MAX_AUDIO_FRAME_BYTES = 256 * 1024
MAX_IMAGE_FRAME_BYTES = 4 * 1024 * 1024
MAX_CAMERA_FPS = 30.0
AUDIO_RATE_SLACK = 1.5      # accept bursts up to 1.5x real time (+1 s) before dropping
INFO_REPEAT_SEC = 1.0
WARMUP_MAX_SEC = 1.0
WARMUP_POLL_SEC = 0.05
LINGER_SEC = 1.0            # at stop, wait this long for readers to ack the last frames


class CaptureStart(BaseModel):
    """First (text) message on ``/ws/capture``."""

    kind: Literal['audio', 'camera']
    topic: constr(min_length=1, max_length=256)
    type: Optional[constr(max_length=256)] = None
    frame_id: constr(max_length=256) = ''
    # audio: what the browser sends; the published chunk size is chunk_samples
    sample_rate: conint(ge=8000, le=96000) = 16000
    channels: conint(ge=1, le=2) = 1
    chunk_samples: conint(ge=32, le=16384) = 1024
    audio_info: bool = True
    audio_info_topic: Optional[constr(max_length=256)] = None
    # camera
    fps: confloat(gt=0, le=MAX_CAMERA_FPS) = 15.0
    encoding: Literal['rgb8', 'bgr8', 'mono8'] = 'rgb8'
    camera_info: bool = True
    camera_info_topic: Optional[constr(max_length=256)] = None
    reliability: Literal['reliable', 'best_effort'] = 'reliable'

    class Config:
        extra = 'forbid'

    def settings(self) -> MediaSettings:
        return MediaSettings(frame_id=self.frame_id, encoding=self.encoding, format='jpeg',
                             sample_rate=self.sample_rate, channels=self.channels,
                             camera_info=self.camera_info,
                             camera_info_topic=self.camera_info_topic,
                             audio_info=self.audio_info, audio_info_topic=self.audio_info_topic)


class Rechunker:
    """Re-slices a PCM byte stream into fixed-size chunks (pure)."""

    def __init__(self, chunk_bytes: int):
        self._size = chunk_bytes
        self._buf = bytearray()

    def push(self, data: bytes) -> List[bytes]:
        self._buf += data
        count = len(self._buf) // self._size
        chunks = [bytes(self._buf[i * self._size:(i + 1) * self._size]) for i in range(count)]
        del self._buf[:count * self._size]
        return chunks


class MinInterval:
    """Lets an event through at most every ``1 / max_hz`` seconds (pure, clock injectable)."""

    def __init__(self, max_hz: float, clock: Callable[[], float] = time.monotonic,
                 slack: float = 0.8):
        self._interval = slack / max_hz  # small slack: browser timers are not exact
        self._clock = clock
        self._last: Optional[float] = None

    def allow(self) -> bool:
        now = self._clock()
        if self._last is not None and now - self._last < self._interval:
            return False
        self._last = now
        return True


class ByteBudget:
    """Drops audio arriving much faster than real time (misbehaving / malicious client)."""

    def __init__(self, bytes_per_sec: float, clock: Callable[[], float] = time.monotonic):
        self._rate = bytes_per_sec
        self._clock = clock
        self._start = clock()
        self._total = 0

    def allow(self, size: int) -> bool:
        elapsed = self._clock() - self._start
        if self._total + size > self._rate * (elapsed + 1.0) * AUDIO_RATE_SLACK:
            return False
        self._total += size
        return True


class CaptureJob(Job):
    def __init__(self, spec: InjectSpec, runtime: RosRuntime, adapter: MediaAdapter,
                 start: CaptureStart, clock: Callable[[], float] = time.monotonic):
        super().__init__(spec)
        expected = KIND_AUDIO if start.kind == 'audio' else KIND_IMAGE
        if adapter.kind != expected:
            raise MediaError('media_kind_mismatch', f'{adapter.type_name} carries '
                             f'{adapter.kind} data, not {start.kind}')
        self._runtime = runtime
        self._adapter = adapter
        self._start = start
        self._settings = start.settings()
        self._clock = clock
        self._publisher: Any = None
        self._companions: List[Tuple[Companion, Any]] = []
        self._companion_topics: List[str] = []  # kept after teardown for the job list
        self._rechunk = Rechunker(start.chunk_samples * start.channels * 2)
        self._frame_gate = MinInterval(min(start.fps, MAX_CAMERA_FPS), clock)
        self._budget = ByteBudget(start.sample_rate * start.channels * 2, clock)
        self._last_info = 0.0
        self.dropped = 0

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), 'dropped': self.dropped,
                'companions': list(self._companion_topics), 'capture': self._start.kind}

    def begin(self) -> None:
        qos = make_qos(self._start.reliability, 'volatile', 10)
        self._publisher = self._runtime.create_publisher(
            msgutil.resolve_type(self._adapter.type_name), self.spec.topic, qos)
        for comp in self._adapter.companions(self.spec.topic, self._settings):
            comp_qos = make_qos('reliable', 'transient_local', 1) if comp.latched else qos
            self._companions.append((comp, self._runtime.create_publisher(
                msgutil.resolve_type(comp.type_name), comp.topic, comp_qos)))
            self._companion_topics.append(comp.topic)
        self._warmup()

    def _warmup(self) -> None:
        """Wait (<= 1 s) until existing subscribers matched, so the first frames are not lost."""
        pubs = [(self.spec.topic, self._publisher),
                *((comp.topic, pub) for comp, pub in self._companions)]
        expected = [(pub, len(self._runtime.subscriptions_info(topic))) for topic, pub in pubs]
        deadline = time.monotonic() + WARMUP_MAX_SEC
        while (any(pub.get_subscription_count() < n for pub, n in expected)
               and time.monotonic() < deadline):
            time.sleep(WARMUP_POLL_SEC)

    def companion_topics(self) -> List[str]:
        return list(self._companion_topics)

    def feed(self, data: bytes) -> int:
        """Handle one binary frame from the browser; returns messages published."""
        if self._start.kind == 'audio':
            return self._feed_audio(data)
        return self._feed_image(data)

    def _feed_audio(self, data: bytes) -> int:
        frame_bytes = 2 * self._start.channels
        if len(data) > MAX_AUDIO_FRAME_BYTES or len(data) % frame_bytes:
            raise MediaError('invalid_frame', f'audio frames must be PCM int16 x '
                             f'{self._start.channels} channel(s), at most '
                             f'{MAX_AUDIO_FRAME_BYTES} bytes')
        if not self._budget.allow(len(data)):
            self.dropped += 1
            return 0
        sent = 0
        for chunk in self._rechunk.push(data):
            audio = AudioChunk(chunk, self._start.sample_rate, self._start.channels)
            sent += self._publish(audio)
        return sent

    def _feed_image(self, data: bytes) -> int:
        if len(data) > MAX_IMAGE_FRAME_BYTES:
            raise MediaError('invalid_frame', f'camera frames must be at most '
                             f'{MAX_IMAGE_FRAME_BYTES} bytes')
        if not self._frame_gate.allow():
            self.dropped += 1
            return 0
        width, height = jpeg_size(data)
        return self._publish(ImageFrame(width, height, 'jpeg', data))

    def _publish(self, item: Any) -> int:
        stamp = self._runtime.node.get_clock().now().to_msg()  # server receive time
        msg = self._adapter.to_message(item, stamp, self._settings)
        now = self._clock()
        send_info = now - self._last_info >= INFO_REPEAT_SEC
        extra = [(pub, comp.build(stamp, item)) for comp, pub in self._companions
                 if comp.every_frame or send_info]
        with self.lock:
            if self.state != 'running':
                return 0
            self._publisher.publish(msg)
            for pub, side in extra:
                pub.publish(side)
            self.sent += 1
        if send_info:
            self._last_info = now
        size = len(item.data)
        self.record_send(size)
        return 1

    def _teardown(self) -> None:
        with self.lock:
            pubs = [self._publisher, *(p for _, p in self._companions)]
            self._publisher, self._companions = None, []
        # The browser often closes right after its last frame: destroying the publisher at once
        # would drop frames that are still in flight to reliable readers.
        for pub in pubs:
            if pub is not None and not pub.wait_for_all_acked(Duration(seconds=LINGER_SEC)):
                LOG.warning('capture %s: not all frames acknowledged before teardown', self.id)
        for pub in pubs:
            if pub is not None:
                self._runtime.destroy_publisher(pub)
