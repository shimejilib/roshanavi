"""Shared injection job types: request spec, error, and the Job base class."""

import logging
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Dict, Optional, Tuple

from rclpy.exceptions import InvalidTopicNameException
from rclpy.validate_full_topic_name import validate_full_topic_name

LOG = logging.getLogger(__name__)

SEND_RATE_WINDOW_SEC = 5.0
MAX_SEND_SAMPLES = 20000


class InjectError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


@dataclass(frozen=True)
class InjectSpec:
    mode: str
    topic: Optional[str] = None
    type: Optional[str] = None
    payload: Any = None
    rate_hz: Optional[float] = None
    count: Optional[int] = None
    source: Optional[str] = None
    loop: bool = False
    qos: Dict[str, Any] = field(default_factory=dict)
    bag_rate: float = 1.0
    bag_topics: Tuple[str, ...] = ()


def validate_topic(topic: Optional[str]) -> str:
    if not topic:
        raise InjectError('invalid_request', 'topic is required')
    try:
        validate_full_topic_name(topic)
    except InvalidTopicNameException as exc:
        raise InjectError('invalid_request', f'invalid topic name {topic!r}: {exc}') from exc
    return topic


class Job:
    """Common job bookkeeping; subclasses implement ``_begin`` and ``_teardown``."""

    def __init__(self, spec: InjectSpec):
        self.id = uuid.uuid4().hex[:12]
        self.spec = spec
        self.lock = threading.Lock()
        self.state = 'running'
        self.sent = 0
        self.error: Optional[str] = None
        self.created_at = time.time()
        self.finished_at: Optional[float] = None
        self._sends: Deque[Tuple[float, Optional[int]]] = deque(maxlen=MAX_SEND_SAMPLES)

    def record_send(self, size: Optional[int] = None) -> None:
        """Count one published message (``size`` = serialized bytes, if known)."""
        self._sends.append((time.monotonic(), size))

    def send_rate(self, now: Optional[float] = None,
                  window: float = SEND_RATE_WINDOW_SEC) -> Tuple[Optional[float], Optional[float]]:
        """(hz, bytes/s) of what this job actually sent in the last ``window`` seconds."""
        now = time.monotonic() if now is None else now
        recent = [s for s in list(self._sends) if now - s[0] <= window]
        if len(recent) < 2:
            return (0.0, 0.0) if not recent else (None, None)
        span = recent[-1][0] - recent[0][0]
        hz = (len(recent) - 1) / span if span > 0 else None
        sizes = [s[1] for s in recent if s[1] is not None]
        bps = hz * sum(sizes) / len(sizes) if hz is not None and sizes else None
        return hz, bps

    def to_dict(self) -> Dict[str, Any]:
        send_hz, send_bps = self.send_rate()
        with self.lock:
            return {'id': self.id, 'mode': self.spec.mode, 'topic': self.spec.topic,
                    'type': self.spec.type, 'rate_hz': self.spec.rate_hz,
                    'count': self.spec.count, 'source': self.spec.source,
                    'qos': dict(self.spec.qos),
                    'state': self.state, 'sent': self.sent, 'error': self.error,
                    'created_at': self.created_at, 'finished_at': self.finished_at,
                    'send_hz': send_hz, 'send_bps': send_bps}

    @property
    def active(self) -> bool:
        with self.lock:
            return self.state == 'running'

    def finish(self, state: str, error: Optional[str] = None) -> bool:
        """Flip state once; returns False if already finished. Then tears down."""
        with self.lock:
            if self.state != 'running':
                return False
            self.state, self.error, self.finished_at = state, error, time.time()
        if error:
            LOG.warning('inject job %s %s: %s', self.id, state, error)
        self._teardown()
        return True

    def _teardown(self) -> None:
        raise NotImplementedError
