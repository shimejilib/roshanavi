"""Memory-leak detector (resources/leak.py) on synthetic RSS curves.

Pure: no ROS, no real processes, no clock. ``synth`` makes 1 Hz samples of ``base + trend + noise``
where the noise is the sum of per-sample jitter and a slow wander (an AR(1) process stepping every
minute, correlation about 5 minutes), because real RSS wanders; white noise alone would make the
long scales look better than they are.

The ``LIMITS`` table below is what docs/design/resources.md and the README quote: it is the
measured limit of this detector on these curves, and ``test_detection_limits`` keeps it honest.
"""

import math
import random
from typing import Callable, Dict, Iterator, Optional, Tuple

import pytest

from roshanavi.resources.leak import (MIB, LeakConfig, LeakDetector, assess_scale, level_noise,
                                      mb_per_min, scale_noise, slope_per_sec)

# (wander sigma, jitter sigma) in MB. quiet: a steady native node; typical: Python/C++ node with
# message buffers; noisy: a process that allocates and frees a lot (+-10 MB swings).
NOISE: Dict[str, Tuple[float, float]] = {'quiet': (0.3, 0.2), 'typical': (2.0, 1.0),
                                         'noisy': (6.0, 3.0)}
WANDER_PHI = 0.8   # per-minute correlation of the wander
HOUR = 3600


def synth(seconds: int, noise: str = 'typical', rate: float = 0.0, base: float = 200.0,
          seed: int = 0, shape: Optional[Callable[[int], float]] = None
          ) -> Iterator[Tuple[float, float]]:
    """Yield ``(t, rss_bytes)`` at 1 Hz. ``rate`` MB/min linear trend, or ``shape(t)`` MB."""
    wander_sigma, jitter_sigma = NOISE[noise]
    rng = random.Random(seed)
    wander = 0.0
    for t in range(seconds):
        if t % 60 == 0:
            wander = (WANDER_PHI * wander
                      + math.sqrt(1 - WANDER_PHI ** 2) * wander_sigma * rng.gauss(0, 1))
        trend = shape(t) if shape else rate * t / 60.0
        yield float(t), (base + trend + wander + jitter_sigma * rng.gauss(0, 1)) * MIB


class Outcome:
    def __init__(self) -> None:
        self.first_suspect_min: Optional[int] = None
        self.first_suspect_scale: Optional[int] = None
        self.first_rate: Optional[float] = None
        self.first_duration: Optional[float] = None
        self.suspect_minutes = 0
        self.watch_minutes = 0
        self.last = None


def run(samples: Iterator[Tuple[float, float]], cfg: LeakConfig = LeakConfig(),
        stop_at_suspect: bool = False) -> Outcome:
    det = LeakDetector(cfg)
    out = Outcome()
    for t, value in samples:
        st = det.observe('p', t, value, 0.0)
        out.last = st
        if int(t) % 60 == 0:
            out.suspect_minutes += st.suspect
            out.watch_minutes += st.watch
        if st.suspect and out.first_suspect_min is None:
            out.first_suspect_min = round(t / 60)
            out.first_suspect_scale, out.first_rate = st.scale_min, st.rate
            out.first_duration = st.duration_sec
            if stop_at_suspect:
                break
    return out


# ---- the leak patterns ---------------------------------------------------------------

def test_one_time_step_is_not_a_leak():
    step = lambda t: 30.0 if t > HOUR else 0.0  # noqa: E731 - a cache filled once, 30 MB
    for seed in range(3):
        out = run(synth(4 * HOUR, 'typical', shape=step, seed=seed))
        assert out.first_suspect_min is None
        assert out.watch_minutes > 0  # the jump is visible on the resources tab for a while
        assert not out.last.watch  # ... and gone again hours later


def test_early_step_right_after_start_is_not_a_leak():
    step = lambda t: 30.0 if t > 180 else 0.0  # noqa: E731
    assert run(synth(3 * HOUR, 'typical', shape=step, seed=1)).first_suspect_min is None


@pytest.mark.parametrize('name,shape', [
    ('buffer fills linearly in 5 min, then stays', lambda t: min(20.0, 20.0 * max(0, t - 60) / 300)),
    ('exponential fill, tau = 3 min', lambda t: 60.0 * (1 - math.exp(-t / 180.0))),
    ('exponential fill, tau = 10 min', lambda t: 60.0 * (1 - math.exp(-t / 600.0))),
])
def test_plateau_buffer_filling_is_not_a_leak(name, shape):
    for noise in ('quiet', 'typical'):
        for seed in range(3):
            out = run(synth(4 * HOUR, noise, shape=shape, seed=seed))
            assert out.first_suspect_min is None, (name, noise, seed)


def test_plateau_is_watched_not_accused():
    shape = lambda t: 40.0 * (1 - math.exp(-t / 400.0))  # noqa: E731 - quiet process, fill 40 MB
    out = run(synth(2 * HOUR, 'quiet', shape=shape, seed=0))
    assert out.first_suspect_min is None


