"""Launch decomposition import: evaluation subprocess, coverage, containment, commit, API."""

import os
import time

import pytest
import yaml

from launch_fixtures import write_fixtures
from roshanavi.launch_import.importer import LaunchImporter, PackageSource, PathSource
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.service import Launcher


@pytest.fixture
def ws(tmp_path):
    root = tmp_path / 'ws'
    write_fixtures(str(root / 'launch'))
    return root


@pytest.fixture
def launcher(ws, data_dir, tmp_path):
    instance = Launcher(str(ws), str(data_dir), project_path=str(tmp_path / 'p.yaml'),
                        autostart=False)
    yield instance
    instance.close()


@pytest.fixture
def importer(launcher, data_dir):
    return LaunchImporter(launcher, str(data_dir), timeout_sec=20.0)


def preview(importer, name, **args):
    return importer.preview(PathSource(kind='path', path=f'launch/{name}'), args)


def by_fq(plan):
    return {n['fq_name']: n for n in plan['nodes']}


def codes(items):
    return sorted(i['code'] for i in items)


def test_python_launch_is_decomposed(importer, tmp_path):
    marker = tmp_path / 'executed'
    plan = preview(importer, 'main.launch.py', rate='5', marker=str(marker))
    nodes = by_fq(plan)
    assert set(nodes) == {'/r1/talker', '/listener', '/inner_talker'}
    talker = nodes['/r1/talker']
    spec = talker['spec']
    assert spec['package'] == 'demo_nodes_cpp' and spec['executable'] == 'talker'
    assert spec['namespace'] == '/r1' and spec['name'] == 'talker'
    assert spec['remaps'] == {'chatter': 'talk', 'extra': '/abs_extra'}
    assert spec['params'] == {'use_sim_time': False, 'rate': 99, 'nested.gain': 1.5,
                              'common': 7, 'from_file': 'yes'}
    assert talker['file_params'] == {'ids': [1, 2]}
    assert talker['param_files'][0].endswith('params.yaml')
    assert talker['importable'], talker['problem']
    assert spec['imported_from'] == 'launch/main.launch.py'
    assert nodes['/inner_talker']['file'].endswith('sub.launch.py')
    assert codes(plan['blocked']) == ['composable_container', 'execute_process',
                                      'include_failed', 'timer']
    container = next(b for b in plan['blocked'] if b['code'] == 'composable_container')
    assert container['composable_nodes'] == ['composition/composition::Talker (comp_talker)']
    assert [s['detail'] for s in plan['skipped']] == [
        'Node demo_nodes_py/listener (py_listener)']
    assert not marker.exists()  # the ExecuteProcess was reported, never run
    assert plan['whole'] is None and plan['whole_reason'] == 'not_in_package'


def test_arguments_and_conditions(importer):
    missing = preview(importer, 'main.launch.py')
    assert missing['missing_args'] == ['rate'] and missing['nodes'] == []
    rate = next(a for a in missing['arguments'] if a['name'] == 'rate')
    assert rate['default'] is None and rate['description'] == 'publish rate'
    flipped = by_fq(preview(importer, 'main.launch.py', rate='1', use_listener='false',
                            robot='r2'))
    assert set(flipped) == {'/r2/talker', '/py_listener', '/inner_talker'}
    # the params file names /r1/talker only, so r2 gets the wildcard entry
    assert flipped['/r2/talker']['spec']['params']['rate'] == 1


def test_xml_and_yaml_launch_files(importer):
    xml = preview(importer, 'main.launch.xml')
    talker = by_fq(xml)['/xml_ns/xml_talker']['spec']
    assert talker['params'] == {'greeting': 'hi', 'count': 3}
    assert talker['remaps'] == {'chatter': '/xml_chatter'}
    assert codes(xml['blocked']) == ['execute_process'] and len(xml['skipped']) == 1
    yml = by_fq(preview(importer, 'main.launch.yaml', who='y'))
    assert yml['/yaml_ns/y_listener']['spec']['params'] == {'flag': True}


def test_prints_do_not_corrupt_the_result(importer):
    plan = preview(importer, 'prints.launch.py')
    node = plan['nodes'][0]
    assert node['fq_name'] is None and node['spec']['id'] == 'talker'
    assert [w['code'] for w in node['warnings']] == ['node_name_unknown']


def test_problems_are_reported_per_node(importer):
    nodes = preview(importer, 'unknown.launch.py')['nodes']
    assert [n['importable'] for n in nodes] == [False, False]
    assert nodes[0]['problem']['code'] == 'unknown_executable'
    assert nodes[1]['problem']['code'] == 'invalid_arg'


