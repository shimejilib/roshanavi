"""データの種類 <-> ROS type mapping and the Python value conversions (docs/design/nodes.md)."""

import array

import numpy as np
import pytest

from roshanavi import data_kinds as dk
from roshanavi import msgutil


def test_table_matches_the_design():
    assert {k.id: k.types[0] for k in dk.KINDS} == {
        'string': 'std_msgs/msg/String', 'float': 'std_msgs/msg/Float64',
        'int': 'std_msgs/msg/Int64', 'bool': 'std_msgs/msg/Bool',
        'numbers': 'std_msgs/msg/Float64MultiArray', 'json': 'std_msgs/msg/String',
        'image': 'sensor_msgs/msg/Image', 'audio': 'audio_common_msgs/msg/AudioDataStamped',
        'bytes': 'std_msgs/msg/UInt8MultiArray'}


def test_audio_falls_back_when_audio_common_is_missing():
    assert dk.ros_type('audio', installed=lambda t: not t.startswith('audio_common')) \
        == 'std_msgs/msg/Int16MultiArray'
    assert dk.ros_type('audio', installed=lambda t: True) \
        == 'audio_common_msgs/msg/AudioDataStamped'


def test_unknown_kind_is_rejected():
    with pytest.raises(dk.KindError) as err:
        dk.ros_type('video')
    assert err.value.code == 'unknown_kind'


@pytest.mark.parametrize('type_name,kind', [
    ('std_msgs/msg/String', 'string'), ('std_msgs/String', 'string'),
    ('std_msgs/msg/Float32', 'float'), ('std_msgs/msg/Int32', 'int'),
    ('std_msgs/msg/UInt8MultiArray', 'bytes'), ('std_msgs/msg/Float32MultiArray', 'numbers'),
    ('sensor_msgs/msg/Image', 'image'), ('geometry_msgs/msg/Twist', None),
    ('sensor_msgs/msg/CompressedImage', None)])
def test_kind_of_type(type_name, kind):
    assert dk.kind_of_type(type_name) == kind


def test_resolve_explicit_types_must_fit_the_kind():
    assert dk.resolve('float') == ('float', 'std_msgs/msg/Float64')
    assert dk.resolve('float', 'std_msgs/Float32') == ('float', 'std_msgs/msg/Float32')
    assert dk.resolve('json', 'std_msgs/msg/String') == ('json', 'std_msgs/msg/String')
    assert dk.resolve('message', 'geometry_msgs/Twist') == ('message', 'geometry_msgs/msg/Twist')
    with pytest.raises(dk.KindError):
        dk.resolve('int', 'std_msgs/msg/String')
    with pytest.raises(dk.KindError):
        dk.resolve('message')


def test_catalog_lists_every_kind_with_its_installed_type():
    body = dk.catalog()
    assert [k['id'] for k in body['kinds']] == list(dk.KIND_IDS)
    assert all(k['available'] for k in body['kinds'] if k['id'] != 'audio')
    assert body['type_kinds']['std_msgs/msg/Float32'] == 'float'


def test_type_groups_order_common_then_workspace_then_by_package():
    types = ['zzz_msgs/msg/A', 'my_pkg/msg/Thing', 'std_msgs/msg/String', 'geometry_msgs/msg/Twist',
             'geometry_msgs/msg/Accel', 'std_msgs/msg/Header', 'action_msgs/msg/GoalInfo']
    groups = dk.type_groups(types, ['my_pkg'])
    assert groups[0] == {'id': 'common', 'types': ['std_msgs/msg/String', 'std_msgs/msg/Header',
                                                   'geometry_msgs/msg/Twist']}
    assert groups[1] == {'id': 'workspace', 'types': ['my_pkg/msg/Thing']}
    assert [(g['package'], g['types']) for g in groups[2:]] == [
        ('action_msgs', ['action_msgs/msg/GoalInfo']), ('geometry_msgs', ['geometry_msgs/msg/Accel']),
        ('zzz_msgs', ['zzz_msgs/msg/A'])]


# ---- conversions ---------------------------------------------------------------------------
@pytest.mark.parametrize('kind,value', [
    ('string', 'héllo'), ('float', 1.5), ('int', -7), ('bool', True),
    ('numbers', [1.0, 2.5]), ('json', {'a': [1, 2], 'b': 'x'}), ('bytes', b'\x00\xff\x10')])
def test_round_trip(kind, value):
    type_name = dk.ros_type(kind)
    msg = dk.from_python(kind, value, type_name)
    assert type(msg).__name__ == type_name.rsplit('/', 1)[-1]
    assert dk.to_python(kind, msg, type_name) == value


