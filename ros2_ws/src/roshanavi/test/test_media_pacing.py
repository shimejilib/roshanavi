"""Pacer, sleep_until/run_paced and Prefetcher: pure logic with injectable clock and sleep."""

import threading
import time

import pytest

from roshanavi.media.pacing import Pacer, run_paced, sleep_until
from roshanavi.media.prefetch import END, Prefetcher, capacity_for, prebuffer_items

PERIOD = 0.1


class FakeTime:
    """Clock + sleep; ``oversleep`` lists extra seconds added to successive sleeps."""

    def __init__(self, oversleep=()):
        self.now = 100.0
        self._extra = list(oversleep)
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds + (self._extra.pop(0) if self._extra else 0.0)
        return False


def run(policy, count=10, oversleep=(), jitter=0.0):
    """Send ``count`` items; returns (send times relative to start, pacer)."""
    ft = FakeTime(oversleep)
    pacer = Pacer(PERIOD, jitter_sec=jitter, clock=ft.clock, late_policy=policy)
    items = iter(range(count))
    sent = []
    start = ft.now
    run_paced(pacer, lambda: next(items, END), lambda i: sent.append((i, ft.now - start)) or True,
              ft.sleep, END, clock=ft.clock)
    return sent, pacer


def gaps(sent):
    times = [t for _, t in sent]
    return [round(b - a, 6) for a, b in zip(times, times[1:])]


# ---- schedule ---------------------------------------------------------------

def test_on_time_items_are_spaced_by_the_period_and_never_late():
    sent, pacer = run('shift')
    assert [i for i, _ in sent] == list(range(10))
    assert gaps(sent) == pytest.approx([PERIOD] * 9)
    assert pacer.late_events == 0 and pacer.max_lateness_ms == 0.0


def test_small_oversleep_is_absorbed_by_absolute_deadlines():
    sent, pacer = run('shift', oversleep=[0.0, 0.03, 0.0, 0.0])
    assert [t for _, t in sent][-1] == pytest.approx(9 * PERIOD)   # no drift
    assert pacer.late_events == 0                                    # 30 ms < one period
    assert pacer.max_lateness_ms == pytest.approx(30.0)


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError):
        Pacer(PERIOD, late_policy='burst')


def test_jitter_stays_within_bounds_of_the_nominal_deadline():
    ft = FakeTime()
    pacer = Pacer(PERIOD, jitter_sec=0.02, clock=ft.clock)
    start = ft.now
    for k in range(50):
        deadline = pacer.next_deadline()
        assert deadline == pacer.next_deadline()                    # stable until arrive()
        assert abs(deadline - (start + k * PERIOD)) <= 0.02 + 1e-9
        ft.now = max(ft.now, deadline)
        pacer.arrive(ft.now)


# ---- late policies ----------------------------------------------------------

LATE = [0.0, 0.0, 0.45, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]   # the 2nd sleep (item 2) wakes 450 ms late


def test_shift_reanchors_after_a_late_wake_without_a_burst():
    sent, pacer = run('shift', oversleep=LATE)
    g = gaps(sent)
    assert max(g) == pytest.approx(PERIOD + 0.45)      # the stall itself is visible once
    assert min(g) == pytest.approx(PERIOD)             # but no burst afterwards
    assert pacer.late_events == 1 and pacer.late_skipped == 0
    assert pacer.max_lateness_ms == pytest.approx(450.0)
    assert len(sent) == 10


def test_catch_up_bursts_back_to_the_original_timeline():
    sent, pacer = run('catch_up', oversleep=LATE)
    g = gaps(sent)
    assert min(g) == pytest.approx(0.0, abs=1e-6)      # back-to-back sends
    assert [t for _, t in sent][-1] == pytest.approx(9 * PERIOD)   # absolute deadlines kept
    assert pacer.late_events == 4                       # 450, 350, 250, 150 ms late (> 100 ms)
    assert len(sent) == 10


def test_drop_skips_late_items_and_keeps_the_timeline():
    sent, pacer = run('drop', oversleep=LATE)
    assert pacer.late_skipped == pacer.late_events == 4
    assert len(sent) == 10 - 4
    sent_times = [t for _, t in sent]
    assert all(t >= 0 for t in sent_times) and sent_times[-1] == pytest.approx(9 * PERIOD)
    assert min(gaps(sent)) >= 0.0


def test_lateness_equal_to_one_period_is_not_a_late_event():
    _, pacer = run('shift', oversleep=[0.1])            # exactly one period late
    assert pacer.late_events == 0


# ---- sleep_until / run_paced ------------------------------------------------

def test_sleep_until_retries_early_wakeups_and_reports_interruption():
    ft = FakeTime()
    calls = []

    def early(seconds):
        calls.append(seconds)
        ft.now += seconds / 2
        return False

    assert sleep_until(ft.now + 1.0, ft.clock, early) is False
    assert len(calls) > 2 and ft.now >= 101.0 - 1e-9
    assert sleep_until(ft.now + 1.0, ft.clock, lambda s: True) is True
    assert sleep_until(ft.now - 1.0, ft.clock, lambda s: pytest.fail('no sleep')) is False