def test_constant_3_mb_per_min_is_a_leak_within_20_minutes():
    for noise in ('quiet', 'typical'):
        out = run(synth(HOUR, noise, rate=3.0, seed=2), stop_at_suspect=True)
        assert out.first_suspect_min is not None and out.first_suspect_min <= 20, noise
        assert out.first_suspect_scale == 10
        assert out.first_rate == pytest.approx(3.0, rel=0.25)
        assert out.first_duration >= 10 * 60  # growing for at least the window that saw it


def test_slow_0_1_mb_per_min_needs_the_6_hour_scale():
    # 0.1 MB/min is far below the +-2 MB wander of a typical process on the 10 min and 1 h scales
    for seed in range(4):
        out = run(synth(8 * HOUR, 'typical', rate=0.1, seed=seed))
        assert out.first_suspect_scale == 360, seed
        assert 340 <= out.first_suspect_min <= 420, seed
        assert out.first_rate == pytest.approx(0.1, rel=0.4)


def test_quiet_process_shows_the_same_slow_leak_already_on_the_1_hour_scale():
    out = run(synth(4 * HOUR, 'quiet', rate=0.1, seed=0), stop_at_suspect=True)
    assert out.first_suspect_scale == 60 and out.first_suspect_min <= 70


def test_accelerating_leak_is_detected_and_keeps_being_reported():
    accel = lambda t: 0.01 * (t / 60.0) ** 2  # noqa: E731 - growth speed 0.02 MB/min per minute
    out = run(synth(3 * HOUR, 'quiet', shape=accel, seed=0))
    assert out.first_suspect_min is not None and out.first_suspect_min <= 60
    assert out.last.suspect


def test_spikes_are_not_a_leak():
    one = lambda t: 60.0 if HOUR < t < HOUR + 120 else 0.0  # noqa: E731 - 60 MB for 2 min
    repeated = lambda t: 60.0 if t % 900 < 20 else 0.0  # noqa: E731 - 60 MB for 20 s, every 15 min
    for noise in ('quiet', 'typical'):
        for shape in (one, repeated):
            for seed in range(2):
                out = run(synth(3 * HOUR, noise, shape=shape, seed=seed))
                assert out.first_suspect_min is None, (noise, seed)


@pytest.mark.parametrize('noise', ['quiet', 'typical', 'noisy'])
def test_noise_only_never_raises_a_suspicion(noise):
    for seed in range(3):
        out = run(synth(12 * HOUR, noise, seed=seed))
        assert out.first_suspect_min is None, (noise, seed)


def test_leak_message_numbers_rate_and_duration_grow_with_time():
    det = LeakDetector()
    first = last = None
    for t, value in synth(2 * HOUR, 'quiet', rate=1.0, seed=3):
        st = det.observe('p', t, value, 0.0)
        if st.suspect:
            first = first or st
            last = st
    assert first is not None and last is not None
    assert last.rate == pytest.approx(1.0, rel=0.25)
    assert last.duration_sec > first.duration_sec


def test_suspicion_goes_away_when_growth_stops():
    stops = lambda t: 3.0 * min(t, 1800) / 60.0  # noqa: E731 - leaks 30 min, then flat
    det = LeakDetector()
    states = [det.observe('p', t, v, 0.0) for t, v in synth(2 * HOUR, 'quiet', shape=stops)]
    assert any(s.suspect for s in states)
    assert not states[-1].suspect


# ---- mechanics --------------------------------------------------------------------------------

def test_slope_of_a_straight_line_and_of_noise_free_constant():
    assert slope_per_sec([(0, 1.0), (1, 3.0), (2, 5.0)]) == pytest.approx(2.0)
    assert slope_per_sec([(0, 7.0), (5, 7.0), (9, 7.0)]) == pytest.approx(0.0)
    assert slope_per_sec([(1, 1.0)]) is None
    assert slope_per_sec([(1, 1.0), (1, 2.0)]) is None


def test_mb_per_min_converts_bytes_per_second():
    samples = [(t, 100 * MIB + t * MIB / 60.0) for t in range(0, 120)]  # +1 MiB per minute
    assert mb_per_min(samples) == pytest.approx(1.0)


def test_warm_up_is_ignored_and_counts_from_process_start():
    det = LeakDetector()
    state = None
    for t in range(59):
        state = det.observe('p', float(t), (100 + 50.0 * t / 60) * MIB, 0.0)
    assert state.warming_up and state.slope is None and not state.suspect
    late = LeakDetector().observe('q', 1000.0, 100 * MIB, first_seen=0.0)  # started long ago
    assert not late.warming_up


def test_measuring_until_the_first_window_is_full():
    det = LeakDetector()
    states = [det.observe('p', t, v, 0.0) for t, v in synth(10 * 60, 'quiet', rate=1.0)]
    assert states[-1].slope is None and not states[-1].suspect
    assert states[-1].span_sec > 500


