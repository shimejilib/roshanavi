"""Injection job management (once / periodic / stream / bag / media).

Publishing jobs own a publisher and rclpy timers on the shared node; their
callbacks run on the executor thread. Each job has its own lock guarding its
state; ``publish()`` happens under that lock after a state check, and teardown
(destroying timers/publisher) happens *after* the state flip and outside the
lock, so a stop from the API thread can never race a publish on a destroyed
publisher.

Before the first message a job waits (up to ``WARMUP_MAX_SEC``) until the
publisher has matched as many subscriptions as existed on the topic when the
job started, so ``once`` messages are not lost to discovery latency.
"""

import logging
import random
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

from rclpy.duration import Duration
from rclpy.serialization import serialize_message

from . import msgutil
from .bagplay import BagJob
from .expr import ExprError, PayloadTemplate
from .files import FileAccessError, load_stream, resolve_in_data_dir
from .jobs import InjectError, InjectSpec, Job, validate_topic
from .media.errors import MediaError
from .media.factory import create_media_job
from .ros_runtime import RosRuntime, make_qos

LOG = logging.getLogger(__name__)

MODES = ('once', 'periodic', 'stream', 'bag', 'media')
MAX_RATE_HZ = 1000.0
MAX_ACTIVE_JOBS = 32
MAX_FINISHED_JOBS = 100
WARMUP_POLL_SEC = 0.05
WARMUP_MAX_SEC = 1.0
LINGER_SEC = 1.0


def _validate_rate(spec: InjectSpec, required: bool) -> None:
    if spec.rate_hz is None:
        if required:
            raise InjectError('invalid_request', f'rate_hz is required for mode {spec.mode}')
        return
    if not 0 < spec.rate_hz <= MAX_RATE_HZ:
        raise InjectError('invalid_request', f'rate_hz must be in (0, {MAX_RATE_HZ}]')


class RecordSource:
    """Yields the message dict for send index ``i`` at job time ``t``."""

    def has(self, i: int) -> bool:
        raise NotImplementedError

    def get(self, i: int, t: float) -> Any:
        raise NotImplementedError


class PayloadSource(RecordSource):
    """once/periodic: renders ``${...}`` expressions on every send."""

    def __init__(self, spec: InjectSpec, rng: random.Random):
        try:
            self._tmpl = PayloadTemplate(spec.payload or {})
        except ExprError as exc:
            raise InjectError('invalid_expression', str(exc)) from exc
        self._limit = 1 if spec.mode == 'once' else spec.count
        self._rng = rng

    def has(self, i: int) -> bool:
        return self._limit is None or i < self._limit

    def get(self, i: int, t: float) -> Any:
        return self._tmpl.render({'i': i, 't': t, 'now': time.time()}, self._rng)


class StreamSource(RecordSource):
    """stream: records in file order, optionally looping, optionally capped by count."""

    def __init__(self, records: Sequence[Any], loop: bool, count: Optional[int]):
        if not records:
            raise InjectError('invalid_file', 'stream has no records')
        self._records = list(records)
        self._loop = loop
        self._count = count

    def has(self, i: int) -> bool:
        if self._count is not None and i >= self._count:
            return False
        return self._loop or i < len(self._records)

    def get(self, i: int, t: float) -> Any:
        return self._records[i % len(self._records)]


