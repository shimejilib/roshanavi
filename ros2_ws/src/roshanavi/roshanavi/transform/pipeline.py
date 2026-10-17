"""Message flow of a transform node, without rclpy (unit-tested with fake clocks).

Order for every received message::

    receive -> join (several inputs: latest value of each) -> drop (ratio)
            -> condition + mapping (map mode) -> throttle (max Hz) -> delay -> publish

- Drop comes first so a dropped message costs nothing.
- Throttle comes after the condition, so filtered messages do not use up the rate.
- Delay keeps the order of messages with a fixed delay; with a random range a
  later message may overtake an earlier one (like a real network).
"""

import heapq
import itertools
import logging
import random
import threading
import time
from dataclasses import asdict, dataclass
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..launcher.schema import DelaySpec

LOG = logging.getLogger(__name__)

MAX_PENDING = 10_000  # delayed messages waiting to be sent; more are dropped (overflow)


@dataclass
class Stats:
    received: int = 0
    published: int = 0
    filtered: int = 0   # the condition was false
    dropped: int = 0    # drop_ratio
    throttled: int = 0  # over throttle_hz
    waiting: int = 0    # several inputs: not every input has a value yet
    overflow: int = 0   # too many delayed messages pending
    errors: int = 0     # expression / build / publish failures
    last_error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Gate:
    """Drop ratio and throttle decisions (deterministic with an injected rng / clock)."""

    def __init__(self, drop_ratio: float = 0.0, throttle_hz: Optional[float] = None,
                 delay: Optional[DelaySpec] = None, rng: Optional[random.Random] = None):
        self._drop_ratio = drop_ratio
        self._min_interval = 1.0 / throttle_hz if throttle_hz else 0.0
        self._delay = delay
        self._rng = rng or random.Random()
        self._last_pass: Optional[float] = None
        self._lock = threading.Lock()

    def drop(self) -> bool:
        if self._drop_ratio <= 0:
            return False
        with self._lock:
            return self._drop_ratio >= 1 or self._rng.random() < self._drop_ratio

    def throttle(self, now: float) -> bool:
        """True when the message must be skipped to stay under ``throttle_hz``."""
        if self._min_interval <= 0:
            return False
        with self._lock:
            # A small tolerance keeps exact-rate inputs (e.g. 10 Hz into 10 Hz) from
            # losing every other message to timer jitter.
            if self._last_pass is not None and now - self._last_pass < self._min_interval * 0.95:
                return True
            self._last_pass = now
            return False

    def delay_sec(self) -> float:
        if self._delay is None:
            return 0.0
        low = self._delay.min_ms
        high = self._delay.max_ms if self._delay.max_ms is not None else low
        if high <= low:
            return low / 1000.0
        with self._lock:
            return self._rng.uniform(low, high) / 1000.0


class Joiner:
    """Latest value of each input; decides when a combined output is computed."""

    def __init__(self, aliases: Sequence[str], trigger: str = 'any'):
        self._aliases = tuple(aliases)
        self._trigger = trigger
        self._latest: Dict[str, Any] = {}
        self._lock = threading.Lock()

    def update(self, alias: str, value: Any) -> Tuple[str, Optional[Dict[str, Any]]]:
        """``('ready', values)``, ``('waiting', None)`` or ``('stored', None)``.

        ``waiting``: some input has no value yet. ``stored``: kept as the latest
        value, but this input is not the trigger.
        """
        with self._lock:
            self._latest[alias] = value
            if len(self._latest) < len(self._aliases):
                return 'waiting', None
            if self._trigger != 'any' and alias != self._trigger:
                return 'stored', None
            return 'ready', dict(self._latest)


class DelayQueue:
    """Sends items at their due time from one worker thread (``send`` is the publisher)."""

    def __init__(self, send: Callable[[Any], None], on_overflow: Callable[[], None],
                 clock: Callable[[], float] = time.monotonic, max_pending: int = MAX_PENDING):
        self._send = send
        self._on_overflow = on_overflow
        self._clock = clock
        self._max = max_pending
        self._heap: List[Tuple[float, int, Any]] = []
        self._seq = itertools.count()
        self._cond = threading.Condition()
        self._closed = False
        self._thread = threading.Thread(target=self._run, name='transform-delay', daemon=True)
        self._thread.start()

    def put(self, item: Any, delay_sec: float) -> None:
        with self._cond:
            if self._closed:
                return
            if len(self._heap) >= self._max:
                self._on_overflow()
                return
            heapq.heappush(self._heap, (self._clock() + delay_sec, next(self._seq), item))
            self._cond.notify()

    def pending(self) -> int:
        with self._cond:
            return len(self._heap)

    def _run(self) -> None:
        while True:
            with self._cond:
                while not self._closed and (not self._heap
                                            or self._heap[0][0] > self._clock()):
                    timeout = self._heap[0][0] - self._clock() if self._heap else None
                    self._cond.wait(timeout)
                if self._closed:
                    return
                _, _, item = heapq.heappop(self._heap)
            try:
                self._send(item)
            except Exception:  # a publish failure must not kill the worker
                LOG.exception('sending a delayed message failed')

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._heap.clear()
            self._cond.notify_all()
        self._thread.join(timeout=2.0)
