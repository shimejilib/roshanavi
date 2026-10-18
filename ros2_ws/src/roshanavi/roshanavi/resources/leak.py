"""Memory growth: multi-scale velocity / deceleration test on 1-minute medians (pure).

The detector is fed ``(t, bytes)`` samples per key (a process) with ``t`` in monotonic seconds; it
never reads a clock itself, so tests drive it with any timeline. Design and the measured
detection limits: docs/design/resources.md#メモリリークの見せ方, issue #45.

A leak is *memory that keeps growing without slowing down*; everything else that grows is not:
a one-time step (cache filled once), a plateau (a buffer filling up to its cap), a spike. So the
test looks at the growth **velocity** ``v`` (MB/min) and whether it **slows down**:

1. Every minute the 1 Hz samples are reduced to their median (robust against spikes). The last
   6 hours (360 points per process) are kept. The first ``warmup_sec`` after the process started
   are ignored (start-up allocations).
2. Three time scales are judged at once, 10 min / 1 h / 6 h. Each window is cut into
   ``segments`` (5) equal parts; a part is summarised by the median of its minutes (its *level*),
   so the window gives 4 velocities ``v_i = (level_{i+1} - level_i) / part_minutes``.
3. The *noise* is estimated from the process itself: ``sigma`` is the robust spread (MAD x 1.4826)
   of how much one level differs from the previous level of the same length over the recent
   history. A constant growth shifts every difference by the same amount and does not widen it.
   ``sigma`` has a floor (``sigma_floor_mb``) for processes whose RSS barely moves.
4. **Leak suspicion** (diagnostics panel) on a scale needs all three:
   - most intervals rise: at least ``segments - 2`` of the 4 velocities exceed
     ``z_step x sigma`` over their part;
   - no slowing down: the speed of the second half is at least ``decel_ratio`` (0.5) of the first
     half and positive;
   - the total rise exceeds ``z_total x sigma`` and ``min_total_mb``.
   The verdict must hold ``confirm_evals`` consecutive minutes and is released after
   ``release_evals`` minutes without it (no flicker at the edge).
5. **Watching** (resources tab only): the total rise is real and the latest interval is still rising,
   but the suspicion test fails: a step that just happened or a buffer that is filling and
   levelling off ("増加中・収束しつつある").

Limits (documented, not hidden): RSS is measured, so memory a language's allocator keeps after
``free`` looks like a leak; a leak smaller than the noise needs a long observation; the detector
cannot say which code leaks; with few independent windows the noise estimate itself is uncertain.
"""

from collections import deque
from dataclasses import dataclass
from statistics import median
from typing import Deque, Dict, List, Optional, Sequence, Tuple

MIB = 1024.0 * 1024.0
MAD_TO_SIGMA = 1.4826
HISTORY_MINUTES = 360


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
    warmup_sec: float = 60.0
    bucket_sec: float = 60.0
    min_bucket_samples: int = 10      # a minute with fewer samples (machine stalled) is skipped
    scales_min: Tuple[int, ...] = (10, 60, 360)
    segments: int = 5
    min_fill: float = 0.8             # share of a part's minutes that must be present
    noise_span_factor: int = 3        # noise is estimated over the last 3 windows (all 360 min at most)
    min_noise_points: int = 12        # fewer differences make the noise estimate a coin toss
    ref_block_min: int = 6            # well-measured block length the noise is extrapolated from
    noise_decay: float = 0.25         # 0 = slow wander (no averaging) .. 0.5 = pure jitter
    sigma_floor_mb: float = 0.3
    z_step: float = 2.5
    z_total: float = 4.0
    z_recent: float = 1.5             # "watching": the latest interval still rises by this much
    decel_ratio: float = 0.5
    min_total_mb: float = 3.0
    confirm_evals: int = 2
    release_evals: int = 3


TIER_NONE = 'none'
TIER_WATCH = 'watch'
TIER_LEAK = 'leak'


@dataclass(frozen=True)
class ScaleResult:
    """Judgement of one window. ``rate`` MB/min, ``total`` / ``sigma`` MB."""
    scale_min: int
    tier: str
    rate: float
    total: float
    sigma: float
    rising: int          # intervals above the noise
    slowing: bool


