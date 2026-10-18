"""「ひな形を作る」 (docs/design/user-code.md §4): the package, its checks, and that it really works.

End to end on a fresh workspace: scaffold → it runs as a function node and as a class node right
away (no build: ``ros2 run roshanavi function`` loads the source) → ``colcon build
--packages-select`` builds it → the generated ROS-free pytest passes.
"""

import json
import os
import subprocess
import sys

import pytest
from std_msgs.msg import String

from conftest import wait_for
from roshanavi.function import modules, scaffold
from roshanavi.function.class_modules import describe_module
from roshanavi.function.scopes import CodeLocations
from roshanavi.launcher.dummy_config import class_config_text, function_config_text
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.schema import ClassSpec, FunctionSpec
from test_dummy import stop_group


@pytest.fixture
def ws(tmp_path):
    (tmp_path / 'ws' / 'src').mkdir(parents=True)
    return tmp_path / 'ws'


def test_generated_files_and_static_listing(ws):
    result = scaffold.scaffold(CodeLocations.of(str(ws)), 'my_logic')
    root = ws / 'src' / 'my_logic'
    assert result == {'package': 'my_logic', 'directory': str(root.resolve()),
                      'module': 'my_logic.logic', 'function': 'convert',
                      'class_name': 'Processor', 'files': result['files']}
    rel = sorted(os.path.relpath(p, root.resolve()) for p in result['files'])
    assert rel == sorted(['package.xml', 'setup.py', 'setup.cfg', 'resource/my_logic',
                          'my_logic/__init__.py', 'my_logic/logic.py', 'test/test_logic.py',
                          'README.md'])
    xml = (root / 'package.xml').read_text()
    assert '<name>my_logic</name>' in xml and '<build_type>ament_python</build_type>' in xml
    assert '<exec_depend>python3-numpy</exec_depend>' in xml and '<!--' in xml   # an example
    assert 'rosdep install' in xml and '--' not in xml.split('<!--', 1)[1].split('-->', 1)[0]
    assert 'rosdep install --from-paths src/my_logic --ignore-src -y' in (root / 'README.md'
                                                                          ).read_text()
    info = describe_module(str(ws), 'my_logic.logic')
    (fn,) = info['functions']
    assert fn['signature'] == 'convert(text: str) -> str' and fn['returns_kind'] == 'string'
    (cls,) = info['classes']
    assert cls['name'] == 'Processor'
    assert [p['name'] for p in cls['init_params']] == ['prefix']
    assert {m['name']: m['action_candidate'] for m in cls['methods']} == {'process': False,
                                                                           'reset': True}
    assert 'my_logic.logic' in [m['module'] for m in modules.list_modules(str(ws))]
    assert 'roshanavi' not in (root / 'my_logic' / 'logic.py').read_text().split('"""', 2)[2]


@pytest.mark.parametrize('name', ['My_logic', '1logic', 'a__b', 'ends_', 'class', 'json', 'rclpy',
                                  'numpy', 'roshanavi', 'x' * 65, 'a-b', 'a b', '', 'a\nb',
                                  '../evil', 'a/b'])
def test_invalid_names_are_refused(ws, name):
    with pytest.raises(LauncherError) as err:
        scaffold.scaffold(CodeLocations.of(str(ws)), name)
    assert err.value.code == 'invalid_package_name'
    assert os.listdir(ws / 'src') == []


def test_never_overwrites(ws):
    existing = ws / 'src' / 'my_logic'
    existing.mkdir()
    (existing / 'mine.txt').write_text('keep')
    with pytest.raises(LauncherError) as err:
        scaffold.scaffold(CodeLocations.of(str(ws)), 'my_logic')
    assert err.value.code == 'file_exists' and err.value.status == 409
    assert os.listdir(existing) == ['mine.txt'] and (existing / 'mine.txt').read_text() == 'keep'
    with pytest.raises(LauncherError) as err:     # a ROS package of that name exists somewhere
        scaffold.scaffold(CodeLocations.of(str(ws)), 'other_logic', taken_packages=['other_logic'])
    assert err.value.code == 'name_taken'
    os.symlink('/tmp', ws / 'src' / 'linked')     # a dangling / outward link is not reused
    with pytest.raises(LauncherError) as err:
        scaffold.scaffold(CodeLocations.of(str(ws)), 'linked')
    assert err.value.code == 'file_exists'


def test_a_python_package_of_the_same_name_is_taken(ws, tmp_path):
    proj = tmp_path / 'proj'
    (proj / 'b_logic').mkdir(parents=True)
    (proj / 'b_logic' / '__init__.py').write_text('')
    with pytest.raises(LauncherError) as err:
        scaffold.scaffold(CodeLocations(str(ws), code_paths=(str(proj),)), 'b_logic')
    assert err.value.code == 'name_taken'


