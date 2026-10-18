import pytest

from roshanavi.diagnostics import (diagnose, is_hidden_node, is_hidden_topic, levenshtein,
                                   names_similar)

QOS = {'reliability': 'reliable', 'durability': 'volatile'}


def snap(topics, edges):
    return {'nodes': [], 'topics': [{'name': n, 'types': t} for n, t in topics],
            'edges': [{'node': n, 'topic': t, 'dir': d, 'qos': q or QOS}
                      for n, t, d, q in edges]}


def codes(diags):
    return [(d['code'], d['topic']) for d in diags]


def test_levenshtein():
    assert levenshtein('', 'abc') == 3
    assert levenshtein('kitten', 'sitting') == 3
    assert levenshtein('cmd_vel', 'cmdvel') == 1


@pytest.mark.parametrize('a,b,similar', [
    ('/cmd_vel', '/cmdvel', True),
    ('/cmd_vel', '/cmd-vel', True),
    ('/robot/scan', '/robot/scans', True),
    ('/robot/odometry', '/robot/odometyr', True),  # transposition = 2 edits
    ('/a/scan', '/b/scan', False),  # different namespace, identical last segment
    ('/odom', '/imu', False),
    ('/map', '/mat', True),  # short name, one edit
    ('/map', '/cap2', False),  # short name, two edits
    ('/chatter', '/chatter', False),
])
def test_names_similar(a, b, similar):
    assert names_similar(a, b) is similar


def test_hidden_topics():
    assert is_hidden_topic('/rosout') and is_hidden_topic('/parameter_events')
    assert is_hidden_topic('/events/write_split')  # rosbag2's own topic while recording
    assert is_hidden_topic('/nav/_action/status')
    assert not is_hidden_topic('/chatter')


@pytest.mark.parametrize('topic', ['/lc_talker/transition_event', '/ns/lc/transition_event',
                                   '/fibonacci/_action/feedback', '/fibonacci/_action/status'])
def test_lifecycle_events_and_action_internals_are_hidden(topic):
    assert is_hidden_topic(topic)


def test_transition_event_hiding_does_not_catch_lookalikes():
    assert not is_hidden_topic('/transition_event_log')
    assert not is_hidden_topic('/my/transition')


@pytest.mark.parametrize('node,hidden', [
    ('/_ros2cli_daemon_0_1a2b3c', True), ('/_ros2cli_12345', True),
    ('/ns/_ros2cli_9', True), ('/talker', False), ('/ns/my_ros2cli', False),
    ('dummy:abc', False)])
def test_hidden_nodes(node, hidden):
    assert is_hidden_node(node) is hidden


def test_healthy_graph_has_no_diagnostics():
    s = snap([('/chatter', ['std_msgs/msg/String'])],
             [('/talker', '/chatter', 'pub', None), ('/listener', '/chatter', 'sub', None)])
    assert diagnose(s) == []


def test_one_sided_topics_are_info_not_warnings():
    s = snap([('/orphan', ['T']), ('/waiting', ['T']), ('/rosout', ['T'])],
             [('/teleop', '/orphan', 'pub', None), ('/base', '/waiting', 'sub', None),
              ('/teleop', '/rosout', 'pub', None)])
    diags = diagnose(s)
    assert [(d['code'], d['severity'], d['topic']) for d in diags] == [
        ('no_publisher', 'info', '/waiting'), ('no_subscriber', 'info', '/orphan')]
    assert diags[1]['nodes'] == ['/teleop'] and diags[0]['nodes'] == ['/base']


def test_similar_names_between_two_one_sided_topics_is_reported_once():
    s = snap([('/cmd_vel', ['T']), ('/cmdvel', ['T'])],
             [('/teleop', '/cmd_vel', 'pub', None), ('/base', '/cmdvel', 'sub', None)])
    diags = diagnose(s)
    assert codes(diags) == [('similar_names', '/cmd_vel'), ('no_publisher', '/cmdvel'),
                            ('no_subscriber', '/cmd_vel')]
    similar = diags[0]
    assert similar['severity'] == 'warning'
    assert similar['detail'] == {'published': '/cmd_vel', 'subscribed': '/cmdvel'}
    assert similar['nodes'] == ['/base', '/teleop']


