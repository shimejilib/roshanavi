"""Transform spec validation, the computer (mapping / filter / conversion) and the dry run."""

import pytest

from roshanavi.launcher.project import dump_project, parse_project
from roshanavi.launcher.schema import ProjectSpec, TransformSpec
from roshanavi.msg_view import MsgView
from roshanavi.pydantic_compat import ValidationError
from roshanavi.transform.compute import CONDITION_PATH, Computer
from roshanavi.transform.preview import preview

STRING = 'std_msgs/msg/String'


def tspec(**kw):
    base = {'id': 'up', 'name': 'rn_upper', 'inputs': [{'topic': '/chatter', 'type': STRING}],
            'output': {'topic': '/chatter_upper', 'type': STRING},
            'mapping': {'data': '${upper(msg.data)}'}}
    return TransformSpec.model_validate({**base, **kw})


def view(**fields):
    return MsgView(fields)


# ---- schema ----------------------------------------------------------------------------

def test_default_aliases_single_and_multi():
    assert tspec().inputs[0].alias == 'msg'
    multi = tspec(inputs=[{'topic': '/a', 'type': STRING}, {'topic': '/b', 'type': STRING}],
                  mapping={'data': '${msg1.data + msg2.data}'})
    assert [i.alias for i in multi.inputs] == ['msg1', 'msg2']


@pytest.mark.parametrize('kw,needle', [
    ({'mode': 'relay'}, 'no mapping'),
    ({'mode': 'relay', 'mapping': None, 'condition': 'msg.data'}, 'no mapping'),
    ({'mode': 'relay', 'mapping': None, 'output': {'topic': '/o', 'type': 'std_msgs/msg/Int32'}},
     'cannot change the type'),
    ({'inputs': [{'topic': '/img', 'type': 'sensor_msgs/msg/Image'}], 'mapping': None,
      'output': {'topic': '/o'}}, 'large type'),
    ({'trigger': 'nope'}, 'trigger'),
    ({'inputs': [{'topic': '/a', 'type': STRING, 'alias': 'x'},
                 {'topic': '/b', 'type': STRING, 'alias': 'x'}]}, 'unique'),
    ({'inputs': [{'topic': '/a', 'type': STRING, 'alias': 'now'}]}, 'reserved'),
    ({'inputs': [{'topic': '/a', 'type': STRING}, {'topic': '/b', 'type': STRING}],
      'mapping': None}, 'several inputs'),
    ({'delay': {'min_ms': 50, 'max_ms': 10}}, 'max_ms'),
    ({'drop_ratio': 1.5}, 'less than or equal'),
    ({'throttle_hz': 0}, 'greater than'),
    ({'inputs': []}, 'at least 1'),
])
def test_invalid_specs(kw, needle):
    with pytest.raises(ValidationError) as info:
        tspec(**kw)
    assert needle in str(info.value)


def test_relay_of_heavy_type_and_output_type_default():
    spec = tspec(mode='relay', mapping=None,
                 inputs=[{'topic': '/img', 'type': 'sensor_msgs/Image'}],
                 output={'topic': '/img_relay'}, delay={'min_ms': 100},
                 throttle_hz=5, drop_ratio=0.1)
    assert spec.output.type == 'sensor_msgs/Image'


def test_project_round_trip_keeps_transforms():
    project = ProjectSpec(transforms=[tspec(condition="msg.data != ''", throttle_hz=2,
                                            delay={'min_ms': 10, 'max_ms': 20})])
    text = dump_project(project)
    assert 'transforms:' in text and "upper(msg.data)" in text
    assert parse_project(text) == project


def test_project_ids_unique_across_transforms():
    with pytest.raises(Exception, match='duplicate id'):
        parse_project(dump_project(ProjectSpec(transforms=[tspec(), tspec()])))


# ---- computer --------------------------------------------------------------------------

def test_mapping_filter_and_conversion():
    comp = Computer(tspec(condition="msg.data != ''"))
    assert comp.compute({'msg': view(data='hi')}).output == {'data': 'HI'}
    filtered = comp.compute({'msg': view(data='')})
    assert not filtered.passed and not filtered.errors

    conv = Computer(tspec(output={'topic': '/n', 'type': 'std_msgs/msg/Int32'},
                          mapping={'data': '${int(msg.data) * 2}'}))
    assert conv.compute({'msg': view(data='21')}).output == {'data': 42}
    bad = conv.compute({'msg': view(data='abc')})
    assert not bad.passed and bad.errors[0].path == 'data' and bad.errors[0].code == 'eval_failed'


