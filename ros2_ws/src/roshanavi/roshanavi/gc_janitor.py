"""Periodic full garbage collection for the long-running server.

Every WebSocket / HTTP connection object of the ASGI server is a reference cycle. Such a cycle
is promoted to the oldest GC generation while the connection is open (a viewer or the live map
stays open for seconds or hours) and is then only freed by a *full* collection. CPython runs a
full collection only when the objects that survived since the last one exceed 25 % of all
long-lived objects; a server with ~100 k long-lived objects (ROS, FastAPI, pydantic) therefore
carries the garbage of hundreds of closed connections before the first full pass. The memory is
reused afterwards, but the process never gives it back, which looks like a leak on the resource
tab (measured: docs/design/resources.md, メモリの増え方).

One full pass every :data:`INTERVAL_SEC` bounds that garbage. A pass over all ~110 k objects takes
~50 ms with the GIL held (a hiccup for the injection pacing), so the start-up objects are moved
out of the collector's reach first (:func:`freeze_startup_objects`): the pass then only walks what
the server allocated since. :meth:`GcJanitor.tick` is called from the 1 Hz housekeeping; it never
raises.
"""

import gc
import logging
import time
from typing import Callable, Optional

LOG = logging.getLogger(__name__)

INTERVAL_SEC = 60.0


def freeze_startup_objects() -> int:
    """Collect once, then exclude every surviving object from future collections.

    Imports, classes, pydantic models and the ROS runtime live as long as the process does;
    scanning them in every full pass is wasted time. Returns the number of frozen objects.
    """
    gc.collect()
    gc.freeze()
    return gc.get_freeze_count()


class GcJanitor:
    def __init__(self, interval_sec: float = INTERVAL_SEC,
                 collect: Callable[[], int] = gc.collect,
                 clock: Callable[[], float] = time.monotonic):
        self._interval = interval_sec
        self._collect = collect
        self._clock = clock
        self._next = clock() + interval_sec
        self.runs = 0
        self.last_ms: Optional[float] = None

    def tick(self) -> Optional[int]:
        """Run a full collection when one is due; the number of objects freed, else None."""
        now = self._clock()
        if now < self._next:
            return None
        self._next = now + self._interval
        try:
            freed = self._collect()
        except Exception:  # a failing collector must not stop the housekeeping loop
            LOG.exception('periodic gc failed')
            return None
        self.runs += 1
        self.last_ms = round((self._clock() - now) * 1000.0, 2)
        LOG.debug('periodic gc freed %d objects in %.1f ms', freed, self.last_ms)
        return freed
