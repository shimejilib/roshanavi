"""Watches the server's own open-file-descriptor count against RLIMIT_NOFILE.

A leak shows up as a slow climb that ends in ``OSError: [Errno 24]`` somewhere
random; warning at 70 % of the soft limit (once per excursion) makes it visible
long before that.
"""

import logging
import os
import resource
from typing import Callable, Optional, Tuple

LOG = logging.getLogger(__name__)

WARN_FRACTION = 0.7


def count_fds(path: str = '/proc/self/fd') -> Optional[int]:
    try:
        return len(os.listdir(path))
    except OSError:
        return None


class FdGuard:
    def __init__(self, counter: Callable[[], Optional[int]] = count_fds,
                 limit: Callable[[], Tuple[int, int]] = lambda: resource.getrlimit(
                     resource.RLIMIT_NOFILE)):
        self._counter, self._limit = counter, limit
        self._warned = False

    def check(self) -> bool:
        """True while the count is above the threshold; logs once per excursion."""
        used, (soft, _hard) = self._counter(), self._limit()
        if used is None or soft in (-1, resource.RLIM_INFINITY):
            return False
        over = used > soft * WARN_FRACTION
        if over and not self._warned:
            LOG.warning('open file descriptors: %d of %d (%.0f%%); a descriptor leak is likely',
                        used, soft, 100.0 * used / soft)
        self._warned = over
        return over
