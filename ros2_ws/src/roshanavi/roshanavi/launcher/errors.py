"""Launcher error type (mapped to the API error envelope by server.py)."""


class LauncherError(ValueError):
    """``code`` is a stable machine-readable error code; ``status`` the HTTP status."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.status = status