def test_literals_nested_fields_and_copy_mode():
    comp = Computer(tspec(output={'topic': '/t', 'type': 'geometry_msgs/msg/Twist'},
                          inputs=[{'topic': '/in', 'type': 'geometry_msgs/msg/Twist'}],
                          mapping={'linear': {'x': '${msg.linear.x * 0.5}', 'y': 1.0},
                                   'angular': {'z': '${clamp(msg.angular.z, -1, 1)}'}}))
    out = comp.compute({'msg': view(linear={'x': 4.0, 'y': 0.0}, angular={'z': 3.0})}).output
    assert out == {'linear': {'x': 2.0, 'y': 1.0}, 'angular': {'z': 1}}
    copy = Computer(tspec(mapping=None, condition='len(msg.data) > 2'))
    assert copy.compute({'msg': view(data='abc')}).output == {'data': 'abc'}
    assert not copy.compute({'msg': view(data='ab')}).passed


def test_compile_errors_are_reported_per_field():
    comp = Computer(tspec(condition='msg.__class__',
                          mapping={'data': '${upper(msg.data}', 'other': '${foo}'}))
    assert not comp.ok
    by_path = {e.path: e.code for e in comp.compile_errors}
    assert by_path == {CONDITION_PATH: 'bad_field', 'data': 'syntax', 'other': 'unknown_name'}


def test_variables_i_and_multi_input():
    comp = Computer(tspec(inputs=[{'topic': '/a', 'type': STRING, 'alias': 'left'},
                                  {'topic': '/b', 'type': STRING, 'alias': 'right'}],
                          mapping={'data': '${left.data + "|" + right.data + str(i)}'}))
    out = comp.compute({'left': view(data='L'), 'right': view(data='R')}, {'i': 7})
    assert out.output == {'data': 'L|R7'}


# ---- dry run (preview) -------------------------------------------------------------------

def test_preview_output_and_template_fallback():
    raw = tspec().model_dump()
    result = preview(raw, {'msg': {'data': 'hello'}})
    assert result['ok'] and result['passed'] and result['output'] == {'data': 'HELLO'}
    fallback = preview(raw, {})
    assert fallback['ok'] and fallback['templated'] == ['msg'] and fallback['output'] == {'data': ''}


def test_preview_reports_field_errors_and_filter():
    raw = tspec(mapping={'data': '${upper(msg.nope)}'}).model_dump()
    result = preview(raw, {'msg': {'data': 'x'}})
    assert not result['ok'] and result['errors'][0]['path'] == 'data'
    assert result['errors'][0]['code'] == 'no_field'
    assert 'data' in result['errors'][0]['params']['fields']
    filtered = preview(tspec(condition="msg.data == 'go'").model_dump(), {'msg': {'data': 'stop'}})
    assert filtered['ok'] and filtered['passed'] is False and filtered['output'] is None


def test_preview_reports_build_errors_at_the_field():
    raw = tspec(output={'topic': '/n', 'type': 'std_msgs/msg/Int32'},
                mapping={'data': '${msg.data}'}).model_dump()
    result = preview(raw, {'msg': {'data': 'not a number'}})
    assert not result['ok'] and result['errors'][0]['path'] == 'data'
    assert result['errors'][0]['code'].startswith('build_')


def test_preview_spec_errors_and_unknown_samples():
    bad = preview({'id': 'x', 'name': 'n', 'inputs': [], 'output': {'topic': '/o'}}, {})
    assert not bad['ok'] and bad['errors'][0]['code'] == 'spec_invalid'
    unknown = preview(tspec().model_dump(), {'other': {'data': 'x'}})
    assert not unknown['ok'] and unknown['errors'][0]['code'] == 'bad_sample'


def test_preview_relay_echoes_the_sample():
    raw = tspec(mode='relay', mapping=None, inputs=[{'topic': '/img',
                                                     'type': 'sensor_msgs/msg/Image'}],
                output={'topic': '/img2'}).model_dump()
    result = preview(raw, {'msg': {'width': 4}})
    assert result['ok'] and result['relay'] and result['output'] == {'width': 4}


def test_preview_api(client):
    body = {'spec': tspec().model_dump(), 'samples': {'msg': {'data': 'abc'}}}
    resp = client.post('/api/transforms/preview', json=body)
    assert resp.status_code == 200, resp.text
    assert resp.json()['output'] == {'data': 'ABC'}
    too_many = {'spec': tspec().model_dump(), 'samples': {f's{i}': {} for i in range(9)}}
    assert client.post('/api/transforms/preview', json=too_many).status_code == 422
    extra = {'spec': tspec().model_dump(), 'oops': 1}
    assert client.post('/api/transforms/preview', json=extra).status_code == 422
