"""Per-publisher rate split for map edges (pure)."""

import time

from roshanavi.jobs import InjectSpec, Job
from roshanavi.rates import (KnownRate, annotate_traffic, known_rates, publishers_by_topic,
                             split_topic_rates)

DUMMY = 'dummy:abc'


def test_no_publishers():
    assert split_topic_rates(5.0, 100.0, [], {}) == {}


def test_single_publisher_gets_the_measured_total():
    assert split_topic_rates(2.0, 50.0, ['/talker'], {}) == {
        '/talker': {'hz': 2.0, 'bps': 50.0, 'basis': 'measured'}}


def test_dummy_only():
    rates = split_topic_rates(1.0, 40.0, [DUMMY], {DUMMY: KnownRate(1.0, 40.0)})
    assert rates == {DUMMY: {'hz': 1.0, 'bps': 40.0, 'basis': 'exact'}}


def test_one_other_publisher_is_estimated_from_the_remainder():
    rates = split_topic_rates(2.0, 80.0, ['/talker', DUMMY], {DUMMY: KnownRate(1.0, 40.0)})
    assert rates['/talker'] == {'hz': 1.0, 'bps': 40.0, 'basis': 'estimated'}
    assert rates[DUMMY]['basis'] == 'exact'


def test_dummy_faster_than_measured_total_is_clamped():
    rates = split_topic_rates(2.0, 10.0, ['/talker', DUMMY], {DUMMY: KnownRate(3.0, 30.0)})
    assert rates['/talker'] == {'hz': 0.0, 'bps': 0.0, 'basis': 'estimated'}


def test_unknown_dummy_bytes_leave_bandwidth_on_the_topic():
    rates = split_topic_rates(2.0, 80.0, ['/talker', '/d'],
                              {'/d': KnownRate(1.0, None, 'configured')})
    assert rates['/talker'] == {'hz': 1.0, 'bps': None, 'basis': 'estimated'}
    assert rates['/d'] == {'hz': 1.0, 'bps': None, 'basis': 'configured'}


def test_two_other_publishers_have_no_per_edge_number():
    rates = split_topic_rates(3.0, 90.0, ['/a', '/b', DUMMY], {DUMMY: KnownRate(1.0, 30.0)})
    assert rates['/a'] == rates['/b'] == {'hz': None, 'bps': None, 'basis': 'unknown'}
    assert rates[DUMMY]['hz'] == 1.0


def test_unmonitored_total_is_unknown():
    rates = split_topic_rates(None, None, ['/cam', DUMMY], {DUMMY: KnownRate(5.0, None)})
    assert rates['/cam']['basis'] == 'unknown'


def test_annotate_traffic_and_self_publishers_are_ignored():
    edges = [{'node': '/talker', 'topic': '/chatter', 'dir': 'pub'},
             {'node': DUMMY, 'topic': '/chatter', 'dir': 'pub'},
             {'node': '/roshanavi', 'topic': '/chatter', 'dir': 'pub'},
             {'node': '/listener', 'topic': '/chatter', 'dir': 'sub'}]
    assert publishers_by_topic(edges) == {'/chatter': ['/talker', DUMMY]}
    entries = [{'topic': '/chatter', 'hz': 2.0, 'bytes_per_sec': 60.0, 'monitored': True,
                'status': 'ok'}]
    out = annotate_traffic(entries, edges, {DUMMY: KnownRate(1.0, 30.0)})
    assert out[0]['source_count'] == 2
    assert out[0]['publishers'][0] == {'node': '/talker', 'hz': 1.0, 'bps': 30.0,
                                       'basis': 'estimated'}
    assert 'publishers' not in entries[0]  # input is not mutated


def test_known_rates_from_jobs_and_persistent_dummies():
    jobs = [{'id': 'abc', 'state': 'running', 'send_hz': 1.0, 'send_bps': 20.0},
            {'id': 'old', 'state': 'done', 'send_hz': 1.0, 'send_bps': 20.0}]
    nodes = [{'id': '/dummy_cam', 'role': 'dummy', 'target_id': 'cam'},
             {'id': '/talker', 'role': 'mine', 'target_id': 'talker'}]
    targets = [{'id': 'cam', 'status': 'running', 'spec': {'mode': 'periodic', 'rate_hz': 5}},
               {'id': 'talker', 'status': 'running', 'spec': {}}]
    known = known_rates(jobs, nodes, targets)
    assert known == {DUMMY: KnownRate(1.0, 20.0),
                     '/dummy_cam': KnownRate(5.0, None, 'configured')}


def test_job_send_rate_counts_actual_sends():
    job = Job(InjectSpec(mode='periodic'))
    assert job.send_rate() == (0.0, 0.0)
    now = time.monotonic()
    for i in range(5):
        job._sends.append((now - 4 + i, 10))
    hz, bps = job.send_rate(now=now)
    assert hz == 1.0 and bps == 10.0
    assert job.send_rate(now=now + 30) == (0.0, 0.0)  # nothing in the window any more
