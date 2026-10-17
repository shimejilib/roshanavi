import pytest

from roshanavi.api_errors import ApiError
from roshanavi.interfaces import field_type, nested_type, show


def test_header_is_expanded_with_nested_time():
    result = show('std_msgs/msg/Header')
    assert 'builtin_interfaces/Time stamp' in result['expanded']
    assert '\tint32 sec' in result['expanded'] and '\tuint32 nanosec' in result['expanded']
    assert 'string frame_id' in result['text']


def test_service_definition_keeps_separator():
    result = show('rcl_interfaces/srv/GetParameters')
    assert '---' in result['expanded']
    assert 'ParameterValue[] values' in result['expanded']
    assert '\tuint8 type' in result['expanded']  # nested fields of ParameterValue


def test_field_type_parsing():
    assert field_type('int32[] data  # comment') == 'int32'
    assert field_type('string<=10 name') == 'string'
    assert field_type('geometry_msgs/Point[<=3] points') == 'geometry_msgs/Point'
    assert field_type('# only a comment') is None and field_type('---') is None
    assert nested_type('Header', 'sensor_msgs') == 'std_msgs/msg/Header'
    assert nested_type('Point', 'geometry_msgs') == 'geometry_msgs/msg/Point'
    assert nested_type('float64', 'x') is None


@pytest.mark.parametrize('name,code', [('std_msgs/msg/../x', 'invalid_interface'),
                                       ('std_msgs/String', 'invalid_interface'),
                                       ('no_such_pkg/msg/Thing', 'unknown_interface')])
def test_bad_names(name, code):
    with pytest.raises(ApiError) as info:
        show(name)
    assert info.value.code == code


def test_rest_interface(client):
    ok = client.get('/api/interfaces/std_msgs/msg/String')
    assert ok.status_code == 200 and 'string data' in ok.json()['expanded']
    assert client.get('/api/interfaces/nope/msg/Nope').status_code == 404
    assert client.get('/api/interfaces/std_msgs/bad/String').status_code == 400