def test_numeric_conversions_are_strict_but_accept_numpy():
    f64, i64 = 'std_msgs/msg/Float64', 'std_msgs/msg/Int64'
    assert dk.from_python('float', 2, f64).data == 2.0
    assert dk.from_python('float', np.float32(0.5), f64).data == 0.5
    assert dk.from_python('int', np.int64(3), i64).data == 3
    assert dk.from_python('int', 4.0, i64).data == 4
    for kind, bad, type_name in [('float', True, f64), ('float', '1', f64), ('int', 1.5, i64),
                                 ('int', False, i64), ('bool', 1, 'std_msgs/msg/Bool'),
                                 ('string', 3, 'std_msgs/msg/String'),
                                 ('numbers', 'abc', 'std_msgs/msg/Float64MultiArray'),
                                 ('json', {1, 2}, 'std_msgs/msg/String'),
                                 ('bytes', [256], 'std_msgs/msg/UInt8MultiArray')]:
        with pytest.raises(dk.KindError) as err:
            dk.from_python(kind, bad, type_name)
        assert 'the function returned' in str(err.value)


def test_compatible_types_keep_their_own_type():
    msg = dk.from_python('numbers', np.array([1, 2, 3]), 'std_msgs/msg/Int32MultiArray')
    assert list(msg.data) == [1, 2, 3]
    f32 = msgutil.build('std_msgs/msg/Float32', {'data': 0.25})
    assert dk.to_python('float', f32) == 0.25


def test_image_numpy_round_trip_rgb_and_mono():
    rgb = np.zeros((4, 6, 3), dtype=np.uint8)
    rgb[1, 2] = (10, 20, 30)
    msg = dk.from_python('image', rgb, 'sensor_msgs/msg/Image')
    assert (msg.width, msg.height, msg.encoding, msg.step) == (6, 4, 'rgb8', 18)
    back = dk.to_python('image', msg)
    assert back.shape == (4, 6, 3) and back[1, 2].tolist() == [10, 20, 30]
    mono = np.full((3, 5), 200, dtype=np.uint8)
    msg = dk.from_python('image', mono, 'sensor_msgs/msg/Image')
    assert msg.encoding == 'mono8'
    assert dk.to_python('image', msg).shape == (3, 5)
    bgr = msgutil.build('sensor_msgs/msg/Image', {'height': 1, 'width': 1, 'encoding': 'bgr8',
                                                  'step': 3, 'data': [1, 2, 3]})
    assert dk.to_python('image', bgr)[0, 0].tolist() == [3, 2, 1]
    for bad in (rgb.astype(np.float32), np.zeros((2, 2, 4), np.uint8), [[1]]):
        with pytest.raises(dk.KindError):
            dk.from_python('image', bad, 'sensor_msgs/msg/Image')


def test_audio_numpy_round_trip_fallback_type():
    samples = np.array([0, 1000, -1000, 32767], dtype=np.int16)
    type_name = 'std_msgs/msg/Int16MultiArray'
    msg = dk.from_python('audio', samples, type_name)
    assert dk.to_python('audio', msg, type_name).tolist() == samples.tolist()
    with pytest.raises(dk.KindError):
        dk.from_python('audio', samples.astype(np.float32), type_name)


def test_message_kind_uses_plain_dicts():
    twist = dk.from_python('message', {'linear': {'x': 0.5}}, 'geometry_msgs/msg/Twist')
    assert twist.linear.x == 0.5
    plain = dk.to_python('message', twist)
    assert plain['linear']['x'] == 0.5 and plain['angular']['z'] == 0.0
    with pytest.raises(dk.KindError):
        dk.from_python('message', 'not a dict', 'geometry_msgs/msg/Twist')
    with pytest.raises(dk.KindError):
        dk.from_python('message', {'nope': 1}, 'geometry_msgs/msg/Twist')


def test_bytes_accept_bytearray_and_int_lists():
    t = 'std_msgs/msg/UInt8MultiArray'
    assert bytes(dk.from_python('bytes', bytearray(b'ab'), t).data) == b'ab'
    assert isinstance(dk.payload('bytes', [1, 2], t)['data'], array.array)


def test_invalid_json_input_is_a_kind_error():
    msg = msgutil.build('std_msgs/msg/String', {'data': '{oops'})
    with pytest.raises(dk.KindError) as err:
        dk.to_python('json', msg)
    assert err.value.code == 'invalid_json'


def test_input_node_spec_kind_must_fit_its_type():
    from roshanavi.launcher.schema import DummySpec
    base = dict(id='a', name='a', topic='/a', type='std_msgs/msg/String', mode='once')
    assert DummySpec(**base, kind='json').kind == 'json'
    assert DummySpec(**base).kind is None
    with pytest.raises(ValueError, match='does not carry'):
        DummySpec(**base, kind='int')
