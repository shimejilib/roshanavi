"""Traced rates equal the probe's (stats.TopicStats) for the same stream."""

import pytest

from roshanavi.stats import TopicStats
from roshanavi.tracing import model as m

NS = m.NS
PID = 7


def _traced(times_s, now_s, window):
    model = m.TraceModel()
    model.feed([(m.K_NODE, 1, PID, 'p', 11, 'l', '/'), (m.K_RCL_SUB, 2, PID, 'p', 21, 11, 31, '/t')])
    model.feed([(m.K_TAKE, int(t * NS), PID, 31) for t in times_s])
    snap = model.snapshot(int(now_s * NS), active_since=0)
    return snap['subscriptions'][0]['windows'][str(window)]['hz_recv']


def _probe(times_s, now_s, window):
    clock = [0.0]
    stats = TopicStats(window, clock=lambda: clock[0])
    for t in times_s:
        clock[0] = t
        stats.record(1)
    clock[0] = now_s
    snap = stats.snapshot(window)
    return None if snap['rate_note'] == 'too_few' else snap['hz']


@pytest.mark.parametrize('hz', [1, 10, 100])
@pytest.mark.parametrize('window', [1, 5, 10])
@pytest.mark.parametrize('elapsed', [1.5, 2.0, 3.3, 6.0, 15.0])
def test_trace_rate_matches_probe_rate(hz, window, elapsed):
    times = [0.13 + i / hz for i in range(int((elapsed - 0.13) * hz) + 1) if 0.13 + i / hz <= elapsed]
    expected = _probe(times, elapsed, window)
    got = _traced(times, elapsed, window)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected, rel=0.01)
        assert got == pytest.approx(hz, rel=0.01)


def test_one_hz_two_seconds_after_start_is_not_inflated():
    # the old count/elapsed rule gave 1.12 Hz here
    assert _traced([0.1, 1.1, 2.1], 2.2, 5) == pytest.approx(1.0, rel=0.01)


def test_stopped_stream_reads_zero():
    assert _traced([0.0, 1.0, 2.0], 10.0, 5) == 0.0
