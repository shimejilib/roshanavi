"""Parameter services client: pure value conversion + a real rclpy node."""

import pytest
from rcl_interfaces.msg import ParameterDescriptor, ParameterValue, SetParametersResult

from conftest import wait_for
from roshanavi.api_errors import ApiError
from roshanavi.params import (ParamService, check_node_name, check_param_name, value_from_msg,
                              value_to_msg)
from roshanavi.ros_runtime import RosRuntime


@pytest.mark.parametrize('type_name,value', [
    ('bool', True), ('integer', -5), ('double', 2.5), ('double', 3), ('string', 'hi'),
    ('integer_array', [1, 2]), ('double_array', [0.5]), ('string_array', ['a']),
    ('bool_array', [True, False]), ('byte_array', [0, 255])])
def test_value_round_trip(type_name, value):
    back_type, back = value_from_msg(value_to_msg(type_name, value))
    assert back_type == type_name and back == value


@pytest.mark.parametrize('type_name,value', [
    ('bool', 1), ('integer', True), ('integer', 1.5), ('integer', 2 ** 63), ('double', 'x'),
    ('double', float('inf')), ('string', 5), ('string', 'x' * 5000), ('integer_array', [1, 'a']),
    ('byte_array', [256]), ('string_array', 'abc'), ('mystery', 1)])
def test_value_rejects_wrong_types(type_name, value):
    with pytest.raises(ApiError):
        value_to_msg(type_name, value)


def test_not_set_value():
    assert value_from_msg(ParameterValue()) == ('not_set', None)


def test_name_checks():
    assert check_node_name('/ns/talker') == '/ns/talker'
    assert check_param_name('qos_overrides./chatter.publisher.depth')
    for bad in ('talker', '/a b', '/1x', '/a//b'):
        with pytest.raises(ApiError):
            check_node_name(bad)
    for bad in ('', 'a..b', 'x;rm', '-p'):
        with pytest.raises(ApiError):
            check_param_name(bad)


@pytest.fixture
def target_node(helper):
    node = helper.node
    node.declare_parameter('rate', 2.0, ParameterDescriptor(description='publish rate'))
    node.declare_parameter('label', 'a')
    node.declare_parameter('fixed', 1, ParameterDescriptor(read_only=True))

    def reject_negative(params):
        ok = all(not (p.name == 'rate' and p.value < 0) for p in params)
        return SetParametersResult(successful=ok, reason='' if ok else 'rate must be >= 0')
    node.add_on_set_parameters_callback(reject_negative)
    return node.get_fully_qualified_name()


@pytest.fixture
def service():
    runtime = RosRuntime('roshanavi_ptest')
    runtime.start()
    svc = ParamService(runtime, timeout_sec=3.0)
    yield svc
    svc.close()
    runtime.stop()


def test_list_get_set_on_real_node(service, target_node):
    params = {p['name']: p for p in service.list(target_node)}
    assert params['rate']['type'] == 'double' and params['rate']['value'] == 2.0
    assert params['rate']['description'] == 'publish rate'
    assert params['fixed']['read_only'] is True
    assert 'use_sim_time' in params

    updated = service.set(target_node, 'rate', 'double', 5.0)
    assert updated['value'] == 5.0
    with pytest.raises(ApiError) as info:
        service.set(target_node, 'rate', 'double', -1.0)
    assert info.value.code == 'param_rejected' and 'rate must be' in str(info.value)
    with pytest.raises(ApiError) as info:
        service.set(target_node, 'fixed', 'integer', 2)
    assert info.value.code == 'param_read_only'
    with pytest.raises(ApiError) as info:
        service.set(target_node, 'label', 'integer', 3)
    assert info.value.code == 'param_type_mismatch'


def test_unknown_node_times_out_quickly():
    runtime = RosRuntime('roshanavi_ptest2')
    runtime.start()
    svc = ParamService(runtime, timeout_sec=0.5)
    try:
        with pytest.raises(ApiError) as info:
            svc.list('/does_not_exist')
        assert info.value.code == 'param_service_unavailable' and info.value.status == 504
    finally:
        svc.close()
        runtime.stop()


def test_rest_parameters_external_policy(client, lab, target_node):
    path = f'/api/nodes{target_node}/parameters'
    wait_for(lambda: client.get(path).status_code == 200, timeout=15.0)
    body = client.get(path).json()
    assert body['external'] is True and any(p['name'] == 'rate' for p in body['parameters'])

    change = {'name': 'rate', 'type': 'double', 'value': 4.0}
    denied = client.put(path, json=change)
    assert denied.status_code == 403 and denied.json()['error']['code'] == 'external_node_readonly'
    allowed = client.put(path, json={**change, 'allow_external': True})
    assert allowed.status_code == 200, allowed.text
    assert allowed.json()['parameter']['value'] == 4.0

    assert client.get('/api/nodes/no_such_node/parameters').status_code == 404
    bad = client.put(path, json={**change, 'type': 'complex'})
    assert bad.status_code == 422
    assert client.put('/api/nodes/roshanavi/parameters',
                      json={**change, 'allow_external': True}).status_code == 403


def test_class_param_order_follows_the_init_signature(client, lab, monkeypatch):
    from roshanavi import server_nodes
    body = {'id': 'ord', 'name': 'ord', 'module': 'roshanavi_examples.stateful',
            'class_name': 'Counter',
            'methods': [{'method': 'process', 'inputs': [{'topic': '/ord_in', 'kind': 'string'}],
                         'outputs': [{'topic': '/ord_out', 'kind': 'int'}]}]}
    assert client.post('/api/classes', json=body).status_code == 201
    fake = {'classes': [{'name': 'Counter', 'init_params': [{'name': 'zeta'}, {'name': 'alpha'}]}]}
    monkeypatch.setattr(server_nodes.class_modules, 'describe_module', lambda *a: fake)
    assert server_nodes.class_param_order(lab, {'id': '/ord', 'target_id': 'ord'}) == [
        'zeta', 'alpha']
    # not a class node / unknown target / unreadable module: no order, no error
    assert server_nodes.class_param_order(lab, {'id': '/x', 'target_id': 'nope'}) is None
    assert server_nodes.class_param_order(lab, {'id': '/x'}) is None
    monkeypatch.setattr(server_nodes.class_modules, 'describe_module',
                        lambda *a: (_ for _ in ()).throw(ValueError('broken')))
    assert server_nodes.class_param_order(lab, {'id': '/ord', 'target_id': 'ord'}) is None


def test_rest_parameters_of_a_plain_node_have_no_init_order(client, lab, target_node):
    path = f'/api/nodes{target_node}/parameters'
    wait_for(lambda: client.get(path).status_code == 200, timeout=15.0)
    assert client.get(path).json()['init_order'] is None