def test_skips_minutes_with_too_few_samples_and_survives_gaps():
    det = LeakDetector()
    # the sampler stalled for 20 minutes in the middle: no crash, no bogus verdict
    for t in list(range(0, 1200)) + list(range(2400, 4800)):
        st = det.observe('p', float(t), 100 * MIB, 0.0)
    assert not st.suspect


def test_retain_forgets_exited_processes():
    det = LeakDetector()
    det.observe('a', 0.0, 1.0)
    det.observe('b', 0.0, 1.0)
    det.retain(['b'])
    assert det.state('a') is None and det.state('b') is not None


def test_processes_are_judged_independently():
    det = LeakDetector()
    leak = synth(HOUR, 'quiet', rate=3.0, seed=1)
    flat = synth(HOUR, 'quiet', seed=2)
    last = {}
    for (t, a), (_, b) in zip(leak, flat):
        last['leaky'] = det.observe('leaky', t, a, 0.0)
        last['flat'] = det.observe('flat', t, b, 0.0)
    assert last['leaky'].suspect and not last['flat'].suspect


def test_state_dict_shape():
    st = run(synth(HOUR, 'quiet', rate=3.0), stop_at_suspect=True).last
    d = st.to_dict()
    assert d['suspect'] is True and d['watch'] is False and d['scale_min'] == 10
    assert set(d) >= {'slope_mb_per_min', 'rate_mb_per_min', 'duration_sec', 'span_sec',
                      'warming_up', 'noise_mb'}


def test_noise_estimate_ignores_a_constant_trend_and_a_step():
    flat = [100.0 + 0.5 * math.sin(i * 1.7) for i in range(200)]
    trend = [v + 0.5 * i for i, v in enumerate(flat)]
    stepped = [v + (30.0 if i > 120 else 0.0) for i, v in enumerate(flat)]
    cfg = LeakConfig()
    base = level_noise(flat, 2, cfg)
    assert base is not None
    assert level_noise(trend, 2, cfg) == pytest.approx(base, rel=0.35)
    assert level_noise(stepped, 2, cfg) == pytest.approx(base, rel=0.35)
    assert level_noise(flat[:5], 2, cfg) is None
    assert scale_noise(flat, 12, cfg) >= base * (2 / 12) ** cfg.noise_decay * 0.6


def test_assess_scale_needs_a_full_window():
    cfg = LeakConfig()
    history = [(i, 100.0 + 3.0 * i) for i in range(8)]
    assert assess_scale(history, 7, 10, cfg) is None
    history = [(i, 100.0 + 3.0 * i) for i in range(30)]
    result = assess_scale(history, 29, 10, cfg)
    assert result is not None and result.tier == 'leak' and result.rate == pytest.approx(3.0)


# ---- measured limits (quoted in the docs) -----------------------------------------------------

# scale (min) -> noise -> (smallest rate MB/min found by every seed, latest detection in minutes).
# "latest" is the slowest of the tested seeds; the first window is full after FIRST_MIN[scale].
FIRST_MIN = {10: 17, 60: 59, 360: 347}
LIMITS: Dict[int, Dict[str, Tuple[float, int]]] = {
    10: {'quiet': (0.5, 17), 'typical': (1.0, 425), 'noisy': (3.0, 425)},
    60: {'quiet': (0.07, 261), 'typical': (0.3, 416), 'noisy': (1.0, 347)},
    360: {'quiet': (0.01, 637), 'typical': (0.05, 381), 'noisy': (0.15, 381)},
}


@pytest.mark.parametrize('scale', [10, 60, 360])
@pytest.mark.parametrize('noise', ['quiet', 'typical', 'noisy'])
def test_detection_limits(scale, noise):
    rate, latest = LIMITS[scale][noise]
    cfg = LeakConfig(scales_min=(scale,))
    found = []
    for seed in range(3):
        out = run(synth(13 * HOUR, noise, rate=rate, seed=seed), cfg, stop_at_suspect=True)
        found.append(out.first_suspect_min)
    assert all(m is not None for m in found), (scale, noise, rate, found)
    assert min(found) >= FIRST_MIN[scale] - 1
    assert max(found) <= latest, (scale, noise, rate, found)


@pytest.mark.parametrize('scale', [10, 60, 360])
@pytest.mark.parametrize('noise', ['quiet', 'typical'])
def test_a_tenth_of_the_limit_is_not_detected(scale, noise):
    rate, _ = LIMITS[scale][noise]
    cfg = LeakConfig(scales_min=(scale,))
    for seed in range(2):
        out = run(synth(8 * HOUR, noise, rate=rate / 10.0, seed=seed), cfg, stop_at_suspect=True)
        assert out.first_suspect_min is None, (scale, noise, seed)
