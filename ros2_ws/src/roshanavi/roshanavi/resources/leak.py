"""Memory growth: least-squares slope over a sliding window and the leak verdict (pure).

The detector is fed ``(t, bytes)`` samples per key (a process) with ``t`` in monotonic
seconds; it never reads a clock itself, so tests drive it with any timeline.

Rules (docs/design/resources.md#メモリリークの見せ方):
- samples during the first ``warmup_sec`` after a process was first seen are ignored
  (start-up allocations are not a leak);
- the slope is fitted over the last ``window_sec`` once the samples span ``min_span_sec``;
- a key is a *suspect* when the slope stayed above ``threshold_mb_per_min`` for
  ``sustain_sec`` without interruption.
"""

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, Optional, Sequence, Tuple

MIB = 1024.0 * 1024.0
WINDOW_SEC = 300.0
WARMUP_SEC = 60.0
MIN_SPAN_SEC = 120.0
SUSTAIN_SEC = 60.0
THRESHOLD_MB_PER_MIN = 1.0
REBASE_EVERY = 600


def slope_per_sec(samples: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Least-squares slope (value units per second); None with < 2 distinct times."""
    n = len(samples)
    if n < 2:
        return None
    mean_t = sum(t for t, _ in samples) / n
    mean_v = sum(v for _, v in samples) / n
    var_t = sum((t - mean_t) ** 2 for t, _ in samples)
    if var_t <= 0.0:
        return None
    cov = sum((t - mean_t) * (v - mean_v) for t, v in samples)
    return cov / var_t


def mb_per_min(samples: Sequence[Tuple[float, float]]) -> Optional[float]:
    """Slope of byte samples in MiB per minute."""
    slope = slope_per_sec(samples)
    return None if slope is None else slope * 60.0 / MIB


@dataclass(frozen=True)
class LeakConfig:
    window_sec: float = WINDOW_SEC
    warmup_sec: float = WARMUP_SEC
    min_span_sec: float = MIN_SPAN_SEC
    sustain_sec: float = SUSTAIN_SEC
    threshold_mb_per_min: float = THRESHOLD_MB_PER_MIN


@dataclass(frozen=True)
class LeakState:
    """``slope`` in MiB/min (None while warming up / too short); ``suspect`` = warn."""
    slope: Optional[float]
    suspect: bool
    above_since: Optional[float]
    span_sec: float
    warming_up: bool

    def to_dict(self) -> Dict[str, object]:
        return {'slope_mb_per_min': None if self.slope is None else round(self.slope, 3),
                'suspect': self.suspect, 'span_sec': round(self.span_sec, 1),
                'warming_up': self.warming_up}


class _Series:
    """Samples of one key with running sums, so the slope costs O(1) per sample (the
    sampler fits every monitored process every second over up to 300 points)."""

    def __init__(self, first_seen: float):
        self.first_seen = first_seen
        self.samples: Deque[Tuple[float, float]] = deque()
        self.above_since: Optional[float] = None
        self.state = LeakState(None, False, None, 0.0, True)
        self._origin = first_seen
        self._pushes = 0
        self._n = 0
        self._st = self._sv = self._stt = self._stv = 0.0

    def _acc(self, t: float, v: float, sign: float) -> None:
        x = t - self._origin  # small numbers keep the sums precise
        self._n += int(sign)
        self._st += sign * x
        self._sv += sign * v
        self._stt += sign * x * x
        self._stv += sign * x * v

    def push(self, t: float, v: float) -> None:
        self.samples.append((t, v))
        self._acc(t, v, 1.0)
        self._pushes += 1
        if self._pushes >= REBASE_EVERY:  # drop the rounding error of many add / subtract
            self._rebase()

    def _rebase(self) -> None:
        self._pushes = 0
        self._origin = self.samples[0][0] if self.samples else self._origin
        self._n = 0
        self._st = self._sv = self._stt = self._stv = 0.0
        for t, v in self.samples:
            self._acc(t, v, 1.0)

    def drop_before(self, t_min: float) -> None:
        while self.samples and self.samples[0][0] < t_min:
            t, v = self.samples.popleft()
            self._acc(t, v, -1.0)

    def slope_per_sec(self) -> Optional[float]:
        n = self._n
        if n < 2:
            return None
        var = self._stt - self._st * self._st / n
        if var <= 1e-9:
            return None
        return (self._stv - self._st * self._sv / n) / var


class LeakDetector:
    def __init__(self, config: LeakConfig = LeakConfig()):
        self.config = config
        self._series: Dict[object, _Series] = {}

    def observe(self, key: object, t: float, value: float,
                first_seen: Optional[float] = None) -> LeakState:
        cfg = self.config
        series = self._series.get(key)
        if series is None:
            series = self._series[key] = _Series(t if first_seen is None else first_seen)
        if t - series.first_seen < cfg.warmup_sec:
            series.state = LeakState(None, False, None, 0.0, True)
            return series.state
        series.push(t, float(value) / MIB)
        series.drop_before(t - cfg.window_sec)
        samples = series.samples
        span = samples[-1][0] - samples[0][0] if samples else 0.0
        per_sec = series.slope_per_sec() if span >= cfg.min_span_sec else None
        slope = None if per_sec is None else per_sec * 60.0
        if slope is not None and slope > cfg.threshold_mb_per_min:
            if series.above_since is None:
                series.above_since = t
        else:
            series.above_since = None
        suspect = series.above_since is not None and t - series.above_since >= cfg.sustain_sec
        series.state = LeakState(slope, suspect, series.above_since, span, False)
        return series.state

    def state(self, key: object) -> Optional[LeakState]:
        series = self._series.get(key)
        return series.state if series else None

    def retain(self, keys: object) -> None:
        """Forget every key not in ``keys`` (processes that exited)."""
        live = set(keys)  # type: ignore[arg-type]
        for key in [k for k in self._series if k not in live]:
            del self._series[key]
