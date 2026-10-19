"""User code over real ROS: nodes from scope B / C, a venv, a missing dependency, and the API.

docs/design/user-code.md §7: the fixture trees are real (src layout with relative imports, a flat
project, an installed distribution, a compiled extension, a venv with ``--system-site-packages``);
every node is a real ``ros2 run roshanavi function`` process.
"""

import json
import os
import subprocess
import sys

import pytest
from std_msgs.msg import String

from conftest import wait_for
from roshanavi.function import dependencies, modules
from roshanavi.function.scopes import CodeLocations
from roshanavi.launcher.discovery import Workspace
from roshanavi.launcher.dummy_config import class_config_text, function_config_text
from roshanavi.launcher.manager import ProcessManager
from roshanavi.launcher.schema import ClassSpec, CodeSettings, FunctionSpec
from test_dummy import stop_group
from user_code_fixtures import (SHOUT_EXTENSION, ament_python, build_extension, flat_project,
                                install_dist, make_venv, site_packages, src_layout_project, write)

SHOUT = 'def shout(text: str) -> str:\n    return text.upper()\n'


def fn_spec(name, module, function='shout', **kw):
    return FunctionSpec.model_validate({
        'id': name.replace('_', '-'), 'name': name, 'module': module, 'function': function,
        'inputs': [{'topic': f'/{name}_in', 'kind': 'string'}],
        'output': {'topic': f'/{name}_out', 'kind': 'string'}, **kw})


