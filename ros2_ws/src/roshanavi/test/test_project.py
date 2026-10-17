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
    autosaved = client.get('/api/project').json()  # every change is saved right away
    assert autosaved['dirty'] is False and autosaved['autosave'] is True
    assert os.path.isfile(autosaved['path'])
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


DEMO_TEMPLATE = 'version: 1\ntargets:\n- {id: talker, kind: run, package: demo_nodes_cpp, ' \
                'executable: talker, role: mine, autostart: true}\n'


def test_bootstrap_copies_template_only_if_absent(tmp_path):
    from roshanavi.launcher.project import bootstrap_project
    template = tmp_path / 'template.yaml'
    template.write_text(DEMO_TEMPLATE)
    target = tmp_path / 'data' / 'roshanavi.yaml'
    assert bootstrap_project(str(target), str(template)) is True
    assert target.read_text() == DEMO_TEMPLATE
    target.write_text('version: 1\n')  # the user's own project is never overwritten
    assert bootstrap_project(str(target), str(template)) is False
    assert target.read_text() == 'version: 1\n'
    assert bootstrap_project(str(tmp_path / 'other.yaml'), None) is False


def test_bootstrap_refuses_broken_template(tmp_path):
    from roshanavi.launcher.errors import LauncherError
    from roshanavi.launcher.project import bootstrap_project
    template = tmp_path / 'bad.yaml'
    template.write_text('targets: [{id: x, colour: red}]\n')
    with pytest.raises(LauncherError):
        bootstrap_project(str(tmp_path / 'p.yaml'), str(template))
    assert not (tmp_path / 'p.yaml').exists()


def test_repo_demo_project_is_valid():
    root = os.environ.get('ROSHANAVI_EXAMPLES', '/examples')  # compose `test` mounts it
    path = os.path.join(root, 'demo_project', 'roshanavi.yaml')
    if not os.path.isfile(path):
        pytest.skip('examples/ is not mounted in this environment')
    spec = parse_project(open(path).read())
    roles = {t.id: (t.role, t.autostart) for t in spec.targets}
    samples = {name: ('mine', False) for name in
               ('image_filter', 'blob_detector', 'audio_level', 'state_machine')}
    assert roles == {'talker': ('mine', True), 'listener': ('dependency', True), **samples}


def test_autosave_is_off_for_a_project_that_failed_to_load(tmp_path, data_dir):
    from roshanavi.lab import Lab
    proj = tmp_path / 'roshanavi.yaml'
    broken = 'targets: [unclosed\n'
    proj.write_text(broken)
    lab = Lab(data_dir=str(data_dir), workspace=str(tmp_path), project_path=str(proj),
              autostart=False)
    try:
        state = lab.launcher.project_state()
        assert state['error'] and state['autosave'] is False
        lab.launcher.autosave()
        assert proj.read_text() == broken
    finally:
        lab.launcher.close()