def test_failure_midway_removes_only_what_it_created(ws, monkeypatch):
    real_open = os.open
    count = [0]

    def failing_open(path, flags, mode=0o777):
        count[0] += 1
        if count[0] == 4:
            raise OSError(30, 'Read-only file system')
        return real_open(path, flags, mode)

    monkeypatch.setattr(os, 'open', failing_open)
    with pytest.raises(LauncherError) as err:
        scaffold.scaffold(CodeLocations.of(str(ws)), 'half_logic')
    assert err.value.code == 'not_writable' and err.value.status == 403
    assert os.listdir(ws / 'src') == []


def test_rendered_python_compiles_for_every_valid_name():
    for name in ('my_logic', 'a', 'robot_2_brain'):
        files = scaffold.render(name)
        for rel, text in files.items():
            if rel.endswith('.py'):
                compile(text, rel, 'exec')
        assert f'from {name}.logic import Processor, convert' in files['test/test_logic.py']


# ---- end to end (real ROS) -------------------------------------------------------------------
def _start(tmp_path, text, name):
    config = tmp_path / f'{name}.yaml'
    config.write_text(text)
    return subprocess.Popen(['ros2', 'run', 'roshanavi', 'function', '--config', str(config),
                             '--ros-args', '-r', f'__node:={name}'], start_new_session=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def _status(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return {}


def test_scaffold_runs_as_function_and_class_node_builds_and_tests(ws, tmp_path, helper):
    result = scaffold.scaffold(CodeLocations.of(str(ws)), 'uc_logic')
    helper.periodic_publisher(String, '/uc_scaf_in', 10, lambda i: String(data=f'hi{i}'))

    # 1. function node, straight from the source (no build)
    fn_out = helper.collector(String, '/uc_scaf_fn_out')
    fn = FunctionSpec.model_validate({
        'id': 'uc-fn', 'name': 'uc_scaf_fn', 'module': result['module'],
        'function': result['function'], 'inputs': [{'topic': '/uc_scaf_in', 'kind': 'string'}],
        'output': {'topic': '/uc_scaf_fn_out', 'kind': 'string'}})
    fn_status = tmp_path / 'fn.status.json'
    proc = _start(tmp_path, function_config_text(fn, str(ws), str(fn_status)), 'uc_scaf_fn')
    try:
        wait_for(lambda: fn_out and fn_out[-1].data.startswith('HI'), timeout=30)
        env = _status(fn_status)['environment']
        assert env['python']['executable'] and env['scope'] == 'workspace'
        assert env['requirements'] == []
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()

    # 2. class node of the same file: process + reset as an action
    cls_out = helper.collector(String, '/uc_scaf_cls_out')
    cls = ClassSpec.model_validate({
        'id': 'uc-cls', 'name': 'uc_scaf_cls', 'module': result['module'],
        'class_name': result['class_name'], 'params': {'prefix': 'No.'},
        'methods': [{'method': 'process', 'inputs': [{'topic': '/uc_scaf_in', 'kind': 'string'}],
                     'outputs': [{'topic': '/uc_scaf_cls_out', 'kind': 'string'}]}],
        'actions': ['reset']})
    cls_status = tmp_path / 'cls.status.json'
    proc = _start(tmp_path, class_config_text(cls, str(ws), str(cls_status)), 'uc_scaf_cls')
    try:
        wait_for(lambda: cls_out and cls_out[-1].data.startswith('No.'), timeout=30)
        wait_for(lambda: _status(cls_status).get('state') == 'running', timeout=10)
        number = int(cls_out[-1].data.split()[0][3:])
        wait_for(lambda: int(cls_out[-1].data.split()[0][3:]) > number, timeout=10)
    finally:
        assert stop_group(proc) == 0, proc.stdout.read()

    # 3. colcon build of just this package
    build = subprocess.run(['colcon', 'build', '--packages-select', 'uc_logic',
                            '--event-handlers', 'console_direct-'], cwd=ws, capture_output=True,
                           text=True, timeout=300)
    assert build.returncode == 0, build.stdout + build.stderr
    assert (ws / 'install' / 'uc_logic' / 'share' / 'uc_logic' / 'package.xml').is_file()
    assert list((ws / 'install' / 'uc_logic' / 'lib').glob('python3*/site-packages/uc_logic/'
                                                           'logic.py'))

    # 4. the generated ROS-free pytest (as the README says, and from the workspace root)
    pkg = ws / 'src' / 'uc_logic'
    for cwd, target in ((pkg, 'test'), (ws, 'src/uc_logic/test')):
        run = subprocess.run([sys.executable, '-m', 'pytest', '-q', '-p', 'no:cacheprovider',
                              target], cwd=cwd, capture_output=True, text=True, timeout=120)
        assert run.returncode == 0 and '2 passed' in run.stdout, run.stdout + run.stderr
