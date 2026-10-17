import pytest

from roshanavi.traffic import HISTORY_LEN, Sample, TopicStats, compute_stats


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


def make(window=5.0):
    mono, wall = FakeClock(), FakeClock(1.7e9)
    return TopicStats(window_sec=window, clock=mono, wall_clock=wall), mono, wall


def test_empty_stats():
    stats, _, _ = make()
    snap = stats.snapshot()
    assert snap['hz'] == 0.0 and snap['total_count'] == 0 and snap['last_seen'] is None


def test_steady_rate():
    stats, mono, wall = make()
    for _ in range(21):  # 10 Hz for 2 s
        stats.record(100)
        mono.now += 0.1
        wall.now += 0.1
    snap = stats.snapshot()
    assert snap['hz'] == pytest.approx(10.0)
    assert snap['avg_size'] == 100
    assert snap['bytes_per_sec'] == pytest.approx(1000.0)
    assert snap['jitter_ms'] == pytest.approx(0.0, abs=1e-6)
    assert snap['total_count'] == 21
    assert snap['last_seen'] == pytest.approx(1.7e9 + 2.0)


def test_jitter_is_interval_stddev():
    result = compute_stats([Sample(0.0, 10), Sample(0.1, 10), Sample(0.3, 30)])
    # intervals 0.1, 0.2 -> mean 0.15, population std 0.05 s
    assert result['jitter_ms'] == pytest.approx(50.0)
    assert result['jitter_recv_ms'] == pytest.approx(50.0)
    assert result['hz'] == pytest.approx(2 / 0.3)
    assert result['avg_size'] == pytest.approx(50 / 3)


def test_window_expiry_drops_to_zero():
    stats, mono, _ = make(window=5.0)
    for _ in range(5):
        stats.record(10)
        mono.now += 1.0
    assert stats.snapshot()['hz'] == pytest.approx(1.0)
    mono.now += 10.0
    snap = stats.snapshot()
    assert snap['hz'] == 0.0
    assert snap['total_count'] == 5  # lifetime total is kept


def test_history_ticks_are_bounded():
    stats, mono, _ = make()
    for _ in range(HISTORY_LEN + 10):
        stats.record(1)
        mono.now += 0.5
        stats.tick()
    history = stats.snapshot()['history']
    assert len(history) == HISTORY_LEN
    assert history[-1] == pytest.approx(2.0)


def test_sample_cap_bounds_memory():
    mono = FakeClock()
    stats = TopicStats(window_sec=5.0, clock=mono, wall_clock=FakeClock(), max_samples=10)
    for _ in range(100):
        stats.record(1)
        mono.now += 0.001
    snap = stats.snapshot()
    assert snap['total_count'] == 100
    assert snap['hz'] == pytest.approx(1000.0)


def test_recent_count_is_last_second_only():
    stats, mono, _ = make()
    for _ in range(5):  # 5 messages at t=0..0.4
        stats.record(10)
        mono.now += 0.1
    mono.now += 1.0  # 1.5 s after the first message
    stats.record(10)
    snap = stats.snapshot()
    assert snap['recent_count'] == 1
    assert snap['total_count'] == 6
