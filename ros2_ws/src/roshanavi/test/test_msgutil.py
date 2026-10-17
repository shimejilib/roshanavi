import json

import pytest
from geometry_msgs.msg import PoseStamped
from sensor_msgs.msg import Image
from std_msgs.msg import Float64, String

from roshanavi import msgutil
from roshanavi.msgutil import MsgUtilError


def test_resolve_type_accepts_both_forms():
    assert msgutil.resolve_type('std_msgs/msg/String') is String
    assert msgutil.resolve_type('std_msgs/String') is String


@pytest.mark.parametrize('name', ['std_msgs/msg/Nope', 'no_such_pkg/msg/X', '../x', 'String',
                                  'std_msgs/srv/String', ''])
def test_resolve_type_errors(name):
    with pytest.raises(MsgUtilError) as info:
        msgutil.resolve_type(name)
    assert info.value.code == 'unknown_type'


def test_list_types_contains_std_msgs():
    types = msgutil.list_types()
    assert 'std_msgs/msg/String' in types
    assert types == sorted(types)


def test_template_is_json_friendly_dict():
    tmpl = msgutil.template('geometry_msgs/msg/PoseStamped')
    assert tmpl['pose']['position'] == {'x': 0.0, 'y': 0.0, 'z': 0.0}
    assert tmpl['header']['frame_id'] == ''
    json.dumps(tmpl)


def test_build_nested_message():
    msg = msgutil.build('geometry_msgs/msg/PoseStamped',
                        {'header': {'frame_id': 'map'}, 'pose': {'position': {'x': 1.5}}})
    assert isinstance(msg, PoseStamped)
    assert msg.header.frame_id == 'map'
    assert msg.pose.position.x == 1.5
    assert msg.pose.position.y == 0.0


def test_build_header_stamp_now():
    msg = msgutil.build('geometry_msgs/msg/PoseStamped', {'header': {'stamp': 'now'}})
    assert msg.header.stamp.sec > 0


def test_build_none_gives_default():
    assert msgutil.build('std_msgs/msg/Float64', None) == Float64()


def test_build_unknown_field_reports_path():
    with pytest.raises(MsgUtilError) as info:
        msgutil.build('geometry_msgs/msg/PoseStamped', {'pose': {'position': {'w': 1}}})
    assert info.value.code == 'invalid_field'
    assert 'pose.position.w' in str(info.value)


def test_build_bad_value_reports_path():
    with pytest.raises(MsgUtilError) as info:
        msgutil.build('geometry_msgs/msg/PoseStamped', {'pose': {'position': {'x': 'abc'}}})
    assert info.value.code == 'invalid_value'
    assert 'pose.position.x' in str(info.value)


def test_build_rejects_non_mapping():
    with pytest.raises(MsgUtilError):
        msgutil.build('std_msgs/msg/String', ['x'])


def test_to_display_truncates_arrays():
    img = Image(height=1, width=100, encoding='mono8', step=100, data=list(range(100)))
    shown = msgutil.to_display(img, max_array=8)
    assert shown['data']['_truncated'] is True
    assert shown['data']['length'] == 100
    assert shown['data']['head'] == list(range(8))
    assert shown['encoding'] == 'mono8'
    json.dumps(shown)


def test_to_display_truncates_long_strings_and_non_finite():
    shown = msgutil.to_display(String(data='x' * 50), max_str=10)
    assert shown['data'].startswith('x' * 10) and '+40' in shown['data']
    assert msgutil.to_display(Float64(data=float('nan')))['data'] == 'nan'
