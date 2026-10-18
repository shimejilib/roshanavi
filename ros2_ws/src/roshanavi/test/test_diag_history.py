"""Time-dependent diagnostics: subscriber_lost / publisher_lost / mine_no_input (pure, driven
with an explicit clock)."""

from roshanavi.diag_history import GraphHistory
from roshanavi.graph import Endpoint, RawGraph, build_snapshot

QOS = {'reliability': 'reliable', 'durability': 'volatile'}


def snap(nodes, edges, roles=None):
    """``nodes``: ids; ``edges``: (node, topic, dir); ``roles``: node id -> role."""
    topics = sorted({t for _, t, _ in edges})
    return {'nodes': [{'id': n, 'role': (roles or {}).get(n, 'other')} for n in nodes],
            'topics': [{'name': t, 'types': ['T']} for t in topics],
            'edges': [{'node': n, 'topic': t, 'dir': d, 'qos': QOS} for n, t, d in edges]}


def run(history, timeline):
    """Feed ``[(t, snapshot), ...]``; return the diagnostics of the last step."""
    out = []
    for t, s in timeline:
        out = history.update(t, s)
    return out


def codes(diags):
    return sorted((d['code'], d['topic']) for d in diags)


TALKER = [('/talker', '/chatter', 'pub')]
LISTENER = [('/listener', '/chatter', 'sub')]


def both():
    return snap(['/talker', '/listener'], TALKER + LISTENER)


def talker_only():
    return snap(['/talker'], TALKER)


def listener_only():
    return snap(['/listener'], LISTENER)


# ---- subscriber_lost / publisher_lost --------------------------------------------------------

def test_healthy_graph_has_no_timed_diagnostics():
    assert run(GraphHistory(), [(t, both()) for t in range(0, 30)]) == []


def test_subscriber_lost_after_the_listener_disappears():
    h = GraphHistory()
    run(h, [(t, both()) for t in range(0, 10)])
    diags = run(h, [(t, talker_only()) for t in range(10, 20)])
    assert codes(diags) == [('subscriber_lost', '/chatter')]
    lost = diags[0]
    assert lost['severity'] == 'warning'
    assert lost['nodes'] == ['/talker'] and lost['detail'] == {'lost': ['/listener']}


def test_a_listener_restarting_within_the_debounce_does_not_warn():
    h = GraphHistory()
    run(h, [(t, both()) for t in range(0, 10)])
    assert run(h, [(10, talker_only()), (11, talker_only())]) == []  # 2 s gone
    assert run(h, [(12, both())]) == []


def test_subscriber_lost_clears_when_the_listener_returns():
    h = GraphHistory()
    run(h, [(t, both()) for t in range(0, 10)])
    assert run(h, [(t, talker_only()) for t in range(10, 20)])
    assert run(h, [(20, both())]) == []


def test_subscriber_lost_expires_after_the_window():
    h = GraphHistory(window_sec=300)
    run(h, [(0, both())])
    assert codes(run(h, [(100, talker_only())])) == [('subscriber_lost', '/chatter')]
    assert codes(run(h, [(299, talker_only())])) == [('subscriber_lost', '/chatter')]
    assert run(h, [(301, talker_only())]) == []


def test_never_subscribed_topic_is_not_subscriber_lost():
    assert run(GraphHistory(), [(t, talker_only()) for t in range(0, 60)]) == []


def test_publisher_lost_when_the_talker_disappears():
    h = GraphHistory()
    run(h, [(t, both()) for t in range(0, 10)])
    diags = run(h, [(t, listener_only()) for t in range(10, 20)])
    assert codes(diags) == [('publisher_lost', '/chatter')]
    assert diags[0]['nodes'] == ['/listener'] and diags[0]['detail'] == {'lost': ['/talker']}


def test_topic_vanishing_entirely_is_not_reported():
    h = GraphHistory()
    run(h, [(t, both()) for t in range(0, 10)])
    assert run(h, [(t, snap([], [])) for t in range(10, 30)]) == []


def test_roshanavi_and_cli_subscribers_do_not_count_as_users():
    watched = snap(['/talker', '/roshanavi', '/_ros2cli_77'],
                   TALKER + [('/roshanavi', '/chatter', 'sub'), ('/_ros2cli_77', '/chatter', 'sub')])
    h = GraphHistory()
    run(h, [(t, watched) for t in range(0, 10)])
    # nobody real ever listened: nothing was lost when the viewer / `ros2 topic echo` stops
    assert run(h, [(t, talker_only()) for t in range(10, 30)]) == []


def test_hidden_topics_are_ignored():
    tx = [('/lc', '/lc/transition_event', 'pub'), ('/cli', '/lc/transition_event', 'sub')]
    h = GraphHistory()
    run(h, [(0, snap(['/lc', '/cli'], tx))])
    assert run(h, [(t, snap(['/lc'], tx[:1])) for t in range(10, 30)]) == []


