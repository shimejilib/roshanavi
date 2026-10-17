"""roshanavi.yaml: schema validation, stable round trip, atomic save, REST."""

import os

import pytest
import yaml

from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.project import ProjectStore, dump_project, parse_project
from roshanavi.launcher.schema import ProjectSpec

EXAMPLE = '''
version: 1
targets:
  - id: talker
    kind: run
    package: demo_nodes_cpp
    executable: talker
    name: my_talker
    params: {rate: 2, use_sim_time: false}
    remaps: {chatter: /chat}
    role: mine
    autostart: true
  - id: pair
    kind: launch
    package: demo_nodes_cpp
    launch_file: talker_listener_launch.py
    args: ["foo:=bar"]
dummies:
  - id: cam
    name: dummy_camera
    topic: /camera/info
    type: std_msgs/msg/String
    mode: periodic
    payload: {data: "frame ${i}"}
    rate_hz: 5
watch_topics: [/chat]
'''


def test_round_trip_is_stable_and_ordered():
    spec = parse_project(EXAMPLE)
    text = dump_project(spec)
    assert parse_project(text) == spec
    assert dump_project(parse_project(text)) == text  # stable across saves
    body = yaml.safe_load(text)
    assert list(body) == ['version', 'targets', 'dummies', 'watch_topics']
    assert list(body['targets'][0])[:4] == ['id', 'kind', 'package', 'executable']
    assert 'launch_file' not in body['targets'][0]  # empty values are omitted
    assert text.startswith('# roshanavi project')


@pytest.mark.parametrize('text,fragment', [
    ('targets: [{id: a, kind: run, package: p, executable: e, colour: red}]',
     'targets.0.colour: extra fields not permitted'),
    ('targets: [{id: a, kind: warp, package: p}]', 'targets.0.kind'),
    ('dummies: [{id: d, name: n, topic: /t, type: std_msgs/msg/String, mode: periodic}]',
     'dummies.0: mode "periodic" needs "rate_hz"'),
    ('version: 2', 'version'),
    ('surprise: 1', 'surprise: extra fields not permitted'),
    ('targets: [{id: a, kind: run, package: p, executable: e},'
     ' {id: a, kind: run, package: p, executable: e}]', "duplicate id 'a'"),
    ('targets: [unclosed', 'invalid YAML (line 1'),
    ('- just a list', 'top level must be a mapping'),
])
def test_validation_errors_are_path_specific(text, fragment):
    with pytest.raises(LauncherError) as err:
        parse_project(text, 'roshanavi.yaml')
    assert err.value.code == 'invalid_project'
    assert fragment in str(err.value), str(err.value)


def test_store_atomic_save_and_dirty(tmp_path):
    path = tmp_path / 'proj' / 'roshanavi.yaml'
    store = ProjectStore(str(path))
    assert not store.exists() and store.load() == ProjectSpec()
    spec = parse_project(EXAMPLE)
    assert store.is_dirty(spec)
    store.save(spec)
    assert not store.is_dirty(spec)
    assert [p.name for p in path.parent.iterdir()] == ['roshanavi.yaml']  # no temp leftovers
    assert ProjectStore(str(path)).load() == spec


def test_rest_project_flow(client, lab, tmp_path):
    state = client.get('/api/project').json()
    assert state['exists'] is False and state['dirty'] is False
    target = {'id': 'talk', 'kind': 'run', 'package': 'demo_nodes_cpp', 'executable': 'talker',
              'role': 'mine'}
    assert client.post('/api/targets', json=target).status_code == 201
    assert client.get('/api/project').json()['dirty'] is True
    saved = client.post('/api/project/save').json()
    assert saved['dirty'] is False and os.path.isfile(saved['path'])
    on_disk = yaml.safe_load(open(saved['path']))
    assert on_disk['targets'] == [target | {'autostart': False, 'auto_restart': False}]

    body = parse_project(EXAMPLE).dict()
    put = client.put('/api/project', json=body)
    assert put.status_code == 200, put.text
    ids = [t['id'] for t in client.get('/api/targets').json()['targets']]
    assert ids == ['talker', 'pair', 'cam']
    bad = client.put('/api/project', json={**body, 'extra': 1})
    assert bad.status_code == 422 and bad.json()['error']['code'] == 'validation_error'


def test_project_with_missing_package_still_opens(tmp_path, data_dir):
    from roshanavi.lab import Lab
    proj = tmp_path / 'roshanavi.yaml'
    proj.write_text('targets: [{id: gone, kind: run, package: not_installed, executable: x}]\n')
    lab = Lab(data_dir=str(data_dir), workspace=str(tmp_path), project_path=str(proj),
              autostart=False)
    try:
        (target,) = lab.launcher.targets()
        assert target['status'] == 'invalid' and 'not_installed' in target['problem']
    finally:
        lab.launcher.close()
