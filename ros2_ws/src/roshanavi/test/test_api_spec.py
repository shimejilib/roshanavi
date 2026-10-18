"""API specs always carry their port lists (the UI maps over them); project files stay lean."""

import yaml

from roshanavi.launcher.project import dump_project
from roshanavi.launcher.schema import (ClassSpec, FunctionSpec, ProjectSpec, TransformSpec,
                                       api_dict, clean_dict)

SINK = {'method': 'on_pose', 'call': 'on_message',
        'inputs': [{'topic': '/turtle1/pose', 'kind': 'message', 'type': 'turtlesim/msg/Pose'}]}
SOURCE = {'method': 'render', 'call': 'periodic', 'rate_hz': 10,
          'outputs': [{'topic': '/turtle_viz/image', 'kind': 'image'}]}


def class_spec(**kw):
    base = {'id': 'canvas', 'name': 'canvas', 'module': 'viz', 'class_name': 'TrajectoryCanvas',
            'methods': [SINK, SOURCE], 'actions': ['reset']}
    return ClassSpec.model_validate({**base, **kw})


def test_class_methods_keep_empty_port_lists_for_the_api():
    out = api_dict(class_spec())
    sink, source = out['methods']
    assert sink['outputs'] == [] and len(sink['inputs']) == 1
    assert source['inputs'] == [] and len(source['outputs']) == 1


def test_actions_only_class_keeps_empty_methods_and_actions():
    out = api_dict(class_spec(methods=[], actions=['reset']))
    assert out['methods'] == [] and out['actions'] == ['reset']
    assert api_dict(class_spec(methods=[SINK], actions=[]))['actions'] == []


def test_periodic_function_keeps_empty_inputs():
    spec = FunctionSpec.model_validate({
        'id': 'tick', 'name': 'tick', 'module': 'm', 'function': 'tick', 'call': 'periodic',
        'rate_hz': 1, 'output': {'topic': '/tick', 'kind': 'float'}})
    assert api_dict(spec)['inputs'] == []
    assert 'inputs' not in clean_dict(spec)


def test_transform_dict_is_unchanged():
    spec = TransformSpec.model_validate({
        'id': 't', 'name': 't', 'mode': 'relay', 'inputs': [{'topic': '/a', 'type': 'std_msgs/msg/String'}],
        'output': {'topic': '/b'}})
    assert api_dict(spec)['inputs'][0]['topic'] == '/a'


def test_project_file_stays_free_of_empty_lists_and_round_trips():
    project = ProjectSpec.model_validate({'classes': [class_spec().model_dump()]})
    text = dump_project(project)
    assert 'inputs: []' not in text and 'outputs: []' not in text
    reloaded = ProjectSpec.model_validate(yaml.safe_load(text))
    assert reloaded == project
    assert dump_project(reloaded) == text
    # the API form loads back to the same project too
    assert ProjectSpec.model_validate(api_dict(project)) == project


def test_rest_target_and_project_carry_empty_port_lists(client, lab):
    body = class_spec(module='roshanavi_examples.stateful', class_name='Counter', actions=[],
                      methods=[{**SINK, 'method': 'process'},
                               {**SOURCE, 'method': 'reset'}]).model_dump()
    resp = client.post('/api/classes', json=body)
    assert resp.status_code == 201, resp.text
    methods = {m['method']: m for m in resp.json()['spec']['methods']}
    assert methods['process']['outputs'] == [] and methods['reset']['inputs'] == []
    listed = next(t for t in client.get('/api/targets').json()['targets'] if t['id'] == 'canvas')
    assert {m['method']: m['outputs'] for m in listed['spec']['methods']}['process'] == []
    project = client.get('/api/project').json()['project']
    assert project['classes'][0]['methods'][0]['outputs'] == []
    # put it back unchanged: still valid, and the saved file is lean
    assert client.put('/api/project', json=project).status_code == 200
    assert client.post('/api/project/save').status_code == 200
    with open(lab.launcher.project.path, encoding='utf-8') as handle:
        saved = handle.read()
    assert 'process' in saved and 'inputs: []' not in saved and 'outputs: []' not in saved
