"""Transform pipeline policies: drop ratio, throttle, delay and multi-input join (no rclpy)."""

import random
import threading
import time

from conftest import wait_for
from roshanavi.launcher.schema import DelaySpec
from roshanavi.transform.pipeline import DelayQueue, Gate, Joiner


def test_drop_ratio_statistics():
    gate = Gate(drop_ratio=0.3, rng=random.Random(42))
    dropped = sum(gate.drop() for _ in range(10_000))
    assert 2_800 <= dropped <= 3_200
    assert not any(Gate(drop_ratio=0).drop() for _ in range(100))
    assert all(Gate(drop_ratio=1).drop() for _ in range(100))


def test_throttle_limits_rate_with_fake_clock():
    gate = Gate(throttle_hz=10)
    # 100 Hz input for 2 s -> about 10 Hz out.
    passed = [t / 100 for t in range(200) if not gate.throttle(t / 100)]
    assert 19 <= len(passed) <= 21
    gaps = [b - a for a, b in zip(passed, passed[1:])]
    assert min(gaps) >= 0.095 - 1e-9


def test_throttle_tolerates_jitter_at_exact_rate():
    gate = Gate(throttle_hz=10)
    times = [i * 0.1 + (0.002 if i % 2 else -0.002) for i in range(1, 51)]
    assert sum(not gate.throttle(t) for t in times) == 50


def test_delay_fixed_and_random_range():
    assert Gate(delay=DelaySpec(min_ms=250)).delay_sec() == 0.25
    gate = Gate(delay=DelaySpec(min_ms=100, max_ms=200), rng=random.Random(1))
    values = [gate.delay_sec() for _ in range(1000)]
    assert 0.1 <= min(values) and max(values) <= 0.2
    assert 0.14 <= sum(values) / len(values) <= 0.16
    assert Gate().delay_sec() == 0.0


def test_joiner_waits_for_all_inputs_then_publishes_on_any():
    join = Joiner(['a', 'b'])
    assert join.update('a', 1) == ('waiting', None)
    assert join.update('b', 2) == ('ready', {'a': 1, 'b': 2})
    assert join.update('a', 3) == ('ready', {'a': 3, 'b': 2})


def test_joiner_trigger_topic():
    join = Joiner(['a', 'b'], trigger='b')
    join.update('b', 1)
    assert join.update('a', 2) == ('stored', None)
    assert join.update('a', 3) == ('stored', None)
    assert join.update('b', 4) == ('ready', {'a': 3, 'b': 4})


def test_delay_queue_sends_in_due_order():
    sent, lock = [], threading.Lock()

    def send(item):
        with lock:
            sent.append((item, time.monotonic()))
    queue = DelayQueue(send, on_overflow=lambda: None)
    try:
        start = time.monotonic()
        queue.put('late', 0.3)
        queue.put('early', 0.1)
        queue.put('now', 0.0)
        wait_for(lambda: len(sent) == 3, timeout=5)
        assert [item for item, _ in sent] == ['now', 'early', 'late']
        # Generous upper bound: the host may be heavily loaded.
        assert sent[2][1] - start >= 0.3 - 0.01
    finally:
        queue.close()


def test_delay_queue_overflow_and_close():
    overflow = []
    queue = DelayQueue(lambda item: None, on_overflow=lambda: overflow.append(1), max_pending=3)
    try:
        for _ in range(5):
            queue.put('x', 60)
        assert queue.pending() == 3 and len(overflow) == 2
    finally:
        queue.close()
    queue.put('after close', 0)  # ignored, no error
    assert queue.pending() == 0


def test_delay_queue_survives_send_errors():
    sent = []

    def send(item):
        if item == 'boom':
            raise RuntimeError('publish failed')
        sent.append(item)
    queue = DelayQueue(send, on_overflow=lambda: None)
    try:
        queue.put('boom', 0)
        queue.put('ok', 0.01)
        wait_for(lambda: sent == ['ok'], timeout=5)
    finally:
        queue.close()