def test_typo_publisher_next_to_a_connected_topic_still_warns():
    # /chater is published (nobody hears it) while the listener hears /chatter (the demo talker
    # feeds it): the beginner's typo, not visible as "sub-only vs pub-only".
    s = snap([('/chatter', ['T']), ('/chater', ['T'])],
             [('/talker', '/chatter', 'pub', None), ('/listener', '/chatter', 'sub', None),
              ('dummy:1', '/chater', 'pub', None)])
    diags = diagnose(s)
    assert codes(diags) == [('similar_names', '/chater'), ('no_subscriber', '/chater')]
    assert diags[0]['detail'] == {'published': '/chater', 'subscribed': '/chatter'}
    assert diags[0]['nodes'] == ['/listener', 'dummy:1']


def test_typo_subscriber_next_to_a_connected_topic_still_warns():
    s = snap([('/chatter', ['T']), ('/chater', ['T'])],
             [('/talker', '/chatter', 'pub', None), ('/listener', '/chatter', 'sub', None),
              ('/me', '/chater', 'sub', None)])
    diags = diagnose(s)
    assert codes(diags) == [('similar_names', '/chater'), ('no_publisher', '/chater')]
    assert diags[0]['detail'] == {'published': '/chatter', 'subscribed': '/chater'}


def test_one_sided_topic_without_a_similar_neighbour_is_only_info():
    s = snap([('/chatter', ['T']), ('/odom', ['T'])],
             [('/talker', '/chatter', 'pub', None), ('/listener', '/chatter', 'sub', None),
              ('/base', '/odom', 'pub', None)])
    assert [(d['code'], d['severity']) for d in diagnose(s)] == [('no_subscriber', 'info')]


def test_infrastructure_nodes_are_not_endpoints():
    # the ros2 CLI (daemon, `ros2 topic echo`) and roshanavi's own viewer / echo subscribe to
    # /scan; that must not hide the missing real subscriber, nor trigger QoS errors
    best_effort = {'reliability': 'best_effort', 'durability': 'volatile'}
    s = snap([('/scan', ['T'])],
             [('/lidar', '/scan', 'pub', best_effort),
              ('/_ros2cli_4242', '/scan', 'sub', None),
              ('/_ros2cli_daemon_0_ab', '/scan', 'sub', None),
              ('/roshanavi_viewer', '/scan', 'sub', None)])
    assert codes(diagnose(s)) == [('no_subscriber', '/scan')]


def test_lifecycle_transition_event_is_never_reported():
    s = snap([('/lc/transition_event', ['T'])], [('/lc', '/lc/transition_event', 'pub', None)])
    assert diagnose(s) == []


def test_qos_incompatible_is_error_and_first():
    best_effort = {'reliability': 'best_effort', 'durability': 'volatile'}
    s = snap([('/scan', ['sensor_msgs/msg/LaserScan']), ('/x', ['A', 'B'])],
             [('/lidar', '/scan', 'pub', best_effort), ('/slam', '/scan', 'sub', None),
              ('/p', '/x', 'pub', None), ('/s', '/x', 'sub', None)])
    diags = diagnose(s)
    assert codes(diags) == [('qos_incompatible', '/scan'), ('type_mismatch', '/x')]
    assert diags[0]['severity'] == 'error'
    assert diags[0]['detail']['reasons'][0]['policy'] == 'reliability'
    assert diags[1]['detail'] == {'types': ['A', 'B']}


def test_quiet_topics_are_not_reported_at_all():
    # a class node's action topic: subscribed, nobody publishes until a button is pressed
    s = snap([('/acc/reset', ['T']), ('/acc/rset', ['T'])],
             [('/acc', '/acc/reset', 'sub', None), ('/btn', '/acc/rset', 'pub', None)])
    assert ('no_publisher', '/acc/reset') in codes(diagnose(s))
    quiet = diagnose(s, ['/acc/reset'])
    assert codes(quiet) == [('no_subscriber', '/acc/rset')]
