"""MessageInfo-based statistics: synthetic samples, no ROS needed."""

import pytest

from roshanavi.stats import Sample, TopicStats, compute_stats, sample_from_info

NS = 1_000_000_000


def src_samples(period_ns, count, gid=None, seq0=1, t0=0.0, skip=(), start_ns=10 * NS, lat_ns=0):
    """Samples published every period_ns, skipping the seq offsets in ``skip``."""
    out = []
    for i in range(count):
        if i in skip:
            continue
        src = start_ns + i * period_ns
        out.append(Sample(t0 + i * period_ns / 1e9, 100, src, src + lat_ns, gid, seq0 + i))
    return out


def test_source_hz_and_no_drops():
    r = compute_stats(src_samples(100_000_000, 21))
    assert r['hz_basis'] == 'source'
    assert r['hz'] == pytest.approx(10.0) and r['hz_source'] == pytest.approx(10.0)
    assert r['dropped'] == 0 and r['drop_ratio'] == 0.0


def test_lost_messages_still_count_toward_source_rate():
    # 4 consecutive messages lost: arrivals alone would give a lower rate than published.
    r = compute_stats(src_samples(100_000_000, 21, skip={3, 4, 5, 6}))
    assert r['hz_source'] == pytest.approx(10.0)
    assert r['hz_recv'] < 9.0
    assert r['dropped'] == 4
    assert r['drop_ratio'] == pytest.approx(4 / 21)


def test_multi_publisher_rates_sum_and_gaps_per_publisher():
    a, b = bytes([1]), bytes([2])
    sa = src_samples(100_000_000, 11, gid=a)                      # 10 Hz
    sb = src_samples(50_000_000, 21, gid=b, seq0=500, skip={2})   # 20 Hz, 1 drop
    mixed = sorted(sa + sb, key=lambda s: s.t)
    r = compute_stats(mixed)
    assert r['hz'] == pytest.approx(30.0)
    assert r['dropped'] == 1


def test_unsupported_sequence_numbers_report_none():
    samples = [s._replace(seq=0) for s in src_samples(100_000_000, 10)]
    r = compute_stats(samples)
    assert r['dropped'] is None and r['drop_ratio'] is None
    assert r['hz_basis'] == 'source'


def test_non_monotonic_sequence_reports_none():
    samples = src_samples(100_000_000, 10)
    samples[5] = samples[5]._replace(seq=1)  # publisher restarted / interleaved
    assert compute_stats(samples)['dropped'] is None


def test_interleaved_publishers_without_gid_report_none_drops():
    a = src_samples(100_000_000, 10)
    b = src_samples(100_000_000, 10, start_ns=10 * NS + 50_000_000)
    r = compute_stats(sorted(a + b, key=lambda s: s.t))
    assert r['dropped'] is None
    assert r['hz'] == pytest.approx(20.0, rel=0.1)  # merged stream still gives the sum


def test_falls_back_to_receive_when_no_source_timestamp():
    samples = [Sample(i * 0.1, 10) for i in range(11)]
    r = compute_stats(samples)
    assert r['hz_basis'] == 'receive' and r['hz_source'] is None
    assert r['hz'] == pytest.approx(10.0) == pytest.approx(r['hz_recv'])
    assert r['latency_ms'] is None and r['dropped'] is None


def test_publish_jitter_ignores_receive_jitter():
    samples = []
    for i in range(11):
        src = 10 * NS + i * 100_000_000
        recv_t = i * 0.1 + (0.03 if i % 2 else 0.0)  # noisy arrival
        samples.append(Sample(recv_t, 10, src, src, None, i + 1))
    r = compute_stats(samples)
    assert r['jitter_ms'] == pytest.approx(0.0, abs=1e-6)
    assert r['jitter_recv_ms'] > 10.0


def test_latency_is_mean_receive_minus_source():
    r = compute_stats(src_samples(100_000_000, 5, lat_ns=2_000_000))
    assert r['latency_ms'] == pytest.approx(2.0)


def test_sample_from_info_handles_missing_and_partial_info():
    assert sample_from_info(1.0, 5, None) == Sample(1.0, 5)
    s = sample_from_info(1.0, 5, {'source_timestamp': 7, 'received_timestamp': 9,
                                  'publication_sequence_number': 3})
    assert (s.src_ns, s.recv_ns, s.seq, s.gid) == (7, 9, 3, None)
    assert sample_from_info(1.0, 5, {'source_timestamp': None}).src_ns == 0


def test_sample_from_info_reads_both_gid_forms():
    # rclpy 10 (Lyrical) adds the publisher gid as a dict; older forms are a byte sequence
    lyrical = {'publisher_gid': {'implementation_identifier': 'rmw_fastrtps_cpp',
                                 'data': b'\x01\x02'}}
    assert sample_from_info(1.0, 5, lyrical).gid == b'\x01\x02'
    assert sample_from_info(1.0, 5, {'publisher_gid': [1, 2]}).gid == b'\x01\x02'
    assert sample_from_info(1.0, 5, {'publisher_gid': {'data': b''}}).gid is None


def test_topic_stats_records_info_with_injected_clock():
    now = [100.0]
    stats = TopicStats(clock=lambda: now[0], wall_clock=lambda: 1.7e9)
    for i in range(11):
        info = {'source_timestamp': 10 * NS + i * 100_000_000,
                'received_timestamp': 10 * NS + i * 100_000_000 + 1_000_000,
                'publication_sequence_number': i + 1}
        stats.record(50, info)
        now[0] += 0.1
    snap = stats.snapshot()
    assert snap['hz_basis'] == 'source' and snap['hz'] == pytest.approx(10.0)
    assert snap['dropped'] == 0 and snap['latency_ms'] == pytest.approx(1.0)
