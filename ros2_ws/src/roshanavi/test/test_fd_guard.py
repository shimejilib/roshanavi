import logging

from roshanavi.fd_guard import FdGuard


class _Collect(logging.Handler):
    def __init__(self):
        super().__init__(logging.WARNING)
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


def _guard(used, soft=1000):
    return FdGuard(counter=lambda: used[0], limit=lambda: (soft, soft))


def test_warns_once_above_seventy_percent_and_again_after_recovering():
    handler = _Collect()
    logger = logging.getLogger('roshanavi.fd_guard')
    logger.addHandler(handler)
    try:
        used = [100]
        guard = _guard(used)
        assert guard.check() is False
        used[0] = 750
        assert guard.check() is True
        assert guard.check() is True
        assert len(handler.messages) == 1 and '750 of 1000' in handler.messages[0]
        used[0] = 200
        assert guard.check() is False
        used[0] = 900
        assert guard.check() is True
        assert len(handler.messages) == 2
    finally:
        logger.removeHandler(handler)


def test_unknown_count_or_unlimited_never_warns():
    assert FdGuard(counter=lambda: None, limit=lambda: (10, 10)).check() is False
    assert FdGuard(counter=lambda: 10 ** 6, limit=lambda: (-1, -1)).check() is False
