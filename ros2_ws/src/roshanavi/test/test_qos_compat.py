import pytest

from roshanavi.qos_compat import incompatibilities, incompatible_pairs

RELIABLE = {'reliability': 'reliable', 'durability': 'volatile'}
BEST_EFFORT = {'reliability': 'best_effort', 'durability': 'volatile'}
LATCHED = {'reliability': 'reliable', 'durability': 'transient_local'}


@pytest.mark.parametrize('pub,sub,policies', [
    (RELIABLE, RELIABLE, []),
    (RELIABLE, BEST_EFFORT, []),  # reliable pub serves best-effort sub
    (BEST_EFFORT, RELIABLE, ['reliability']),
    (LATCHED, RELIABLE, []),  # transient_local pub serves volatile sub
    (RELIABLE, LATCHED, ['durability']),
    (BEST_EFFORT, LATCHED, ['reliability', 'durability']),
    ({}, {}, []),  # unknown policies never warn
])
def test_reliability_and_durability(pub, sub, policies):
    assert [r['policy'] for r in incompatibilities(pub, sub)] == policies


@pytest.mark.parametrize('pub_deadline,sub_deadline,bad', [
    (None, None, False), (100.0, None, False), (50.0, 100.0, False),
    (200.0, 100.0, True), (None, 100.0, True)])
def test_deadline(pub_deadline, sub_deadline, bad):
    reasons = incompatibilities({'deadline_ms': pub_deadline}, {'deadline_ms': sub_deadline})
    assert bool(reasons) is bad
    if bad:
        assert reasons[0] == {'policy': 'deadline', 'pub': pub_deadline, 'sub': sub_deadline}


def test_liveliness_kind_and_lease():
    auto, manual = {'liveliness': 'automatic'}, {'liveliness': 'manual_by_topic'}
    assert [r['policy'] for r in incompatibilities(auto, manual)] == ['liveliness']
    assert incompatibilities(manual, auto) == []
    assert incompatibilities({'liveliness': 'system_default'}, manual) == []
    reasons = incompatibilities({'lease_ms': 2000.0}, {'lease_ms': 1000.0})
    assert [r['policy'] for r in reasons] == ['liveliness_lease']


def test_incompatible_pairs_per_topic():
    edges = [
        {'node': '/cam', 'topic': '/img', 'dir': 'pub', 'qos': BEST_EFFORT},
        {'node': '/viewer', 'topic': '/img', 'dir': 'sub', 'qos': RELIABLE},
        {'node': '/logger', 'topic': '/img', 'dir': 'sub', 'qos': BEST_EFFORT},
        {'node': '/other', 'topic': '/x', 'dir': 'sub', 'qos': RELIABLE},
    ]
    pairs = incompatible_pairs(edges)
    assert pairs == [{'topic': '/img', 'publisher': '/cam', 'subscriber': '/viewer',
                      'reasons': [{'policy': 'reliability', 'pub': 'best_effort',
                                   'sub': 'reliable'}]}]