# ---- mine_no_input ---------------------------------------------------------------------------

MINE = {'/detector': 'mine'}


def mine_listening(extra_pub=False):
    edges = [('/detector', '/camera', 'sub')]
    nodes = ['/detector']
    if extra_pub:
        edges.append(('/cam', '/camera', 'pub'))
        nodes.append('/cam')
    return snap(nodes, edges, MINE)


def test_mine_no_input_after_grace():
    h = GraphHistory()
    assert run(h, [(t, mine_listening()) for t in (0, 1, 2)]) == []  # < 3 s: starting up
    diags = run(h, [(3, mine_listening())])
    assert codes(diags) == [('mine_no_input', '/camera')]
    assert diags[0]['nodes'] == ['/detector'] and diags[0]['detail'] == {'node': '/detector'}


def test_mine_no_input_waits_after_the_node_appeared_not_after_roshanavi_started():
    h = GraphHistory()
    run(h, [(t, snap([], [])) for t in range(0, 100)])
    late = mine_listening()
    assert run(h, [(100, late), (102, late)]) == []
    assert codes(run(h, [(103, late)])) == [('mine_no_input', '/camera')]


def test_mine_no_input_clears_when_a_publisher_appears():
    h = GraphHistory()
    run(h, [(t, mine_listening()) for t in range(0, 10)])
    assert run(h, [(10, mine_listening(extra_pub=True))]) == []


def test_other_roles_do_not_get_mine_no_input():
    other = snap(['/detector'], [('/detector', '/camera', 'sub')], {'/detector': 'dependency'})
    assert run(GraphHistory(), [(t, other) for t in range(0, 10)]) == []


def test_publisher_lost_is_replaced_by_the_more_specific_mine_no_input():
    h = GraphHistory()
    run(h, [(t, mine_listening(extra_pub=True)) for t in range(0, 10)])
    diags = run(h, [(t, mine_listening()) for t in range(10, 20)])
    assert codes(diags) == [('mine_no_input', '/camera')]


def test_mine_no_input_ignores_hidden_topics_and_cli_publishers_do_not_feed_it():
    # a transient `ros2 topic pub` (hidden node) is no real source
    s = snap(['/detector', '/_ros2cli_5'],
             [('/detector', '/camera', 'sub'), ('/_ros2cli_5', '/camera', 'pub'),
              ('/detector', '/_internal', 'sub')], MINE)
    assert codes(run(GraphHistory(), [(t, s) for t in range(0, 10)])) == [
        ('mine_no_input', '/camera')]


# ---- wired through build_snapshot ------------------------------------------------------------

def raw(with_listener):
    nodes = [('talker', '/')] + ([('listener', '/')] if with_listener else [])
    subs = [Endpoint('/listener', QOS)] if with_listener else []
    return RawGraph(nodes=nodes, topics={'/chatter': ['std_msgs/msg/String']},
                    publishers={'/chatter': [Endpoint('/talker', QOS)]},
                    subscribers={'/chatter': subs})


def test_build_snapshot_merges_timed_diagnostics_in_severity_order():
    h = GraphHistory()
    build_snapshot(raw(True), history=h, now=0.0)
    quiet = build_snapshot(raw(False), history=h, now=1.0)
    assert [d['code'] for d in quiet['diagnostics']] == ['no_subscriber']  # < debounce
    loud = build_snapshot(raw(False), history=h, now=10.0)
    assert [(d['code'], d['severity']) for d in loud['diagnostics']] == [
        ('subscriber_lost', 'warning'), ('no_subscriber', 'info')]
    assert build_snapshot(raw(False), now=10.0)['diagnostics'][0]['code'] == 'no_subscriber'


def test_quiet_topics_never_get_lost_or_mine_warnings():
    # a class node's action topic: a button once published, now nobody does (publisher_lost would
    # fire), and the class node itself is `mine` (mine_no_input would fire)
    pressed = snap(['/acc', '/btn'], [('/acc', '/acc/reset', 'sub'), ('/btn', '/acc/reset', 'pub')],
                   roles={'/acc': 'mine'})
    idle = snap(['/acc'], [('/acc', '/acc/reset', 'sub')], roles={'/acc': 'mine'})
    h = GraphHistory()
    quiet = ['/acc/reset']
    for t in range(0, 5):
        h.update(t, pressed, quiet)
    out = []
    for t in range(5, 30):
        out = h.update(t, idle, quiet)
    assert out == []
    # without the quiet list the same timeline warns (the control)
    h = GraphHistory()
    for t in range(0, 5):
        h.update(t, pressed)
    for t in range(5, 30):
        out = h.update(t, idle)
    assert codes(out) == [('mine_no_input', '/acc/reset')]
