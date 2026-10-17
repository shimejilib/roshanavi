"""Free-space policy for recordings (pure; the free-space function is injectable)."""

import shutil
from dataclasses import dataclass
from typing import Callable, Tuple

MIB = 1024 * 1024


def disk_usage(path: str) -> Tuple[int, int]:
    """(free bytes, total bytes) of the volume holding ``path``."""
    usage = shutil.disk_usage(path)
    return usage.free, usage.total


@dataclass(frozen=True)
class DiskThresholds:
    """Warn below ``warn_mb`` MiB **or** ``warn_pct`` % free; stop below the stop pair."""

    warn_mb: float = 1024.0
    warn_pct: float = 5.0
    stop_mb: float = 256.0
    stop_pct: float = 1.0


class DiskGuard:
    def __init__(self, path: str, thresholds: DiskThresholds = DiskThresholds(),
                 usage: Callable[[str], Tuple[int, int]] = disk_usage):
        self._path = path
        self.thresholds = thresholds
        self._usage = usage

    def check(self) -> dict:
        """``{level: ok|warn|stop, free_bytes, total_bytes, free_pct}``."""
        free, total = self._usage(self._path)
        pct = 100.0 * free / total if total else 0.0
        th = self.thresholds
        if free < th.stop_mb * MIB or pct < th.stop_pct:
            level = 'stop'
        elif free < th.warn_mb * MIB or pct < th.warn_pct:
            level = 'warn'
        else:
            level = 'ok'
        return {'level': level, 'free_bytes': free, 'total_bytes': total,
                'free_pct': round(pct, 2)}
