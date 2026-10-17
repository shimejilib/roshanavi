"""Record mode (記録モード): watch topics + the UI's operations as one timeline.

While a session is active the server routes for inject start / stop and target
start / stop / restart report each operation here (:meth:`ScenarioRecorder.note_op`),
and every watched topic is subscribed. The UI reads the timeline (``events``),
turns operations into steps and clicked messages into expectations (web
``scenarios/record*.ts``). ``measure`` runs the runner's own judging code
(window_rate, stamp / order pairing) over a selected time range so the UI can
propose thresholds.

Times are seconds since the session started (monotonic). At most
:data:`MAX_WATCH` topics, :data:`MAX_EVENTS` events (oldest messages dropped first,
operations are kept), :data:`DISPLAY_HZ` messages per topic per second on the
timeline after a burst of :data:`DISPLAY_BURST` (all receive times are kept for
``measure``), :data:`MAX_SESSION_SEC`.
"""

import logging
import threading
import time
import uuid
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Sequence, Tuple

from .. import msgutil
from ..jobs import validate_topic
from ..ros_runtime import RosRuntime, make_qos
from ..stats import window_rate
from .checks import Record, pair_by_order, pair_by_stamp, percentile
from .fields import json_safe, plain_capped, stamp_ns

LOG = logging.getLogger(__name__)

MAX_WATCH = 8
MAX_EVENTS = 5000
MAX_TIMES = 50000
DISPLAY_HZ = 10.0
DISPLAY_BURST = 10.0
MAX_SESSION_SEC = 30 * 60.0
SUB_DEPTH = 100


class RecordError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


class _Watch:
    def __init__(self, session: 'Session', topic: str, type_name: str):
        self.session = session
        self.topic = topic
        self.type_name = type_name
        self.subscription: Any = None
        self.times: Deque[Tuple[float, Optional[int]]] = deque(maxlen=MAX_TIMES)
        self.tokens = DISPLAY_BURST
        self.last_t = 0.0
        self.count = 0

    def on_message(self, msg: Any) -> None:
        t = time.monotonic() - self.session.started
        plain = plain_capped(msg)
        self.times.append((t, stamp_ns(plain)))
        self.count += 1
        # Token bucket: a slow topic shows every message (also two close together); a fast
        # one is thinned to DISPLAY_HZ on the timeline.
        self.tokens = min(DISPLAY_BURST, self.tokens + (t - self.last_t) * DISPLAY_HZ)
        self.last_t = t
        if self.tokens < 1.0:
            return
        self.tokens -= 1.0
        self.session.add({'kind': 'msg', 'topic': self.topic, 'type': self.type_name,
                          'data': json_safe(msgutil.to_display(msg))}, t)


class Session:
    def __init__(self, watch: Sequence[str]):
        self.id = uuid.uuid4().hex[:12]
        self.started = time.monotonic()
        self.started_at = time.time()
        self.watch = list(watch)
        self.active = True
        self.stopped_sec: Optional[float] = None
        self._lock = threading.Lock()
        self._events: List[Dict[str, Any]] = []
        self._seq = 0
        self.dropped = 0

    def now(self) -> float:
        return time.monotonic() - self.started

    def add(self, event: Dict[str, Any], t: Optional[float] = None) -> None:
        with self._lock:
            if not self.active:
                return
            self._seq += 1
            self._events.append({'seq': self._seq, 't': self.now() if t is None else t, **event})
            if len(self._events) > MAX_EVENTS:
                index = next((i for i, e in enumerate(self._events) if e['kind'] == 'msg'), 0)
                del self._events[index]
                self.dropped += 1

    def events(self, since: int = 0) -> List[Dict[str, Any]]:
        with self._lock:
            return [e for e in self._events if e['seq'] > since]


