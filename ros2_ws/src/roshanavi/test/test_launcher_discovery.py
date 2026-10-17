"""Workspace discovery against the installed demo packages and fake workspaces."""

import os

import pytest

from roshanavi.launcher.discovery import Workspace
from roshanavi.launcher.env import child_env
from roshanavi.launcher.errors import LauncherError
from ws_fixtures import fake_prefix, fake_source

WS_ROOT = os.environ.get('ROSHANAVI_TEST_WS', '/ws')


@pytest.fixture(scope='module')
def real_ws():
    return Workspace(WS_ROOT)


def by_name(ws):
    return {p['name']: p for p in ws.to_dict()['packages']}


def test_system_demo_packages(real_ws):
    pkgs = by_name(real_ws)
    cpp, py = pkgs['demo_nodes_cpp'], pkgs['demo_nodes_py']
    assert cpp['origin'] == 'system' and cpp['sourced'] and cpp['built']
    assert {'talker', 'listener'} <= set(cpp['executables'])
    assert 'talker_listener_launch.py' in cpp['launch_files']
    assert 'talker_listener_launch.xml' in cpp['launch_files']
    assert {'talker', 'listener'} <= set(py['executables'])
    assert real_ws.require_executable('demo_nodes_cpp', 'talker').name == 'demo_nodes_cpp'


def test_own_workspace_package_comes_first(real_ws):
    packages = real_ws.to_dict()['packages']
    assert packages[0]['origin'] == 'workspace'
    mine = by_name(real_ws)['roshanavi']
    assert mine['origin'] == 'workspace'
    assert mine['source_dir'] == os.path.realpath(os.path.join(WS_ROOT, 'src', 'roshanavi'))
    assert {'server', 'dummy'} <= set(mine['executables'])


def test_unknown_lookups(real_ws):
    for call, code in ((lambda: real_ws.package('no_such_pkg'), 'unknown_package'),
                       (lambda: real_ws.require_executable('demo_nodes_cpp', 'nope'),
                        'unknown_executable'),
                       (lambda: real_ws.require_launch_file('demo_nodes_cpp', 'x.launch.py'),
                        'unknown_launch_file')):
        with pytest.raises(LauncherError) as err:
            call()
        assert err.value.code == code


def test_isolated_layout_sources_and_unsourced(tmp_path):
    fake_prefix(tmp_path / 'install' / 'built_pkg', 'built_pkg', ['run_me'], ['a.launch.xml'])
    fake_source(tmp_path / 'src' / 'group', 'built_pkg')
    fake_source(tmp_path / 'src', 'unbuilt_pkg')
    ignored = fake_source(tmp_path / 'src', 'ignored_pkg')
    (ignored / 'COLCON_IGNORE').write_text('')
    ws = Workspace(str(tmp_path), env={'AMENT_PREFIX_PATH': ''})
    pkgs = by_name(ws)
    assert pkgs['built_pkg']['origin'] == 'workspace' and not pkgs['built_pkg']['sourced']
    assert pkgs['built_pkg']['executables'] == ['run_me']
    assert pkgs['built_pkg']['source_dir'].endswith('src/group/built_pkg')
    assert pkgs['unbuilt_pkg']['built'] is False
    assert 'ignored_pkg' not in pkgs
    assert ws.unsourced_prefixes() == [os.path.realpath(tmp_path / 'install' / 'built_pkg')]


def test_merged_layout_and_refresh(tmp_path):
    fake_prefix(tmp_path / 'install', 'merged_a', ['x'])
    ws = Workspace(str(tmp_path), env={'AMENT_PREFIX_PATH': str(tmp_path / 'install')})
    assert by_name(ws)['merged_a']['sourced'] is True
    fake_prefix(tmp_path / 'install', 'merged_b', ['y'])
    assert 'merged_b' not in by_name(ws)  # cached until refresh
    ws.refresh()
    assert by_name(ws)['merged_b']['executables'] == ['y']


def test_child_env_applies_colcon_dsv(tmp_path):
    prefix = tmp_path / 'install' / 'new_pkg'
    hook = prefix / 'share' / 'new_pkg' / 'hook'
    hook.mkdir(parents=True)
    (prefix / 'share' / 'new_pkg' / 'package.dsv').write_text(
        'source;share/new_pkg/hook/ament_prefix_path.dsv\n'
        'source;share/new_pkg/hook/ament_prefix_path.sh\n'
        'source;share/new_pkg/hook/pythonpath.dsv\n')
    (hook / 'ament_prefix_path.dsv').write_text('prepend-non-duplicate;AMENT_PREFIX_PATH;\n')
    (hook / 'pythonpath.dsv').write_text(
        'prepend-non-duplicate;PYTHONPATH;lib/python3.12/site-packages\n')
    env = child_env({'AMENT_PREFIX_PATH': '/opt/ros/jazzy', 'PYTHONPATH': '/a'}, [str(prefix)])
    assert env['AMENT_PREFIX_PATH'] == f'{prefix}:/opt/ros/jazzy'
    assert env['PYTHONPATH'] == f'{prefix}/lib/python3.12/site-packages:/a'
    assert env['PYTHONUNBUFFERED'] == '1' and env['RCUTILS_COLORIZED_OUTPUT'] == '0'
