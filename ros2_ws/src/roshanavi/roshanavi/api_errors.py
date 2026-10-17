"""Generic API error for routes outside the injector / launcher / media domains.

Rendered by the server as ``{"error": {"code", "message"}}`` with ``status``.
"""

from typing import Optional

from .stats import WINDOWS_SEC


class ApiError(ValueError):
    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status


def parse_window(value: Optional[str]) -> Optional[float]:
    """``?window=`` (seconds) -> one of :data:`WINDOWS_SEC`, or None for the default."""
    if value is None or value == '':
        return None
    try:
        window = float(value)
    except ValueError:
        window = -1.0
    if window not in WINDOWS_SEC:
        allowed = ', '.join(f'{w:g}' for w in WINDOWS_SEC)
        raise ApiError('invalid_window', f'window must be one of {allowed} seconds')
    return window
