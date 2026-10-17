"""Reader thread that decodes ahead of the pacer into a bounded buffer.

The pacer thread must never wait on ffmpeg (pipe reads, decode start-up, a
restart when looping), so a separate reader thread pulls items from the
:class:`~roshanavi.media.sources.FrameSource` and the pacer only dequeues.
Memory stays bounded by an item count and a byte budget.
"""

import logging
import math
import threading
from collections import deque
from typing import Any, Deque, Optional

from .sources import FrameSource

LOG = logging.getLogger(__name__)

END = object()                      # returned by get() at end of media / after close()
READAHEAD_EXTRA_ITEMS = 4           # buffer capacity beyond the prebuffer
MAX_BUFFER_BYTES = 96 * 1024 * 1024
JOIN_TIMEOUT_SEC = 5.0


def prebuffer_items(prebuffer_ms: float, period: float) -> int:
    """Items that cover ``prebuffer_ms`` of media at ``period`` seconds per item (>= 1)."""
    return max(1, math.ceil(prebuffer_ms / 1000.0 / period))


def capacity_for(prebuffer: int) -> int:
    return max(prebuffer + READAHEAD_EXTRA_ITEMS, 2 * prebuffer)


def _size_of(item: Any) -> int:
    return len(getattr(item, 'data', b''))


class Prefetcher:
    """Bounded queue filled by a reader thread; ``get`` is for the pacer thread."""

    def __init__(self, source: FrameSource, capacity: int, name: str = 'media-reader',
                 max_bytes: int = MAX_BUFFER_BYTES):
        self._source = source
        self._capacity = max(1, capacity)
        self._max_bytes = max_bytes
        self._cond = threading.Condition()
        self._items: Deque[Any] = deque()
        self._bytes = 0
        self._finished = False
        self._full = False        # the reader hit the capacity at least once
        self._closed = False
        self._error: Optional[BaseException] = None
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)

    def start(self) -> None:
        self._thread.start()

    # ---- reader side -----------------------------------------------------
    def _run(self) -> None:
        try:
            while True:
                item = self._source.next()
                if item is None or not self._put(item):
                    break
        except Exception as exc:  # handed to the pacer thread, which fails the job
            with self._cond:
                self._error = exc
        finally:
            with self._cond:
                self._finished = True
                self._cond.notify_all()

    def _has_room(self, size: int) -> bool:
        if not self._items:
            return True
        return len(self._items) < self._capacity and self._bytes + size <= self._max_bytes

    def _put(self, item: Any) -> bool:
        size = _size_of(item)
        with self._cond:
            while not self._closed and not self._has_room(size):
                self._full = True
                self._cond.notify_all()
                self._cond.wait()
            if self._closed:
                return False
            self._items.append(item)
            self._bytes += size
            self._cond.notify_all()
            return True

    # ---- pacer side ------------------------------------------------------
    def wait_ready(self, items: int, timeout: float) -> bool:
        """Block until ``items`` are buffered (or the buffer is full / media ended).

        Returns False on timeout or close; the caller then starts anyway or stops.
        """
        with self._cond:
            return self._cond.wait_for(
                lambda: self._closed or self._finished or self._full or len(self._items) >= items,
                timeout=timeout) and not self._closed

    def get(self) -> Any:
        """Next item; ``END`` at the end of the media or after close. Re-raises a reader error."""
        with self._cond:
            while not self._items and not self._finished and not self._closed:
                self._cond.wait()
            if self._items and not self._closed:
                item = self._items.popleft()
                self._bytes -= _size_of(item)
                self._cond.notify_all()
                return item
            if self._error is not None and not self._closed:
                error, self._error = self._error, None
                raise error
            return END

    @property
    def depth(self) -> int:
        with self._cond:
            return len(self._items)

    def close(self) -> None:
        """Wake every waiter and join the reader (the owner closes the source first)."""
        with self._cond:
            self._closed = True
            self._items.clear()
            self._bytes = 0
            self._cond.notify_all()
        if self._thread.is_alive() and self._thread is not threading.current_thread():
            self._thread.join(timeout=JOIN_TIMEOUT_SEC)
            if self._thread.is_alive():
                LOG.warning('media reader %s did not stop within %.0f s', self._thread.name,
                            JOIN_TIMEOUT_SEC)