class PublishJob(Job):
    def __init__(self, spec: InjectSpec, runtime: RosRuntime, source: RecordSource,
                 clock: Callable[[], float]):
        super().__init__(spec)
        self._runtime = runtime
        self._source = source
        self._clock = clock
        self._msg_type = msgutil.resolve_type(spec.type)
        self._qos = make_qos(**spec.qos) if spec.qos else make_qos()
        self._publisher: Any = None
        self._warmup_timer: Any = None
        self._timer: Any = None
        self._expected_subs = 0
        self._started = 0.0
        self._msg_size: Optional[int] = None  # serialized size of the first message

    def validate_first(self) -> None:
        """Render+build the first message eagerly so bad payloads fail at submit time."""
        if not self._source.has(0):
            raise InjectError('invalid_request', 'job would send no messages')
        try:
            first = self._build(self._source.get(0, 0.0))
        except ExprError as exc:
            raise InjectError('invalid_expression', str(exc)) from exc
        try:  # approximate bytes/s of this job (later messages may differ slightly)
            self._msg_size = len(serialize_message(first))
        except Exception as exc:  # size is informational only
            LOG.debug('cannot serialize first message of job %s: %s', self.id, exc)

    def _build(self, record: Any) -> Any:
        try:
            return msgutil.build(self.spec.type, record)
        except msgutil.MsgUtilError as exc:
            raise InjectError(exc.code, str(exc)) from exc

    def begin(self) -> None:
        self._expected_subs = len(self._runtime.subscriptions_info(self.spec.topic))
        self._publisher = self._runtime.create_publisher(self._msg_type, self.spec.topic, self._qos)
        self._started = self._clock()
        self._warmup_timer = self._runtime.create_timer(WARMUP_POLL_SEC, self._on_warmup)

    def _on_warmup(self) -> None:
        with self.lock:
            if self.state != 'running' or self._warmup_timer is None:
                return
            timer = self._warmup_timer
            matched = self._publisher.get_subscription_count()
        if matched < self._expected_subs and self._clock() - self._started < WARMUP_MAX_SEC:
            return
        with self.lock:
            if self.state != 'running':
                return
            self._warmup_timer = None
        self._runtime.destroy_timer(timer)
        self._started = self._clock()
        if not self._send_next() or self.spec.mode == 'once':
            return
        periodic = self._runtime.create_timer(1.0 / self.spec.rate_hz, self._send_next)
        with self.lock:
            if self.state == 'running':
                self._timer, periodic = periodic, None
        if periodic is not None:  # stopped while we were creating it
            self._runtime.destroy_timer(periodic)

    def _send_next(self) -> bool:
        """Publish one message. Returns True while the job should keep running."""
        try:
            with self.lock:
                if self.state != 'running':
                    return False
                if self._source.has(self.sent):
                    record = self._source.get(self.sent, self._clock() - self._started)
                    self._publisher.publish(self._build(record))
                    self.sent += 1
                    self.record_send(self._msg_size)
                more = self._source.has(self.sent)
            if not more:
                self._linger()
        except (InjectError, ExprError) as exc:
            self.finish('error', str(exc))
            return False
        except Exception as exc:  # publish failures etc.: surface in job status
            LOG.exception('inject job %s failed', self.id)
            self.finish('error', f'{type(exc).__name__}: {exc}')
            return False
        if not more:
            self.finish('done')
        return more

    def _linger(self) -> None:
        """Let reliable readers ack the last messages before the publisher is destroyed."""
        publisher = self._publisher
        if publisher is not None and not publisher.wait_for_all_acked(
                Duration(seconds=LINGER_SEC)):
            LOG.warning('inject job %s: not all messages acknowledged before teardown', self.id)

    def _teardown(self) -> None:
        with self.lock:
            timers = (self._warmup_timer, self._timer)
            publisher = self._publisher
            self._warmup_timer = self._timer = self._publisher = None
        for timer in timers:
            if timer is not None:
                self._runtime.destroy_timer(timer)
        if publisher is not None:
            self._runtime.destroy_publisher(publisher)


