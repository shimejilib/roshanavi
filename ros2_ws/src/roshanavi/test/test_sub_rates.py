"""Theoretical per-subscriber rates (pure): QoS-compatible publishers' sum."""

from roshanavi.rates import KnownRate, annotate_traffic
from roshanavi.sub_rates import subscriber_rate, topic_subscribers

REL = {'reliability': 'reliable', 'durability': 'volatile'}
BE = {'reliability': 'best_effort', 'durability': 'volatile'}


def pub(node, qos=REL):
    return {'node': node, 'topic': '/t', 'dir': 'pub', 'qos': qos}


def sub(node, qos=REL):
    return {'node': node, 'topic': '/t', 'dir': 'sub', 'qos': qos}


def test_all_compatible_publishers_give_the_topic_total():
    rate = subscriber_rate(REL, [pub('/a'), pub('/b')], {}, 10.0, 1000.0)
    assert rate == {'hz': 10.0, 'bps': 1000.0, 'basis': 'theoretical', 'delivered': True,
                    'sources': ['/a', '/b']}


def test_partly_compatible_sums_the_compatible_publishers():
    rates = {'/a': {'hz': 4.0, 'bps': 40.0}, '/b': {'hz': 6.0, 'bps': 60.0}}
    rate = subscriber_rate(REL, [pub('/a'), pub('/b', BE)], rates, 10.0, 100.0)
    assert rate['hz'] == 4.0 and rate['bps'] == 40.0 and rate['sources'] == ['/a']
    unknown = subscriber_rate(REL, [pub('/a'), pub('/b', BE)], {'/a': {'hz': None}}, 10.0, 1.0)
    assert unknown['hz'] is None and unknown['basis'] == 'theoretical'


def test_incompatible_subscriber_gets_nothing():
    rate = subscriber_rate(REL, [pub('/a', BE)], {}, 10.0, 100.0)
    assert rate == {'hz': 0.0, 'bps': 0.0, 'basis': 'not_delivered', 'delivered': False,
                    'sources': []}


def test_no_publisher_and_unmonitored_topic():
    assert subscriber_rate(REL, [], {}, 0.0, 0.0)['hz'] == 0.0
    entry = {'topic': '/t', 'monitored': False, 'status': 'not_monitored', 'hz': 0.0,
             'publishers': []}
    subs = topic_subscribers(entry, [pub('/a'), sub('/s')])
    assert subs[0]['hz'] is None and subs[0]['delivered']
    # not measured is not "nothing arrives" (#61): its own basis, never a delivery verdict
    assert subs[0]['basis'] == 'not_monitored'


def test_annotate_traffic_adds_subscribers_and_skips_self():
    entries = [{'topic': '/t', 'monitored': True, 'status': 'ok', 'hz': 5.0,
                'bytes_per_sec': 50.0}]
    edges = [pub('/talker'), sub('/listener'), sub('/listener'), sub('/fast', BE),
             sub('/roshanavi_x')]
    out = annotate_traffic(entries, edges, {})[0]
    assert [s['node'] for s in out['subscribers']] == ['/listener', '/fast']
    assert out['subscribers'][0]['hz'] == 5.0 and out['subscribers'][1]['hz'] == 5.0
    assert out['publishers'] == [{'node': '/talker', 'hz': 5.0, 'bps': 50.0,
                                  'basis': 'measured'}]
    known = annotate_traffic(entries, [pub('dummy:j'), pub('/b', BE), sub('/s')],
                             {'dummy:j': KnownRate(2.0, 20.0)})[0]
    assert known['subscribers'][0]['hz'] == 2.0 and known['subscribers'][0]['sources'] == [
        'dummy:j']