def test_broken_file_and_timeout(importer, launcher, data_dir):
    with pytest.raises(LauncherError) as err:
        preview(importer, 'broken.launch.py')
    assert err.value.code == 'launch_eval_failed' and 'SyntaxError' in str(err.value)
    quick = LaunchImporter(launcher, str(data_dir), timeout_sec=2.0)
    started = time.monotonic()
    with pytest.raises(LauncherError) as err:
        preview(quick, 'slow.launch.py')
    assert err.value.code == 'launch_eval_timeout' and err.value.status == 504
    assert time.monotonic() - started < 10


def test_containment(importer, ws, tmp_path, launcher):
    outside = tmp_path / 'outside.launch.py'
    outside.write_text('raise SystemExit(1)\n')
    os.symlink(outside, ws / 'launch' / 'link.launch.py')
    for path in ('/etc/passwd', '../outside.launch.py', 'launch/link.launch.py',
                 'launch/params.txt'):
        with pytest.raises(LauncherError) as err:
            importer.preview(PathSource(kind='path', path=path), {})
        assert err.value.code in ('forbidden_path', 'invalid_file'), path
    inner_data = ws / 'data'
    inner_data.mkdir()
    (inner_data / 'up.launch.py').write_text('')
    guarded = LaunchImporter(launcher, str(inner_data))
    with pytest.raises(LauncherError) as err:
        guarded.preview(PathSource(kind='path', path='data/up.launch.py'), {})
    assert err.value.code == 'forbidden_path' and err.value.status == 403
    with pytest.raises(LauncherError) as err:
        importer.preview(PathSource(kind='path', path='launch/main.launch.py'), {'bad-arg': '1'})
    assert err.value.code == 'invalid_arg'


def test_commit_nodes_writes_param_file(importer, launcher, data_dir):
    plan = preview(importer, 'main.launch.py', rate='5')
    talker = by_fq(plan)['/r1/talker']['index']
    result = importer.commit(plan['preview_id'], 'nodes', [talker], 'mine', autostart=False)
    assert result['errors'] == []
    target = result['created'][0]
    assert target['role'] == 'mine' and target['spec']['id'] == 'talker'
    params_file = target['spec']['params_file']
    assert params_file.startswith(str(data_dir))
    with open(params_file) as handle:
        assert yaml.safe_load(handle) == {'/**': {'ros__parameters': {'ids': [1, 2]}}}
    again = importer.commit(plan['preview_id'], 'nodes', [talker], 'dependency')
    assert again['created'][0]['id'] == 'talker-2'
    assert {t['id'] for t in launcher.targets()} == {'talker', 'talker-2'}
    with pytest.raises(LauncherError) as err:
        importer.commit(plan['preview_id'], 'whole', [], 'mine')
    assert err.value.code == 'whole_unavailable'
    with pytest.raises(LauncherError) as err:
        importer.commit('0' * 32, 'nodes', [0], 'mine')
    assert err.value.code == 'preview_expired'


def test_package_launch_file_and_whole_fallback(importer, launcher):
    source = PackageSource(kind='package', package='demo_nodes_cpp',
                           launch_file='talker_listener_launch.py')
    plan = importer.preview(source, {})
    assert [n['spec']['executable'] for n in plan['nodes']] == ['talker', 'listener']
    assert plan['origin'] == 'demo_nodes_cpp/talker_listener_launch.py'
    result = importer.commit(plan['preview_id'], 'whole', [], 'dependency')
    whole = result['created'][0]
    assert whole['kind'] == 'launch' and whole['spec']['launch_file'] == \
        'talker_listener_launch.py'
    with pytest.raises(LauncherError) as err:
        importer.preview(PackageSource(kind='package', package='demo_nodes_cpp',
                                       launch_file='nope.launch.py'), {})
    assert err.value.code == 'unknown_launch_file'


def test_launch_import_api(client):
    body = {'source': {'kind': 'package', 'package': 'roshanavi',
                       'launch_file': 'demo_system.launch.py'}, 'args': {'robot': 'api'}}
    resp = client.post('/api/launch-import/preview', json=body)
    assert resp.status_code == 200, resp.text
    plan = resp.json()
    assert sorted(n['fq_name'] for n in plan['nodes']) == ['/api/imported_listener',
                                                           '/api/imported_talker']
    assert codes(plan['blocked']) == ['execute_process'] and plan['whole'] is not None
    commit = client.post('/api/launch-import/commit', json={
        'preview_id': plan['preview_id'], 'indices': [0, 1], 'role': 'dependency'})
    assert commit.status_code == 201, commit.text
    created = [t['id'] for t in commit.json()['created']]
    assert sorted(created) == ['imported_listener', 'imported_talker']
    rows = client.get('/api/node-list').json()['rows']
    assert {r['target_id'] for r in rows if r['origin'].get('imported_from')} == set(created)
    bad = client.post('/api/launch-import/preview', json={'source': {'kind': 'path',
                                                                     'path': '/etc/passwd'}})
    assert bad.status_code in (400, 403)
    for target_id in created:
        client.delete(f'/api/targets/{target_id}')
