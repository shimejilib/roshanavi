import pytest

from roshanavi.diagnostics import diagnose, is_hidden_topic, levenshtein, names_similar

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


def test_healthy_graph_has_no_diagnostics():
    s = snap([('/chatter', ['std_msgs/msg/String'])],
             [('/talker', '/chatter', 'pub', None), ('/listener', '/chatter', 'sub', None)])
    assert diagnose(s) == []


def test_one_sided_and_similar_names():
    s = snap([('/cmd_vel', ['T']), ('/cmdvel', ['T']), ('/rosout', ['T']), ('/orphan', ['T'])],
             [('/teleop', '/cmd_vel', 'pub', None), ('/base', '/cmdvel', 'sub', None),
              ('/teleop', '/rosout', 'pub', None)])
    diags = diagnose(s)
    assert codes(diags) == [('no_publisher', '/cmdvel'), ('no_subscriber', '/cmd_vel'),
                            ('similar_names', '/cmd_vel')]
    similar = diags[-1]
    assert similar['detail'] == {'published': '/cmd_vel', 'subscribed': '/cmdvel'}
    assert similar['nodes'] == ['/base', '/teleop']


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
