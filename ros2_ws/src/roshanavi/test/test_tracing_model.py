"""Trace model (pure): handle chains -> node / topic, windowed counts, callback times."""

from roshanavi.tracing import config
from roshanavi.tracing import model as m

NS = m.NS
PID = 100


def init_cpp(pid=PID, node=('listener', '/'), topic='/chatter'):
    """Init events of one rclcpp node with one subscription (handles are fake pointers)."""
    return [
        (m.K_NODE, 1, pid, 'listener', 11, node[0], node[1]),
        (m.K_RCL_SUB, 2, pid, 'listener', 21, 11, 31, topic),
        (m.K_CPP_SUB, 3, pid, 'listener', 21, 41),
        (m.K_CB_REGISTER, 4, pid, 'listener', 51, 'Listener::on_message'),
        (m.K_CB_ADDED, 5, pid, 'listener', 41, 51),
        (m.K_RCL_PUB, 6, pid, 'listener', 61, 11, 71, '/rosout'),
    ]


def messages(pid, start_s, rate_hz, seconds, cb_ms):
    """take + callback start/end per message; ``cb_ms`` long callbacks on thread 7."""
    events, period = [], int(NS / rate_hz)
    t = int(start_s * NS)
    for _ in range(int(rate_hz * seconds)):
        events += [(m.K_TAKE, t, pid, 31), (m.K_CB_START, t + 1, pid, 7, 51, False),
                   (m.K_CB_END, t + 1 + int(cb_ms * 1e6), pid, 7, 51)]
        t += period
    return events


def sub_of(snap, node='/listener'):
    return next(s for s in snap['subscriptions'] if s['node'] == node)


def test_rclcpp_chain_maps_takes_and_callbacks_to_node_and_topic():
    model = m.TraceModel()
    model.feed(init_cpp())
    model.feed(messages(PID, 1.0, 10, 10, cb_ms=2.0))  # t = 1.0 .. 10.9 s
    snap = model.snapshot(int(10.95 * NS), active_since=0)  # window (5.95, 10.95]
    sub = sub_of(snap)
    assert sub['topic'] == '/chatter' and sub['lang'] == 'cpp'
    assert sub['symbol'] == 'Listener::on_message'
    w5 = sub['windows']['5']
    assert w5['hz_recv'] == 10.0 and w5['hz_processed'] == 10.0
    assert w5['cb_ms'] == {'avg': 2.0, 'p95': 2.0, 'max': 2.0}
    assert snap['nodes'] == [{'node': '/listener', 'pid': PID, 'lang': 'cpp',
                              'procname': 'listener'}]


def test_rates_are_interval_based_and_unmeasurable_until_two_events():
    model = m.TraceModel()
    model.feed(init_cpp())
    model.feed(messages(PID, 0.05, 10, 2, cb_ms=1.0))
    snap = model.snapshot(2 * NS, active_since=0)
    assert sub_of(snap)['windows']['5']['hz_recv'] == 10.0  # (n-1)/span, not n/elapsed
    one = m.TraceModel()
    one.feed(init_cpp())
    one.feed([(m.K_TAKE, int(1.9 * NS), PID, 31)])
    assert sub_of(one.snapshot(2 * NS, active_since=0))['windows']['1']['hz_recv'] is None


def test_callback_times_p95_and_max():
    model = m.TraceModel()
    model.feed(init_cpp())
    durations = [1.0] * 19 + [50.0]
    t = NS
    for d in durations:
        model.feed([(m.K_TAKE, t, PID, 31), (m.K_CB_START, t, PID, 3, 51, False),
                    (m.K_CB_END, t + int(d * 1e6), PID, 3, 51)])
        t += NS // 10
    cb = sub_of(model.snapshot(4 * NS, active_since=0))['windows']['5']['cb_ms']
    assert cb['max'] == 50.0 and cb['p95'] == 1.0 and cb['avg'] == round(69 / 20, 3)


def test_rclpy_subscription_has_received_only():
    model = m.TraceModel()
    model.feed([(m.K_NODE, 1, 200, 'listener', 11, 'py_listener', '/'),
                (m.K_RCL_SUB, 2, 200, 'listener', 21, 11, 31, '/chatter')])
    model.feed([(m.K_TAKE, int(i * NS / 5) + NS, 200, 31) for i in range(25)])
    sub = sub_of(model.snapshot(int(5.9 * NS), active_since=0), '/py_listener')
    assert sub['lang'] == 'py'
    assert sub['windows']['5'] == {'hz_recv': 5.0, 'hz_processed': None, 'cb_ms': None}


