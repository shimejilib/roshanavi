"""Thread-safe ring buffer of log lines with monotonically increasing sequence numbers."""

import threading
import time
from collections import deque
from typing import Any, Deque, Dict, List, Tuple

DEFAULT_MAX_LINES = 5000
MAX_LINE_CHARS = 4000


class LogBuffer:
    """Keeps the last ``max_lines`` lines; readers poll with :meth:`since`."""

    def __init__(self, max_lines: int = DEFAULT_MAX_LINES):
        self._lines: Deque[Dict[str, Any]] = deque(maxlen=max_lines)
        self._lock = threading.Lock()
        self._next_seq = 1

    def append(self, stream: str, text: str) -> None:
        text = text.rstrip('\r\n')
        if len(text) > MAX_LINE_CHARS:
            text = text[:MAX_LINE_CHARS] + ' …'
        with self._lock:
            self._lines.append({'seq': self._next_seq, 'ts': time.time(), 'stream': stream,
                                'text': text})
            self._next_seq += 1

    def since(self, seq: int = 0,
              limit: int = DEFAULT_MAX_LINES) -> Tuple[List[Dict[str, Any]], int]:
        """Lines with ``seq > seq`` (oldest first, at most ``limit``) and the next cursor."""
        with self._lock:
            lines = [dict(line) for line in self._lines if line['seq'] > seq]
            next_seq = self._next_seq - 1
        if len(lines) > limit:
            lines = lines[:limit]
            next_seq = lines[-1]['seq']
        return lines, next_seq

    def tail(self, n: int) -> List[str]:
        with self._lock:
            return [line['text'] for line in list(self._lines)[-n:]]

    def clear(self) -> None:
        with self._lock:
            self._lines.clear()
