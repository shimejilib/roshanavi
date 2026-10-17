"""Shared injection job types: request spec, error, and the Job base class."""

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Optional, Tuple

from rclpy.exceptions import InvalidTopicNameException
from rclpy.validate_full_topic_name import validate_full_topic_name

LOG = logging.getLogger(__name__)


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

    def to_dict(self) -> Dict[str, Any]:
        with self.lock:
            return {'id': self.id, 'mode': self.spec.mode, 'topic': self.spec.topic,
                    'type': self.spec.type, 'rate_hz': self.spec.rate_hz,
                    'count': self.spec.count, 'source': self.spec.source,
                    'qos': dict(self.spec.qos),
                    'state': self.state, 'sent': self.sent, 'error': self.error,
                    'created_at': self.created_at, 'finished_at': self.finished_at}

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
