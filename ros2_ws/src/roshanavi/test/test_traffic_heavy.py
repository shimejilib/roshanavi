"""Heavy-topic opt-in: TrafficMonitor driven by a fake runtime (no ROS graph)."""

from roshanavi.graph import Endpoint, RawGraph
from roshanavi.traffic import TrafficMonitor

QOS = {'reliability': 'reliable'}
IMAGE = 'sensor_msgs/msg/Image'
STRING = 'std_msgs/msg/String'


class FakeRuntime:
    def __init__(self):
        self.subs = {}

    def create_subscription(self, msg_type, topic, callback, qos, raw=False, group=None):
        self.subs[topic] = callback
        return topic

    def destroy_subscription(self, sub):
        self.subs.pop(sub, None)


def graph():
    return RawGraph(
        topics={'/cam': [IMAGE], '/chatter': [STRING], '/scan': ['sensor_msgs/msg/LaserScan'],
                '/cloud': ['sensor_msgs/msg/PointCloud2']},
        publishers={t: [Endpoint('/pub', QOS)] for t in ('/cam', '/chatter', '/scan', '/cloud')},
        subscribers={})


def entries(mon):
    return {e['topic']: e for e in mon.snapshot()}


def test_heavy_types_not_monitored_by_default():
    rt, mon = FakeRuntime(), TrafficMonitor(FakeRuntime())
    mon = TrafficMonitor(rt)
    mon.sync(graph())
    e = entries(mon)
    assert set(rt.subs) == {'/chatter', '/scan'}  # LaserScan is not heavy
    assert (e['/cam']['status'], e['/cam']['monitored']) == ('not_monitored', False)
    assert e['/cloud']['status'] == 'not_monitored'
    assert (e['/chatter']['status'], e['/chatter']['monitored']) == ('ok', True)
    assert e['/cam']['type'] == IMAGE and e['/cam']['hz'] == 0.0 and e['/cam']['dropped'] is None


def test_monitor_heavy_flag_monitors_everything():
    rt = FakeRuntime()
    mon = TrafficMonitor(rt, monitor_heavy=True)
    mon.sync(graph())
    assert set(rt.subs) == {'/cam', '/chatter', '/scan', '/cloud'}
    assert all(e['status'] == 'ok' and e['monitored'] for e in mon.snapshot())


def test_toggle_on_then_off_at_runtime():
    rt = FakeRuntime()
    mon = TrafficMonitor(rt)
    mon.sync(graph())
    mon.set_monitored('/cam', True)
    assert entries(mon)['/cam']['monitored'] is True  # reported immediately
    mon.sync(graph())
    assert '/cam' in rt.subs and entries(mon)['/cam']['status'] == 'ok'
    mon.set_monitored('/cam', False)
    mon.sync(graph())
    assert '/cam' not in rt.subs
    assert entries(mon)['/cam']['status'] == 'not_monitored'


def test_any_topic_can_be_disabled_and_override_beats_flag():
    rt = FakeRuntime()
    mon = TrafficMonitor(rt, monitor_heavy=True)
    mon.sync(graph())
    mon.set_monitored('/chatter', False)
    mon.set_monitored('/cam', False)
    mon.sync(graph())
    assert set(rt.subs) == {'/scan', '/cloud'}
    assert entries(mon)['/chatter']['status'] == 'not_monitored'
    mon.set_monitored('/chatter', True)
    mon.sync(graph())
    assert '/chatter' in rt.subs


def test_unmonitored_topic_removed_when_vanished():
    rt = FakeRuntime()
    mon = TrafficMonitor(rt)
    mon.sync(graph())
    mon.sync(RawGraph())
    assert mon.snapshot() == [] and rt.subs == {}


def test_callback_accepts_message_info():
    rt = FakeRuntime()
    mon = TrafficMonitor(rt)
    mon.sync(graph())
    rt.subs['/chatter'](b'abc', {'source_timestamp': 5, 'received_timestamp': 6,
                                 'publication_sequence_number': 1})
    assert entries(mon)['/chatter']['total_count'] == 1


def test_default_collapsed_topics_include_lifecycle_transition_events():
    from roshanavi.traffic_select import TopicSelector
    selector = TopicSelector()
    for topic in ('/rosout', '/parameter_events', '/events/write_split',
                  '/lc/transition_event', '/ns/lc/transition_event'):
        assert selector.collapsed(topic), topic
    for topic in ('/transition_event', '/lc/transition_events', '/chatter'):
        assert not selector.collapsed(topic), topic