@dataclass(frozen=True)
class LeakState:
    """``slope`` (MB/min over the last 10 min; None while measuring), ``suspect`` = leak warning
    (diagnostics), ``watch`` = growing but levelling off (resources tab only)."""
    slope: Optional[float]
    suspect: bool
    watch: bool
    span_sec: float
    warming_up: bool
    scale_min: Optional[int] = None
    rate: Optional[float] = None         # MB/min on the deciding scale
    duration_sec: Optional[float] = None  # how long it has been growing (lower bound)
    noise_mb: Optional[float] = None

    def to_dict(self) -> Dict[str, object]:
        def r(v: Optional[float], d: int) -> Optional[float]:
            return None if v is None else round(v, d)
        return {'slope_mb_per_min': r(self.slope, 3), 'suspect': self.suspect,
                'watch': self.watch, 'span_sec': round(self.span_sec, 1),
                'warming_up': self.warming_up, 'scale_min': self.scale_min,
                'rate_mb_per_min': r(self.rate, 3), 'duration_sec': r(self.duration_sec, 0),
                'noise_mb': r(self.noise_mb, 3)}


def _mad(values: Sequence[float]) -> float:
    centre = median(values)
    return median([abs(v - centre) for v in values])


def level_noise(values: Sequence[float], part: int, cfg: LeakConfig) -> Optional[float]:
    """Spread (MB) of the change between two neighbouring ``part``-minute levels.

    Slides a pair of adjacent blocks of ``part`` minutes over ``values`` (newest first, stride a
    quarter block), takes the medians of both, and returns 1.4826 x MAD of the differences.
    None when the history is too short for ``cfg.min_noise_points`` differences.
    """
    stride = max(1, part // 4)
    diffs: List[float] = []
    end = len(values) - 1
    while end >= 2 * part - 1:
        newer = median(values[end - part + 1:end + 1])
        older = median(values[end - 2 * part + 1:end - part + 1])
        diffs.append(newer - older)
        end -= stride
    if len(diffs) < cfg.min_noise_points:
        return None
    return max(MAD_TO_SIGMA * _mad(diffs), cfg.sigma_floor_mb)


def scale_noise(values: Sequence[float], part: int, cfg: LeakConfig) -> Optional[float]:
    """Noise (MB) of a level change at ``part``-minute resolution, on the safe side.

    The direct estimate at ``part`` is statistically weak for the long scales (a 6 h window holds
    only a few independent 72-minute levels), and it comes out too small by chance. So it is
    combined with the estimate at a short reference block (``ref_block_min``, well measured) scaled
    down to ``part`` by ``(ref / part) ** noise_decay``: fully random jitter would average out as
    ``part ** -0.5``, slow wander does not average out at all; ``noise_decay`` (0.25) sits in
    between, leaning to the safe side. The larger of the two is used.
    """
    ref = min(part, cfg.ref_block_min)
    reference = level_noise(values, ref, cfg)
    if reference is None:
        return None
    scaled = reference * (ref / part) ** cfg.noise_decay
    direct = level_noise(values, part, cfg) if part != ref else None
    return max(scaled, direct or 0.0)


def _levels(window: Sequence[Tuple[int, float]], first_idx: int, part: int,
            cfg: LeakConfig) -> Optional[List[float]]:
    buckets: List[List[float]] = [[] for _ in range(cfg.segments)]
    for idx, value in window:
        buckets[min(cfg.segments - 1, (idx - first_idx) // part)].append(value)
    need = max(1, int(part * cfg.min_fill))
    if any(len(b) < need for b in buckets):
        return None
    return [median(b) for b in buckets]


def assess_scale(history: Sequence[Tuple[int, float]], cur: int, scale_min: int,
                 cfg: LeakConfig = LeakConfig()) -> Optional[ScaleResult]:
    """Judge the last ``scale_min`` minutes of ``history`` ``[(minute index, MB), ...]``.

    None while the history does not yet cover the window or is too short to estimate the noise.
    """
    part = scale_min // cfg.segments
    first_idx = cur - scale_min + 1
    window = [(i, v) for i, v in history if i >= first_idx]
    levels = _levels(window, first_idx, part, cfg)
    if levels is None:
        return None
    span = [v for i, v in history if i >= cur - cfg.noise_span_factor * scale_min + 1]
    sigma = scale_noise(span, part, cfg)
    if sigma is None:
        return None
    steps = [b - a for a, b in zip(levels, levels[1:])]
    total = levels[-1] - levels[0]
    half = cfg.segments // 2
    early = (levels[half] - levels[0]) / (half * part)
    late = (levels[-1] - levels[half]) / ((cfg.segments - 1 - half) * part)
    rising = sum(1 for d in steps if d > cfg.z_step * sigma)
    slowing = not (late > 0.0 and late >= cfg.decel_ratio * early)
    real_total = total > max(cfg.z_total * sigma, cfg.min_total_mb)
    rate = total / ((cfg.segments - 1) * part)
    if real_total and not slowing and rising >= len(steps) - 1:
        tier = TIER_LEAK
    elif real_total and steps[-1] > cfg.z_recent * sigma:
        tier = TIER_WATCH
    else:
        tier = TIER_NONE
    return ScaleResult(scale_min, tier, rate, total, sigma, rising, slowing)


class _Series:
    """Minute medians of one key plus the confirm / release state of the verdict."""

    def __init__(self, first_seen: float):
        self.first_seen = first_seen
        self.origin: Optional[float] = None      # time of the first kept sample
        self.bucket_idx = 0
        self.bucket: List[float] = []
        self.minutes: Deque[Tuple[int, float]] = deque(maxlen=HISTORY_MINUTES)
        self.hits = 0                            # consecutive minutes with a leak verdict
        self.misses = 0                          # consecutive minutes without one (while suspect)
        self.suspect = False
        self.hit_since: Optional[float] = None
        self.results: List[ScaleResult] = []
        self.state = LeakState(None, False, False, 0.0, True)

    def push(self, t: float, mb: float, cfg: LeakConfig) -> bool:
        """Add a sample; True when a minute was completed (time to re-judge)."""
        if self.origin is None:
            self.origin = t
        idx = int((t - self.origin) // cfg.bucket_sec)
        done = False
        if idx > self.bucket_idx:
            if len(self.bucket) >= cfg.min_bucket_samples:
                self.minutes.append((self.bucket_idx, median(self.bucket)))
                done = True
            self.bucket, self.bucket_idx = [], idx
        self.bucket.append(mb)
        return done

    def judge(self, t: float, cfg: LeakConfig) -> None:
        if not self.minutes:
            return
        cur = self.minutes[-1][0]
        history = list(self.minutes)
        results = [r for r in (assess_scale(history, cur, n, cfg) for n in cfg.scales_min) if r]
        self.results = results
        if any(r.tier == TIER_LEAK for r in results):
            self.hits += 1
            self.misses = 0
            if self.hit_since is None:
                self.hit_since = t
            if self.hits >= cfg.confirm_evals:
                self.suspect = True
        else:
            self.hits = 0
            if self.suspect:
                self.misses += 1
                if self.misses >= cfg.release_evals:
                    self.suspect, self.misses = False, 0
            if not self.suspect:
                self.hit_since = None

    def snapshot(self, t: float) -> LeakState:
        results = self.results
        span = 0.0 if self.origin is None else max(0.0, t - self.origin)
        short = min(results, key=lambda r: r.scale_min) if results else None
        slope = short.rate if short else None
        leak = [r for r in results if r.tier == TIER_LEAK]
        watch = [r for r in results if r.tier == TIER_WATCH]
        if self.suspect:
            best = max(leak, key=lambda r: r.scale_min) if leak else max(
                results, key=lambda r: r.rate)
            since = t if self.hit_since is None else self.hit_since
            return LeakState(slope, True, False, span, False, best.scale_min, best.rate,
                             best.scale_min * 60.0 + (t - since), best.sigma)
        if watch and not leak:
            best = max(watch, key=lambda r: r.scale_min)
            return LeakState(slope, False, True, span, False, best.scale_min, best.rate, None,
                             best.sigma)
        return LeakState(slope, False, False, span, False, None, None, None,
                         short.sigma if short else None)


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
            series.state = LeakState(None, False, False, 0.0, True)
            return series.state
        if series.push(t, float(value) / MIB, cfg):
            series.judge(t, cfg)
        series.state = series.snapshot(t)
        return series.state

    def state(self, key: object) -> Optional[LeakState]:
        series = self._series.get(key)
        return series.state if series else None

    def retain(self, keys: object) -> None:
        """Forget every key not in ``keys`` (processes that exited)."""
        live = set(keys)  # type: ignore[arg-type]
        for key in [k for k in self._series if k not in live]:
            del self._series[key]