def test_events_of_processes_without_init_are_reported_as_unknown():
    model = m.TraceModel()
    model.feed([(m.K_TAKE, NS, 300, 999), (m.K_PUBLISH, NS, 300, 998)])
    snap = model.snapshot(2 * NS, active_since=0)
    assert snap['unknown_pids'] == [300] and snap['subscriptions'] == []


def test_same_handle_in_two_processes_does_not_mix():
    model = m.TraceModel()
    model.feed(init_cpp(pid=1, node=('a', '/'), topic='/x'))
    model.feed(init_cpp(pid=2, node=('b', '/ns'), topic='/y'))
    model.feed(messages(1, 1.0, 4, 4, 1.0) + messages(2, 1.0, 2, 4, 1.0))
    snap = model.snapshot(5 * NS, active_since=0)
    assert sub_of(snap, '/a')['windows']['5']['hz_recv'] == 4.0
    assert sub_of(snap, '/ns/b')['topic'] == '/y'
    assert sub_of(snap, '/ns/b')['windows']['5']['hz_recv'] == 2.0


def test_publish_counts_and_forgetting_dead_processes():
    model = m.TraceModel()
    model.feed(init_cpp())
    model.feed([(m.K_PUBLISH, NS + i * NS // 2, PID, 71) for i in range(8)])
    pub = model.snapshot(5 * NS, active_since=0)['publishers'][0]
    assert pub['node'] == '/listener' and pub['topic'] == '/rosout'
    assert pub['windows']['5']['hz'] == 2.0
    model.forget_processes(alive=set())
    assert model.snapshot(5 * NS, None) == {'nodes': [], 'subscriptions': [],
                                            'publishers': [], 'unknown_pids': []}


def test_old_samples_are_trimmed_and_clear_rates_keeps_the_registry():
    model = m.TraceModel()
    model.feed(init_cpp())
    model.feed(messages(PID, 1.0, 10, 2, 1.0))
    later = model.snapshot(30 * NS, active_since=0)
    assert sub_of(later)['windows']['10']['hz_recv'] == 0.0
    model.clear_rates()
    snap = model.snapshot(31 * NS, active_since=None)
    assert sub_of(snap)['windows']['1']['hz_recv'] is None  # not measuring


def test_unpaired_callback_end_is_ignored():
    model = m.TraceModel()
    model.feed(init_cpp())
    model.feed([(m.K_CB_END, NS, PID, 7, 51), (m.K_CB_START, NS, PID, 7, 999, False),
                (m.K_CB_END, 2 * NS, PID, 7, 999)])
    assert sub_of(model.snapshot(3 * NS, 0))['windows']['5']['hz_processed'] == 0.0


def test_rt_buffer_is_shrunk_to_fit_dev_shm():
    assert config.rt_channel_size(8, None).per_cpu == 4 * config.MIB
    size = config.rt_channel_size(24, 64 * config.MIB)  # Docker's default /dev/shm
    assert size.per_cpu * 24 + config.INIT_SUBBUF * 2 * 24 <= 32 * config.MIB
    assert size.subbuf_bytes >= config.PAGE and size.subbuf_count == 4
    tiny = config.rt_channel_size(1, None, wanted_per_cpu=8 * config.KIB)
    assert (tiny.subbuf_bytes, tiny.subbuf_count) == (config.PAGE, 2)


def test_rt_buffer_too_small_raises():
    try:
        config.rt_channel_size(64, 1 * config.MIB)
    except config.ShmTooSmall:
        return
    raise AssertionError('expected ShmTooSmall')


def test_filters_and_session_names():
    assert config.exclude_filter([]) is None
    assert config.take_filter([5, 3, 5]) == 'taken == 1 && $ctx.vpid != 3 && $ctx.vpid != 5'
    assert config.stale_owner_pid('roshanavi-123-ab12cd34-rt') == 123
    assert config.stale_owner_pid('my-session') is None
    assert config.possible_cpus('/nonexistent') >= 1
