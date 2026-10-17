"""``media`` inject jobs: frames / audio chunks from a source, paced in real time.

Two threads per job. A *reader* thread decodes ahead into a bounded buffer
(:class:`~roshanavi.media.prefetch.Prefetcher`), so ffmpeg start-up, pipe reads
and loop restarts never delay a send. The *pacer* thread starts after a
prebuffer is filled and only does dequeue -> stamp -> publish against absolute
deadlines (:mod:`roshanavi.media.pacing`). Sleeping uses an Event so a stop
wakes it immediately; stopping also closes the source, which kills ffmpeg and
unblocks a pending read. Publishing happens under the job lock after a state
check, and publishers are destroyed only after the state flip, so a stop can
never race a publish on a destroyed publisher (same rule as ``PublishJob``).
"""

import logging
import random
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from rclpy.serialization import serialize_message

from .. import msgutil
from ..jobs import InjectSpec, Job
from ..ros_runtime import RosRuntime, make_qos
from .adapters.base import Companion, MediaAdapter, MediaSettings
from .errors import MediaError
from .pacing import DEFAULT_LATE_POLICY, Pacer, run_paced
from .prefetch import END, Prefetcher, capacity_for, prebuffer_items
from .sources import FrameSource

LOG = logging.getLogger(__name__)

DEFAULT_PREBUFFER_MS = 300.0
PREBUFFER_MAX_SEC = 3.0     # start anyway when the source cannot fill the prebuffer in time
WARMUP_POLL_SEC = 0.05
WARMUP_MAX_SEC = 1.0
INFO_REPEAT_SEC = 1.0       # latched companions (AudioInfo) are also re-sent this often
JOIN_TIMEOUT_SEC = 5.0


class MediaJob(Job):
    pausable = True

    def __init__(self, spec: InjectSpec, runtime: RosRuntime, adapter: MediaAdapter,
                 source: FrameSource, settings: MediaSettings, jitter_sec: float = 0.0,
                 drop_ratio: float = 0.0, rng: Optional[random.Random] = None,
                 prebuffer_ms: float = DEFAULT_PREBUFFER_MS,
                 late_policy: str = DEFAULT_LATE_POLICY):
        super().__init__(spec)
        self._runtime = runtime
        self._adapter = adapter
        self._source = source
        self._settings = settings
        self._rng = rng or random.Random()
        self._pacer = Pacer(source.period, jitter_sec, self._rng, late_policy=late_policy)
        self._prebuffer_items = prebuffer_items(prebuffer_ms, source.period)
        self._prefetch = Prefetcher(source, capacity_for(self._prebuffer_items),
                                    name=f'media-reader-{self.id}')
        self._drop_ratio = drop_ratio
        self._stop = threading.Event()
        self._publisher: Any = None
        self._companions: List[Tuple[Companion, Any]] = []
        self._companion_topics: List[str] = []  # kept after teardown for the job list
        self._thread: Optional[threading.Thread] = None
        self.dropped = 0
        self._last_info = 0.0
        self._size: Optional[int] = None  # serialized size of the first message

    def to_dict(self) -> Dict[str, Any]:
        return {**super().to_dict(), 'dropped': self.dropped,
                'companions': list(self._companion_topics), 'period_sec': self._pacer.period,
                'late_policy': self._pacer.late_policy, 'late_events': self._pacer.late_events,
                'max_lateness_ms': self._pacer.max_lateness_ms,
                'late_skipped': self._pacer.late_skipped}

    def begin(self) -> None:
        qos = make_qos(**self.spec.qos) if self.spec.qos else make_qos()
        self._publisher = self._runtime.create_publisher(
            msgutil.resolve_type(self._adapter.type_name), self.spec.topic, qos)
        for comp in self._adapter.companions(self.spec.topic, self._settings):
            comp_qos = make_qos('reliable', 'transient_local', 1) if comp.latched else qos
            pub = self._runtime.create_publisher(msgutil.resolve_type(comp.type_name),
                                                 comp.topic, comp_qos)
            self._companions.append((comp, pub))
            self._companion_topics.append(comp.topic)
        self._thread = threading.Thread(target=self._run, name=f'media-{self.id}', daemon=True)
        self._thread.start()

    def _warmup(self) -> None:
        expected = len(self._runtime.subscriptions_info(self.spec.topic))
        deadline = time.monotonic() + WARMUP_MAX_SEC
        while not self._stop.is_set() and time.monotonic() < deadline:
            with self.lock:
                if self._publisher is None or self._publisher.get_subscription_count() >= expected:
                    return
            self._stop.wait(WARMUP_POLL_SEC)

    def _run(self) -> None:
        try:
            self._prefetch.start()  # decode runs while we wait for subscribers
            self._warmup()
            self._await_prebuffer()
            self._loop()
        except MediaError as exc:
            self.finish('error', str(exc))
        except Exception as exc:  # surface any failure in the job status
            LOG.exception('media job %s failed', self.id)
            self.finish('error', f'{type(exc).__name__}: {exc}')
        else:
            self.finish('done')

    def _await_prebuffer(self) -> None:
        if self._stop.is_set():
            return
        if not self._prefetch.wait_ready(self._prebuffer_items, PREBUFFER_MAX_SEC):
            LOG.info('media job %s: prebuffer not full after %.0f s (%d/%d), starting anyway',
                     self.id, PREBUFFER_MAX_SEC, self._prefetch.depth, self._prebuffer_items)

    def _loop(self) -> None:
        self._pacer.reset()  # the schedule starts once the prebuffer is filled
        run_paced(self._pacer, self._take, self._send, self._stop.wait, END,
                  limit=self.spec.count)

    def _take(self) -> Any:
        return END if self._stop.is_set() else self._prefetch.get()

    def _send(self, item: Any) -> bool:
        """Pacer-thread step after the deadline: maybe drop, else stamp + publish."""
        if self.paused:  # paused frames are read and skipped so timing stays on schedule
            return True
        if self._drop_ratio and self._rng.random() < self._drop_ratio:
            self.dropped += 1
            return True
        now = time.monotonic()
        send_info = now - self._last_info >= INFO_REPEAT_SEC
        if not self._publish(item, send_info):
            return False
        if send_info:
            self._last_info = now
        return True

    def _publish(self, item: Any, send_info: bool) -> bool:
        stamp = self._runtime.node.get_clock().now().to_msg()
        msg = self._adapter.to_message(item, stamp, self._settings)
        extra = [(pub, comp.build(stamp, item)) for comp, pub in self._companions
                 if comp.every_frame or send_info]
        if self._size is None:
            self._size = len(serialize_message(msg))
        with self.lock:
            if self.state != 'running':
                return False
            self._publisher.publish(msg)
            for pub, side in extra:
                pub.publish(side)
            self.sent += 1
        self.record_send(self._size)
        return True

    def _teardown(self) -> None:
        self._stop.set()
        self._source.close()
        self._prefetch.close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=JOIN_TIMEOUT_SEC)
        with self.lock:
            pubs = [self._publisher, *(p for _, p in self._companions)]
            self._publisher, self._companions = None, []
        for pub in pubs:
            if pub is not None:
                self._runtime.destroy_publisher(pub)
