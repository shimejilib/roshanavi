"""Selectable averaging windows (1 / 5 / 10 s) and immediate hz 0 for stopped topics."""

import pytest

from roshanavi.api_errors import ApiError, parse_window
from roshanavi.stats import STALE_MIN_SEC, Sample, TopicStats, expected_period, is_silent


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now


def feed(stats, clock, rate_hz, seconds):
    for _ in range(int(rate_hz * seconds)):
        stats.record(100)
        clock.now += 1.0 / rate_hz


def make():
    mono = FakeClock()
    return TopicStats(window_sec=5.0, clock=mono, wall_clock=FakeClock(1.7e9)), mono


def test_each_window_averages_only_its_own_span():
    stats, mono = make()
    feed(stats, mono, 2.0, 8.0)    # 2 Hz for 8 s, then
    feed(stats, mono, 10.0, 1.0)   # 10 Hz for the last second
    one, five, ten = (stats.snapshot(w) for w in (1.0, 5.0, 10.0))
    assert one['window_sec'] == 1.0 and five['window_sec'] == 5.0 and ten['window_sec'] == 10.0
    assert one['hz'] == pytest.approx(10.0, rel=0.15)
    assert 2.0 < five['hz'] < one['hz']
    assert ten['hz'] < five['hz']
    assert stats.snapshot()['window_sec'] == 5.0  # default window


def test_ten_second_window_keeps_samples_beyond_default():
    stats, mono = make()
    feed(stats, mono, 1.0, 9.0)
    assert stats.snapshot(10.0)['hz'] == pytest.approx(1.0)
    assert stats.snapshot(10.0)['total_count'] == 9


def test_stopped_fast_topic_reads_zero_after_one_second():
    stats, mono = make()
    feed(stats, mono, 10.0, 2.0)
    mono.now += 0.5  # 0.6 s since the last message: still within max(3 x 0.1 s, 1 s)
    assert stats.snapshot()['hz'] == pytest.approx(10.0) and not stats.snapshot()['stale']
    mono.now += 0.6
    snap = stats.snapshot()
    assert snap['stale'] and snap['hz'] == 0.0 and snap['bytes_per_sec'] == 0.0
    assert snap['avg_size'] == 100  # sizes keep their last values


def test_slow_topic_uses_three_periods():
    stats, mono = make()
    feed(stats, mono, 1.0, 5.0)  # 1 Hz -> silent after 3 s
    mono.now += 1.5
    assert not stats.snapshot()['stale']
    mono.now += 1.0
    assert stats.snapshot()['stale'] and stats.snapshot()['hz'] == 0.0


def test_history_records_zero_once_stopped():
    stats, mono = make()
    feed(stats, mono, 10.0, 1.0)
    mono.now += 2.0
    stats.tick()
    assert stats.snapshot()['history'][-1] == 0.0


def test_silence_helpers():
    samples = [Sample(0.0, 1), Sample(0.5, 1), Sample(1.0, 1)]
    assert expected_period(samples) == pytest.approx(0.5)
    assert expected_period(samples[:1]) is None
    assert not is_silent(samples, 2.4) and is_silent(samples, 2.6)
    assert is_silent(samples[:1], STALE_MIN_SEC + 0.01)
    assert not is_silent([], 100.0)


def test_parse_window():
    assert parse_window(None) is None and parse_window('') is None
    assert parse_window('1') == 1.0 and parse_window('10') == 10.0
    for bad in ('2', 'abc', '-1', 'nan'):
        with pytest.raises(ApiError) as info:
            parse_window(bad)
        assert info.value.code == 'invalid_window'


def test_rest_and_ws_window(client):
    assert client.get('/api/traffic?window=1').status_code == 200
    bad = client.get('/api/traffic?window=3')
    assert bad.status_code == 400 and bad.json()['error']['code'] == 'invalid_window'
    with client.websocket_connect('ws://localhost/ws/live?window=10') as ws:
        frame = ws.receive_json()
        assert 'server_time' in frame
        assert all(e['window_sec'] == 10.0 for e in frame['traffic'])
    with client.websocket_connect('ws://localhost/ws/live?window=7') as ws:
        assert ws.receive_json()['error']['code'] == 'invalid_window'


def test_slow_topic_falls_back_to_the_longest_window():
    stats, mono = make()
    feed(stats, mono, 0.5, 8.0)  # 4 messages, 2 s apart: alive but slower than 1 s
    mono.now -= 1.0              # 1 s after the last message (not stale yet)
    one = stats.snapshot(1.0)
    assert not one['stale']
    assert one['rate_note'] == 'extended' and one['rate_window_sec'] == 10.0
    assert one['hz'] == pytest.approx(0.5)
    five = stats.snapshot(5.0)
    assert five['rate_note'] is None and five['rate_window_sec'] == 5.0


def test_single_message_cannot_be_measured():
    stats, mono = make()
    stats.record(10)
    mono.now += 0.5
    snap = stats.snapshot(1.0)
    assert snap['rate_note'] == 'too_few' and snap['hz'] == 0.0 and not snap['stale']