class Injector:
    def __init__(self, runtime: RosRuntime, data_dir: str,
                 clock: Callable[[], float] = time.monotonic,
                 rng: Optional[random.Random] = None, extra_roots: Sequence[str] = ()):
        self._runtime = runtime
        self._data_dir = data_dir
        self._extra_roots = tuple(extra_roots)  # e.g. the workspace (calibration files)
        self._clock = clock
        self._rng = rng or random.Random()
        self._lock = threading.Lock()
        self._jobs: Dict[str, Job] = {}

    def _check_capacity(self) -> None:
        with self._lock:
            active = sum(1 for j in self._jobs.values() if j.active)
        if active >= MAX_ACTIVE_JOBS:
            raise InjectError('too_many_jobs', f'at most {MAX_ACTIVE_JOBS} active jobs', 429)

    def start(self, spec: InjectSpec) -> Dict[str, Any]:
        self._check_capacity()
        job = self._create(spec)
        self.register(job)
        LOG.info('inject job %s started: %s %s', job.id, spec.mode, spec.topic or spec.source)
        return job.to_dict()

    def register(self, job: Job, check_capacity: bool = False) -> None:
        """Begin a job and track it (also used for browser capture jobs)."""
        if check_capacity:
            self._check_capacity()
        job.begin()
        with self._lock:
            self._jobs[job.id] = job
            self._prune_finished()

    def active_jobs(self) -> List[Job]:
        with self._lock:
            return [j for j in self._jobs.values() if j.active]

    def _create(self, spec: InjectSpec) -> Job:
        if spec.mode not in MODES:
            raise InjectError('invalid_request', f'mode must be one of {MODES}')
        if spec.mode == 'media':
            try:
                return create_media_job(spec, self._runtime, self._data_dir, self._extra_roots)
            except MediaError as exc:
                raise InjectError(exc.code, str(exc), exc.status) from exc
        if spec.mode == 'bag':
            return BagJob(spec, self._resolve(spec.source))
        validate_topic(spec.topic)
        if not spec.type:
            raise InjectError('invalid_request', 'type is required')
        _validate_rate(spec, required=spec.mode != 'once')
        if spec.count is not None and spec.count < 1:
            raise InjectError('invalid_request', 'count must be >= 1')
        if spec.mode == 'stream':
            try:
                records = load_stream(self._resolve(spec.source))
            except FileAccessError as exc:
                raise InjectError(exc.code, str(exc)) from exc
            source: RecordSource = StreamSource(records, spec.loop, spec.count)
        else:
            source = PayloadSource(spec, self._rng)
        try:
            job = PublishJob(spec, self._runtime, source, self._clock)
        except msgutil.MsgUtilError as exc:
            raise InjectError(exc.code, str(exc)) from exc
        except ValueError as exc:  # make_qos
            raise InjectError('invalid_request', str(exc)) from exc
        job.validate_first()
        return job

    def _resolve(self, source: Optional[str]) -> str:
        if not source:
            raise InjectError('invalid_request', 'source is required for stream/bag mode')
        try:
            return resolve_in_data_dir(self._data_dir, source)
        except FileAccessError as exc:
            raise InjectError(exc.code, str(exc), 404 if exc.code == 'not_found' else 400) from exc

    def _prune_finished(self) -> None:
        finished = [j for j in self._jobs.values() if not j.active]
        for job in finished[:max(0, len(finished) - MAX_FINISHED_JOBS)]:
            del self._jobs[job.id]

    def stop(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise InjectError('not_found', f'no such job: {job_id}', 404)
        job.finish('stopped')
        return job.to_dict()

    def get(self, job_id: str) -> Dict[str, Any]:
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise InjectError('not_found', f'no such job: {job_id}', 404)
        return job.to_dict()

    def spec(self, job_id: str) -> InjectSpec:
        """The full request of a job (including payload), e.g. to persist it."""
        with self._lock:
            job = self._jobs.get(job_id)
        if job is None:
            raise InjectError('not_found', f'no such job: {job_id}', 404)
        return job.spec

    def list(self) -> List[Dict[str, Any]]:
        with self._lock:
            jobs = list(self._jobs.values())
        return [j.to_dict() for j in jobs]

    def close(self) -> None:
        with self._lock:
            jobs = list(self._jobs.values())
        for job in jobs:
            job.finish('stopped')