def status_of(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


class Node:
    def __init__(self, tmp_path, name, text, env=None):
        self.status = tmp_path / f'{name}.status.json'
        config = tmp_path / f'{name}.yaml'
        config.write_text(text.replace('__STATUS__', str(self.status)))
        self.proc = subprocess.Popen(
            ['ros2', 'run', 'roshanavi', 'function', '--config', str(config), '--ros-args', '-r',
             f'__node:={name}'], start_new_session=True, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, text=True, env=env)

    def stop(self):
        code = stop_group(self.proc)
        assert code == 0, self.proc.stdout.read()


def feed(helper, name, text='hi'):
    out = helper.collector(String, f'/{name}_out')
    helper.periodic_publisher(String, f'/{name}_in', 10, lambda i: String(data=f'{text}{i}'))
    return out


def test_b_src_layout_function_with_relative_imports_reloads_a_sibling(tmp_path, helper):
    ws = tmp_path / 'ws'
    (ws / 'src').mkdir(parents=True)
    proj = src_layout_project(tmp_path / 'work' / 'vision_lib', 'uc_vision', {
        'utils.py': "MARK = '+'\n",
        'filters.py': 'from .utils import MARK\n\n\ndef shout(text: str) -> str:\n'
                      '    return MARK + text.upper()\n'})
    code = CodeSettings(code_paths=[str(proj)])
    out = feed(helper, 'uc_b_fn')
    node = Node(tmp_path, 'uc_b_fn', function_config_text(
        fn_spec('uc_b_fn', 'uc_vision.filters'), str(ws), '__STATUS__', code))
    try:
        wait_for(lambda: out and out[-1].data.startswith('+HI'), timeout=30)
        write(proj / 'src' / 'uc_vision' / 'utils.py', "MARK = '*'\n")     # the sibling only
        wait_for(lambda: out and out[-1].data.startswith('*HI'), timeout=15)
        wait_for(lambda: status_of(node.status).get('stats', {}).get('reloads', 0) >= 1,
                 timeout=10)
        status = status_of(node.status)
        assert status['environment']['scope'] == 'code_path'
        assert status['location'].startswith('uc_vision/filters.py:')
    finally:
        node.stop()


def test_b_flat_class_node(tmp_path, helper):
    ws = tmp_path / 'ws'
    (ws / 'src').mkdir(parents=True)
    proj = flat_project(tmp_path / 'flat', 'uc_flat', {'state.py': '''\
        class Tagger:
            def __init__(self, tag: str = 'T'):
                self.tag = tag

            def process(self, text: str) -> str:
                return f'{self.tag}:{text}'
    '''})
    spec = ClassSpec.model_validate({
        'id': 'uc-b-cls', 'name': 'uc_b_cls', 'module': 'uc_flat.state', 'class_name': 'Tagger',
        'params': {'tag': 'B'}, 'methods': [{
            'method': 'process', 'inputs': [{'topic': '/uc_b_cls_in', 'kind': 'string'}],
            'outputs': [{'topic': '/uc_b_cls_out', 'kind': 'string'}]}]})
    out = feed(helper, 'uc_b_cls')
    node = Node(tmp_path, 'uc_b_cls', class_config_text(spec, str(ws), '__STATUS__',
                                                       CodeSettings(code_paths=[str(proj)])))
    try:
        wait_for(lambda: out and out[-1].data.startswith('B:hi'), timeout=30)
    finally:
        node.stop()


def test_c_installed_module_and_extension_function(tmp_path, helper):
    ws = tmp_path / 'ws'
    (ws / 'src').mkdir(parents=True)
    site = tmp_path / 'site'
    install_dist(site, 'uc-inst', '1.0', {'filters.py': SHOUT}, top='uc_inst')
    has_ext = build_extension(site, 'fastlib', SHOUT_EXTENSION) is not None
    env = {**os.environ, 'PYTHONPATH': os.pathsep.join([str(site), os.environ.get(
        'PYTHONPATH', '')])}
    code = CodeSettings(installed_modules=['uc_inst', 'fastlib'])
    out = feed(helper, 'uc_c_fn')
    node = Node(tmp_path, 'uc_c_fn', function_config_text(
        fn_spec('uc_c_fn', 'uc_inst.filters'), str(ws), '__STATUS__', code), env=env)
    nodes = [node]
    try:
        wait_for(lambda: out and out[-1].data.startswith('HI'), timeout=30)
        status = status_of(node.status)
        assert {'code': 'no_hot_reload_installed'} in status['notices']
        assert status['environment']['loaded_from'] == str(site / 'uc_inst' / 'filters.py')
        if has_ext:
            ext_out = feed(helper, 'uc_c_ext')
            nodes.append(Node(tmp_path, 'uc_c_ext', function_config_text(
                fn_spec('uc_c_ext', 'fastlib'), str(ws), '__STATUS__', code), env=env))
            wait_for(lambda: ext_out and ext_out[-1].data.endswith('!!'), timeout=30)
            assert ext_out[-1].data.startswith('HI')
    finally:
        for n in nodes:
            n.stop()


def test_missing_library_is_reported_with_the_rosdep_route(tmp_path, helper):
    """「依存不足」: the logic imports OpenCV, which this environment does not have. (numpy cannot
    be the example: rclpy itself imports numpy, so a ROS 2 node always has it.)"""
    ws = tmp_path / 'ws'
    pkg = ament_python(ws / 'src', 'uc_dep', {'logic.py': 'import cv2\n' + SHOUT})
    write(pkg / 'requirements.txt', 'uc-not-installed-zzz>=1\nnumpy\n')
    feed(helper, 'uc_dep_fn')
    node = Node(tmp_path, 'uc_dep_fn', function_config_text(
        fn_spec('uc_dep_fn', 'uc_dep.logic'), str(ws), '__STATUS__'))
    try:
        wait_for(lambda: status_of(node.status).get('state') == 'import_error', timeout=30)
        status = status_of(node.status)
        assert status['problem']['missing_module'] == 'cv2'
        assert status['problem']['location'] == 'uc_dep/logic.py:1 (<module>)'
        (req,) = status['environment']['requirements']
        assert req['file'] == 'src/uc_dep/requirements.txt'
        assert [m['name'] for m in req['missing']] == ['uc-not-installed-zzz'] and req['ok'] == 1
        resolved = modules.resolve_module(str(ws), 'uc_dep.logic')
        out = dependencies.hint('cv2', resolved, dependencies.RosdepResolver(),
                                status['environment']['python'])
        assert out['venv']['pip_name'] == 'opencv-python'
        if out['rosdep']['status'] == 'found':
            assert out['exec_depend'] == '<exec_depend>python3-opencv</exec_depend>'
            assert out['package_xml'] == str((pkg / 'package.xml').resolve())
            assert out['route'] == 'rosdep'
        # Fixing the file (here: not needing cv2 any more) loads it without a restart.
        write(pkg / 'uc_dep' / 'logic.py', SHOUT)
        wait_for(lambda: status_of(node.status).get('state') == 'running', timeout=20)
    finally:
        node.stop()


def goto_class_spec(name, module='uc_goto.goto'):
    return ClassSpec.model_validate({
        'id': name.replace('_', '-'), 'name': name, 'module': module, 'class_name': 'Goto',
        'methods': [{'method': 'process', 'inputs': [{'topic': f'/{name}_in', 'kind': 'string'}],
                     'outputs': [{'topic': f'/{name}_out', 'kind': 'string'}]}]})


PID_LIB = {'core.py': 'GAIN = 2\n\n\ndef scale(x):\n    return x * GAIN\n',
           '__init__.py': 'from .core import scale\n'}
GOTO = ('import uc_pid\n\n\nclass Goto:\n    def process(self, text: str) -> str:\n'
        '        return f"pid{uc_pid.scale(len(text))}"\n')


@pytest.mark.parametrize('build', [flat_project, src_layout_project], ids=['flat', 'src'])
def test_scope_a_class_imports_a_package_of_a_registered_code_path(tmp_path, helper, build):
    """The demo bug: ``import simple_pid`` in the user's own package, the library in a
    registered folder. The node process must find it (and the server must not import it)."""
    ws = tmp_path / 'ws'
    ament_python(ws / 'src', 'uc_goto', {'goto.py': GOTO})
    proj = build(tmp_path / 'third_party' / 'simple-pid', 'uc_pid', PID_LIB)
    out = feed(helper, 'uc_dep_cls', 'abc')
    node = Node(tmp_path, 'uc_dep_cls', class_config_text(
        goto_class_spec('uc_dep_cls'), str(ws), '__STATUS__', CodeSettings(code_paths=[str(proj)])))
    try:
        wait_for(lambda: out and out[-1].data.startswith('pid'), timeout=30)
        status = status_of(node.status)
        assert status['environment']['scope'] == 'workspace' and not status.get('problem')
        # editing the library (a dependency, not a sibling) reloads like a sibling
        write(proj / ('uc_pid' if build is flat_project else 'src/uc_pid') / 'core.py',
              'GAIN = 5\n\n\ndef scale(x):\n    return x * GAIN\n')
        wait_for(lambda: out and int(out[-1].data[3:]) >= 20, timeout=15)   # GAIN 5 * 4+ chars
        wait_for(lambda: status_of(node.status).get('stats', {}).get('reloads', 0) >= 1,
                 timeout=10)
    finally:
        node.stop()


def test_unregistering_the_code_path_gives_a_clear_error_and_the_right_advice(tmp_path, helper):
    ws = tmp_path / 'ws'
    ament_python(ws / 'src', 'uc_goto', {'goto.py': GOTO})
    proj = flat_project(tmp_path / 'third_party' / 'simple-pid', 'uc_pid', PID_LIB)
    spec = goto_class_spec('uc_unreg')
    feed(helper, 'uc_unreg', 'abc')
    node = Node(tmp_path, 'uc_unreg', class_config_text(spec, str(ws), '__STATUS__'))
    try:   # not registered
        wait_for(lambda: status_of(node.status).get('state') == 'import_error', timeout=30)
        problem = status_of(node.status)['problem']
        assert problem['missing_module'] == 'uc_pid'
        assert 'No module named' in problem['message']
        plain = dependencies.hint('uc_pid', None, dependencies.RosdepResolver(),
                                  status_of(node.status)['environment']['python'],
                                  CodeLocations(str(ws)))
        assert plain['route'] in ('rosdep', 'venv') and plain['code_places']['registered'] == []
    finally:
        node.stop()
    # registered somewhere it is not: the advice names the registered place, not rosdep / pip
    empty = tmp_path / 'third_party' / 'uc-pid'
    write(empty / 'README.md', 'no package here')
    loc = CodeLocations(str(ws), code_paths=(str(empty),))
    out = dependencies.hint('uc_pid', None, dependencies.RosdepResolver(), {}, loc)
    assert out['route'] == 'code_path_missing' and out['code_places']['looks_like']['path'] == str(
        empty) and out['rosdep']['status'] == 'skipped'
    # registered where it is, after the node started: restart
    now = CodeLocations(str(ws), code_paths=(str(proj),))
    assert dependencies.hint('uc_pid', None, dependencies.RosdepResolver(), {}, now)[
        'route'] == 'code_path_restart'


def test_a_standard_library_name_in_a_code_path_is_refused_for_dependency_use(tmp_path, helper):
    ws = tmp_path / 'ws'
    ament_python(ws / 'src', 'uc_goto', {'goto.py': 'import winreg\n' + GOTO.split('\n', 1)[1]})
    proj = tmp_path / 'proj'
    write(proj / 'winreg' / '__init__.py', "WHO = 'user'\n")   # not importable on Linux: stdlib name
    write(proj / 'json' / '__init__.py', "WHO = 'user'\n")
    feed(helper, 'uc_shadow', 'abc')
    node = Node(tmp_path, 'uc_shadow', class_config_text(
        goto_class_spec('uc_shadow'), str(ws), '__STATUS__', CodeSettings(code_paths=[str(proj)])))
    try:
        wait_for(lambda: status_of(node.status).get('state') == 'import_error', timeout=30)
        assert status_of(node.status)['problem']['missing_module'] == 'winreg'
    finally:
        node.stop()


def test_venv_node_uses_a_library_installed_only_in_the_venv(tmp_path, helper):
    """依存 ②: roshanavi started from an activated venv (``--system-site-packages``) runs its
    function nodes with that venv's Python, so a library installed only there imports."""
    venv = make_venv(tmp_path / 'venv')
    site = site_packages(venv)
    install_dist(site, 'uc-venvonly', '1.0', {'__init__.py': 'def mark(t):\n    return "V:" + t\n'},
                 top='uc_venvonly')
    ws = tmp_path / 'ws'
    pkg = ament_python(ws / 'src', 'uc_venv_pkg', {
        'logic.py': 'from uc_venvonly import mark\n\n\ndef shout(text: str) -> str:\n'
                    '    return mark(text)\n'})
    write(pkg / 'requirements.txt', 'uc-venvonly==1.0\n')
    assert str(site) not in sys.path
    env = {**os.environ, 'VIRTUAL_ENV': str(venv),
           'PATH': f'{venv}/bin{os.pathsep}{os.environ["PATH"]}'}
    manager = ProcessManager(Workspace(str(ws), env=env), str(tmp_path / 'data'),
                             timeouts=(3.0, 2.0))
    try:
        manager.code = CodeSettings(installed_modules=['uc_venvonly'])
        interpreter = manager.node_interpreter()
        assert interpreter['venv'] is True and interpreter['executable'].startswith(str(venv))
        listed = [m['module'] for m in modules.list_modules(manager.locations())]
        assert 'uc_venvonly' in listed       # found on the venv's path, not the server's
        manager.code = CodeSettings()
        out = feed(helper, 'uc_venv_fn')
        manager.add(fn_spec('uc_venv_fn', 'uc_venv_pkg.logic'))
        info = manager.start('uc-venv-fn')
        assert info['command'][:4] == [info['command'][0], 'run', '--prefix', str(venv / 'bin' /
                                                                                  'python3')]
        wait_for(lambda: out and out[-1].data.startswith('V:hi'), timeout=30)
        status = manager.function_status('uc-venv-fn')
        assert status['environment']['python']['venv'] is True
        assert status['environment']['python']['executable'] == str(venv / 'bin' / 'python3')
        (req,) = status['environment']['requirements']
        assert req['missing'] == [] and req['ok'] == 1
    finally:
        manager.close()


def test_without_a_venv_the_command_is_unchanged(tmp_path):
    ws = tmp_path / 'ws'
    ament_python(ws / 'src', 'uc_plain', {'logic.py': SHOUT})
    env = {k: v for k, v in os.environ.items() if k != 'VIRTUAL_ENV'}
    manager = ProcessManager(Workspace(str(ws), env=env), str(tmp_path / 'data'))
    try:
        argv = manager._argv(fn_spec('uc_plain_fn', 'uc_plain.logic'))
        assert argv[1:4] == ['run', 'roshanavi', 'function'] and '--prefix' not in argv
        assert manager.node_interpreter()['executable']
    finally:
        manager.close()


# ---- the API on a workspace of its own -------------------------------------------------------
@pytest.fixture
def uc_client(tmp_path, data_dir):
    from fastapi.testclient import TestClient
    from roshanavi.lab import Lab
    from roshanavi.server import create_app
    ws = tmp_path / 'ws'
    ament_python(ws / 'src', 'uc_api_pkg', {'logic.py': 'import cv2\n' + SHOUT})
    lab = Lab(data_dir=str(data_dir), period_sec=0.2, workspace=str(ws),
              project_path=str(tmp_path / 'project' / 'roshanavi.yaml'),
              stop_timeouts=(3.0, 2.0)).start()
    try:
        with TestClient(create_app(lab, static_dir=None, live_period=0.2),
                        base_url='http://localhost') as client:
            yield client, ws, tmp_path
    finally:
        lab.stop()


def test_locations_scaffold_and_dependency_api(uc_client, helper):
    client, ws, tmp_path = uc_client
    body = client.get('/api/functions/locations').json()
    assert body['src'] == str((ws / 'src').resolve()) and body['settings'] == {
        'code_paths': [], 'installed_modules': []}
    assert body['python']['executable'] and 'path' not in body['python']
    assert [p['top'] for p in body['scopes']['workspace']['packages']] == ['uc_api_pkg']

    # B: register a project; bad places are refused with the reason
    proj = flat_project(tmp_path / 'proj', 'uc_api_b', {'m.py': SHOUT})
    data = client.get('/api/health').json().get('data_dir') or str(tmp_path / 'data')
    for bad, status in (('/', 400), (str(tmp_path / 'nope'), 404), (data, 400),
                        (str(tmp_path / 'proj' / '.git'), 400)):
        r = client.put('/api/functions/locations', json={'code_paths': [bad]})
        assert r.status_code == status and r.json()['error']['code'] == 'invalid_code_path', \
            (bad, r.text)
    r = client.put('/api/functions/locations', json={'code_paths': [str(proj)],
                                                     'installed_modules': ['not_there_xyz']})
    assert r.status_code == 200, r.text
    assert r.json()['settings']['code_paths'] == [str(proj)]
    assert any(p['code'] == 'installed_not_found' for p in r.json()['problems'])
    assert client.put('/api/functions/locations', json={'code_paths': ['x', 'x']}).status_code \
        == 422
    project = client.get('/api/project').json()['project']
    assert project['code_paths'] == [str(proj)] and project['installed_modules'] == [
        'not_there_xyz']
    listed = {m['module']: m for m in client.get('/api/functions/modules').json()['modules']}
    assert listed['uc_api_b.m']['scope'] == 'code_path'

    # 「ひな形を作る」 then it is listed and runs as a function node
    r = client.post('/api/functions/scaffold', json={'name': 'uc_api_logic'})
    assert r.status_code == 201, r.text
    assert r.json()['module'] == 'uc_api_logic.logic'
    again = client.post('/api/functions/scaffold', json={'name': 'uc_api_logic'})
    assert again.status_code == 409 and again.json()['error']['code'] == 'file_exists'
    assert client.post('/api/functions/scaffold', json={'name': 'Bad'}).json()['error'][
        'code'] == 'invalid_package_name'
    out = helper.collector(String, '/uc_api_fn_out')
    helper.periodic_publisher(String, '/uc_api_fn_in', 10, lambda i: String(data=f'api{i}'))
    spec = fn_spec('uc_api_fn', 'uc_api_logic.logic', function='convert').model_dump()
    assert client.post('/api/functions?start=true', json=spec).status_code == 201
    wait_for(lambda: out and out[-1].data.startswith('API'), timeout=30)

    # B module through the API too (the node gets the code paths in its config)
    b_out = helper.collector(String, '/uc_api_bfn_out')
    helper.periodic_publisher(String, '/uc_api_bfn_in', 10, lambda i: String(data=f'b{i}'))
    b_spec = fn_spec('uc_api_bfn', 'uc_api_b.m').model_dump()
    assert client.post('/api/functions?start=true', json=b_spec).status_code == 201
    wait_for(lambda: b_out and b_out[-1].data.startswith('B'), timeout=30)

    # the dependency hint
    hint = client.get('/api/functions/dependency', params={
        'missing': 'cv2', 'module': 'uc_api_pkg.logic'}).json()
    assert hint['missing'] == 'cv2' and hint['venv']['commands']
    if hint['rosdep']['status'] == 'found':
        assert hint['exec_depend'] == '<exec_depend>python3-opencv</exec_depend>'
        assert hint['package_xml'] == str((ws / 'src' / 'uc_api_pkg' / 'package.xml').resolve())
    assert client.get('/api/functions/dependency', params={'missing': '../x'}).status_code == 422
    # a library of a registered place: restart advice (no rosdep), and the server (this process)
    # never makes registered code importable for itself
    mine = client.get('/api/functions/dependency', params={'missing': 'uc_api_b'}).json()
    assert mine['route'] == 'code_path_restart' and mine['code_places']['found_in']['path'] == str(
        proj)
    from roshanavi.function.code_imports import CodeImportFinder
    assert not [f for f in sys.meta_path if isinstance(f, CodeImportFinder)]
    assert 'uc_api_b' not in sys.modules


def test_locations_api_returns_the_host_src_hint(uc_client, monkeypatch):
    client = uc_client[0]
    monkeypatch.delenv('ROSHANAVI_HOST_SRC_HINT', raising=False)
    assert client.get('/api/functions/locations').json()['host_src_hint'] is None
    monkeypatch.setenv('ROSHANAVI_HOST_SRC_HINT', 'clone したフォルダの workspace/')
    body = client.get('/api/functions/locations').json()
    assert body['host_src_hint'] == 'clone したフォルダの workspace/' and body['src_writable']


def test_new_routes_are_behind_the_host_origin_content_type_guard(uc_client):
    client = uc_client[0]
    assert client.get('/api/functions/locations', headers={'Host': 'evil.com'}).status_code == 403
    r = client.post('/api/functions/scaffold', content='{"name": "x_logic"}',
                    headers={'Content-Type': 'text/plain'})
    assert r.status_code == 415
    r = client.put('/api/functions/locations', content='{}', headers={'Content-Type': 'text/plain'})
    assert r.status_code == 415
    assert client.get('/api/functions/dependency', params={'missing': 'numpy'},
                      headers={'Host': 'evil.com'}).status_code == 403