def test_run_paced_limit_counts_taken_items_and_stops_when_send_says_so():
    ft = FakeTime()
    pacer = Pacer(PERIOD, clock=ft.clock)
    sent = []
    run_paced(pacer, iter(range(100)).__next__, lambda i: sent.append(i) or True,
              ft.sleep, END, clock=ft.clock, limit=3)
    assert sent == [0, 1, 2]
    sent.clear()
    run_paced(Pacer(PERIOD, clock=ft.clock), iter(range(100)).__next__,
              lambda i: sent.append(i) or i < 1, ft.sleep, END, clock=ft.clock)
    assert sent == [0, 1]


# ---- prebuffer / prefetch ---------------------------------------------------

def test_prebuffer_items_and_capacity():
    assert prebuffer_items(300, 0.064) == 5            # 320 ms of 64 ms chunks
    assert prebuffer_items(300, 1.0) == 1              # slow slideshow: just the first frame
    assert prebuffer_items(0, 0.033) == 1
    assert capacity_for(5) == 10 and capacity_for(1) == 5


class GatedSource:
    """Yields ``n`` items immediately, then blocks on ``gate`` before each further item."""

    period = 0.05

    def __init__(self, free, total=100):
        self.free, self.total = free, total
        self.gate = threading.Event()
        self.produced = 0
        self.closed = False

    def next(self):
        if self.produced >= self.total or self.closed:
            return None
        if self.produced >= self.free:
            self.gate.wait(timeout=10)
            if self.closed:
                return None
        self.produced += 1
        return _Item(self.produced)

    def close(self):
        self.closed = True
        self.gate.set()


class _Item:
    def __init__(self, n, size=10):
        self.n, self.data = n, b'x' * size


def test_wait_ready_blocks_until_the_prebuffer_is_filled():
    src = GatedSource(free=2)
    buf = Prefetcher(src, capacity=10)
    buf.start()
    try:
        assert buf.wait_ready(5, timeout=0.2) is False       # only 2 items available
        assert buf.depth == 2
        src.gate.set()
        assert buf.wait_ready(5, timeout=5) is True
        assert buf.depth >= 5
    finally:
        src.close()
        buf.close()


def test_pacer_side_never_waits_on_a_stalled_reader_while_items_are_buffered():
    src = GatedSource(free=6)
    buf = Prefetcher(src, capacity=10)
    buf.start()
    try:
        assert buf.wait_ready(6, timeout=5)
        started = time.monotonic()
        got = [buf.get().n for _ in range(6)]                 # reader is now blocked on the gate
        assert got == [1, 2, 3, 4, 5, 6]
        assert time.monotonic() - started < 0.2
    finally:
        src.close()
        buf.close()


def test_reader_stops_at_capacity_and_resumes_when_the_pacer_dequeues():
    src = GatedSource(free=1000)
    buf = Prefetcher(src, capacity=4)
    buf.start()
    try:
        assert buf.wait_ready(99, timeout=5)                  # returns at "full"
        time.sleep(0.05)
        assert buf.depth == 4 and src.produced <= 5
        buf.get()
        deadline = time.monotonic() + 5
        while buf.depth < 4 and time.monotonic() < deadline:
            time.sleep(0.005)
        assert buf.depth == 4
    finally:
        src.close()
        buf.close()


def test_byte_budget_limits_the_buffer_but_always_admits_one_item():
    class Big(GatedSource):
        def next(self):
            item = super().next()
            return None if item is None else _Item(item.n, size=100)

    src = Big(free=1000)
    buf = Prefetcher(src, capacity=50, max_bytes=250)
    buf.start()
    try:
        assert buf.wait_ready(50, timeout=5)
        time.sleep(0.05)
        assert buf.depth == 2                                  # 2 x 100 B fits, a third does not
    finally:
        src.close()
        buf.close()


def test_end_of_media_and_reader_error_reach_the_pacer_after_buffered_items():
    class Ends(GatedSource):
        def next(self):
            if self.produced == 3:
                raise RuntimeError('decode failed')
            return super().next()

    src = Ends(free=1000)
    buf = Prefetcher(src, capacity=10)
    buf.start()
    assert [buf.get().n for _ in range(3)] == [1, 2, 3]
    with pytest.raises(RuntimeError, match='decode failed'):
        buf.get()
    assert buf.get() is END
    buf.close()

    done = GatedSource(free=1000, total=2)
    buf = Prefetcher(done, capacity=10)
    buf.start()
    assert [buf.get().n for _ in range(2)] == [1, 2] and buf.get() is END
    buf.close()


def test_close_wakes_a_blocked_get_and_joins_the_reader():
    src = GatedSource(free=0)
    buf = Prefetcher(src, capacity=4)
    buf.start()
    result = []
    waiter = threading.Thread(target=lambda: result.append(buf.get()))
    waiter.start()
    time.sleep(0.05)
    src.close()
    buf.close()
    waiter.join(timeout=2)
    assert result == [END] and not waiter.is_alive()
