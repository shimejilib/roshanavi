"""Real-time pacing of media items (pure logic, clock and sleep are injectable).

Items are due at ``t0 + k * period`` (plus optional jitter). The pacer thread
sleeps until that absolute deadline, so a late wake never shifts later items by
itself. What happens when the thread wakes *more than one period late* is the
``late_policy``:

* ``shift``    - re-anchor the timeline at the wake time: the late item goes out
  now and the following ones keep the normal spacing (no burst). Default.
* ``catch_up`` - keep the original timeline: late items go out back to back
  until the schedule is caught up (a burst).
* ``drop``     - skip the late item; the next ones keep the original timeline.

``late_events`` counts wakes later than one period, ``max_lateness_ms`` is the
worst lateness seen (any size).
"""

import random
import time
from typing import Any, Callable, Optional

LATE_POLICIES = ('shift', 'catch_up', 'drop')
DEFAULT_LATE_POLICY = 'shift'


class Pacer:
    """Deadline schedule ``t0 + k * period`` with a late-wake policy."""

    def __init__(self, period: float, jitter_sec: float = 0.0,
                 rng: Optional[random.Random] = None,
                 clock: Callable[[], float] = time.monotonic,
                 late_policy: str = DEFAULT_LATE_POLICY):
        if late_policy not in LATE_POLICIES:
            raise ValueError(f'late_policy must be one of {LATE_POLICIES}')
        self.period = period
        self.late_policy = late_policy
        self.late_events = 0
        self.late_skipped = 0
        self.max_lateness = 0.0
        self._jitter = jitter_sec
        self._rng = rng or random.Random()
        self._clock = clock
        self._t0 = clock()
        self._k = 0
        self._deadline: Optional[float] = None

    @property
    def max_lateness_ms(self) -> float:
        return round(self.max_lateness * 1000.0, 1)

    def reset(self) -> None:
        """Start the schedule now (after the prebuffer is filled)."""
        self._t0, self._k, self._deadline = self._clock(), 0, None

    def next_deadline(self) -> float:
        """Absolute time item ``k`` is due; stable until :meth:`arrive` is called."""
        if self._deadline is None:
            jitter = self._rng.uniform(-self._jitter, self._jitter) if self._jitter else 0.0
            self._deadline = self._t0 + self._k * self.period + jitter
        return self._deadline

    def arrive(self, now: float) -> bool:
        """Account for the wake at ``now``; True when the item should be sent."""
        deadline = self.next_deadline()
        lateness = max(0.0, now - deadline)
        self.max_lateness = max(self.max_lateness, lateness)
        late = lateness > self.period
        if late:
            self.late_events += 1
        self._deadline = None
        if late and self.late_policy == 'drop':
            self._k += 1
            self.late_skipped += 1
            return False
        if late and self.late_policy == 'shift':
            self._t0, self._k = now, 0
        self._k += 1
        return True


def sleep_until(deadline: float, clock: Callable[[], float],
                sleep: Callable[[float], bool]) -> bool:
    """Sleep to an absolute ``deadline``; True when ``sleep`` reports an interruption.

    ``sleep(seconds)`` returns True if it was interrupted (stop requested). Early
    returns are retried, so the deadline is never undershot.
    """
    remaining = deadline - clock()
    while remaining > 0:
        if sleep(remaining):
            return True
        remaining = deadline - clock()
    return False


def run_paced(pacer: Pacer, take: Callable[[], Any], send: Callable[[Any], bool],
              sleep: Callable[[float], bool], end: Any,
              clock: Callable[[], float] = time.monotonic,
              limit: Optional[int] = None) -> None:
    """Pacer loop: dequeue -> sleep to the deadline -> (stamp, publish) via ``send``.

    ``take()`` returns the next item or ``end``; ``send(item)`` returns False to
    stop. ``limit`` caps the number of items taken (skipped ones included).
    """
    taken = 0
    while limit is None or taken < limit:
        item = take()
        if item is end:
            return
        taken += 1
        if sleep_until(pacer.next_deadline(), clock, sleep):
            return
        if pacer.arrive(clock()) and not send(item):
            return