class ScenarioRecorder:
    """One recording session at a time (shared by every browser tab)."""

    def __init__(self, runtime: RosRuntime):
        self._runtime = runtime
        self._lock = threading.Lock()
        self._session: Optional[Session] = None
        self._watches: Dict[str, _Watch] = {}
        self._stopped_watches: Dict[str, _Watch] = {}

    @property
    def active(self) -> bool:
        session = self._session
        if session is not None and session.active and session.now() > MAX_SESSION_SEC:
            self.stop()
        return self._session is not None and self._session.active

    def _type_of(self, topic: str) -> str:
        types = dict(self._runtime.topic_names_and_types()).get(topic)
        if not types:
            raise RecordError('not_found', f'{topic} が見つかりません (いま誰も使っていないトピックです)',
                              404)
        if len(types) != 1:
            raise RecordError('unsupported', f'{topic} は複数の型で使われています: {", ".join(types)}')
        return types[0]

    def start(self, watch: Sequence[str]) -> Dict[str, Any]:
        topics = list(dict.fromkeys(watch))
        if not topics:
            raise RecordError('invalid_request', '確かめたい出力トピックを 1 つ以上選んでください')
        if len(topics) > MAX_WATCH:
            raise RecordError('invalid_request', f'見張るトピックは {MAX_WATCH} 個までです')
        for topic in topics:
            validate_topic(topic)
        types = {t: self._type_of(t) for t in topics}
        self.stop()
        session = Session(topics)
        watches = {}
        try:
            for topic, type_name in types.items():
                watch = _Watch(session, topic, type_name)
                pubs = self._runtime.publishers_info(topic)
                reliable = bool(pubs) and all(p.qos_profile.reliability.name == 'RELIABLE'
                                              for p in pubs)
                watch.subscription = self._runtime.create_subscription(
                    msgutil.resolve_type(type_name), topic, watch.on_message,
                    make_qos('reliable' if reliable else 'best_effort', 'volatile', SUB_DEPTH))
                watches[topic] = watch
        except Exception as exc:
            for watch in watches.values():
                self._runtime.destroy_subscription(watch.subscription)
            raise RecordError('subscribe_failed', f'購読できません: {exc}', 500) from exc
        with self._lock:
            self._session, self._watches, self._stopped_watches = session, watches, {}
        LOG.info('scenario recording %s started: %s', session.id, ', '.join(topics))
        return self.status()

    def stop(self) -> Dict[str, Any]:
        with self._lock:
            session, watches = self._session, dict(self._watches)
            self._watches = {}
        if session is not None and session.active:
            session.stopped_sec = session.now()
            session.active = False
        for watch in watches.values():
            if watch.subscription is not None:
                self._runtime.destroy_subscription(watch.subscription)
        # The finished session's watches stay readable for measure() until the next start.
        if watches:
            with self._lock:
                self._stopped_watches = watches
        return self.status()

    def discard(self) -> Dict[str, Any]:
        """Stop and forget the session (after it was saved or thrown away)."""
        self.stop()
        with self._lock:
            self._session, self._stopped_watches = None, {}
        return self.status()

    def note_op(self, op: Dict[str, Any]) -> None:
        """Called by the server routes after a successful operation (no-op when idle)."""
        session = self._session
        if session is not None and session.active:
            session.add({'kind': 'op', 'op': json_safe(op)})

    def status(self) -> Dict[str, Any]:
        session = self._session
        if session is None:
            return {'active': False, 'session': None}
        watches = self._watches or self._stopped_watches
        return {'active': session.active, 'session': {
            'id': session.id, 'watch': session.watch, 'started_at': session.started_at,
            'elapsed_sec': session.stopped_sec if not session.active else session.now(),
            'types': {t: w.type_name for t, w in watches.items()},
            'counts': {t: w.count for t, w in watches.items()}, 'dropped': session.dropped}}

    def events(self, since: int = 0) -> List[Dict[str, Any]]:
        session = self._session
        return session.events(since) if session is not None else []

    # ---- measurements for thresholds -----------------------------------------------------------
    def _times(self, topic: str) -> List[Tuple[float, Optional[int]]]:
        watches = self._watches or self._stopped_watches
        watch = watches.get(topic)
        if watch is None:
            raise RecordError('not_found', f'{topic} は記録していません', 404)
        return list(watch.times)

    def measure(self, kind: str, start: float, end: float, topic: Optional[str] = None,
                input_topic: Optional[str] = None, output_topic: Optional[str] = None,
                match: str = 'header.stamp') -> Dict[str, Any]:
        if end <= start:
            raise RecordError('invalid_request', '区間の終わりは始まりより後にしてください')
        if kind == 'rate':
            times = [t for t, _s in self._times(topic or '') if start <= t <= end]
            hz, note = window_rate(times, end, end - start, retain_sec=end - start)
            return {'kind': kind, 'hz': hz, 'note': note, 'count': len(times)}
        ins = [Record(t, t, {'header': {'stamp': _stamp(s)}} if s is not None else {})
               for t, s in self._times(input_topic or '') if start <= t <= end]
        outs = [Record(t, t, {'header': {'stamp': _stamp(s)}} if s is not None else {})
                for t, s in self._times(output_topic or '') if start <= t <= end]
        if kind == 'throughput':
            return {'kind': kind, 'inputs': len(ins), 'outputs': len(outs),
                    'ratio': len(outs) / len(ins) if ins else None}
        if kind == 'latency':
            pair = pair_by_order if match == 'order' else pair_by_stamp
            latencies, unmatched = pair(ins, outs)
            ms = sorted(v * 1000.0 for v in latencies)
            stats = ({'p50_ms': percentile(ms, 50), 'p95_ms': percentile(ms, 95),
                      'max_ms': ms[-1]} if ms else {'p50_ms': None, 'p95_ms': None,
                                                    'max_ms': None})
            return {'kind': kind, 'match': match, 'pairs': len(ms), 'unmatched': unmatched,
                    **stats}
        raise RecordError('invalid_request', f'unknown measurement {kind!r}')

    def close(self) -> None:
        self.stop()


def _stamp(ns: int) -> Dict[str, int]:
    return {'sec': ns // 1_000_000_000, 'nanosec': ns % 1_000_000_000}

