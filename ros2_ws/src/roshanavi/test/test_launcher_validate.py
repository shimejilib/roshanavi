"""Launcher argument validation: argv building and injection attempts (no processes)."""

import os

import pytest

from roshanavi.launcher import validate
from roshanavi.launcher.command import CommandContext, target_command
from roshanavi.launcher.discovery import Workspace
from roshanavi.launcher.errors import LauncherError
from roshanavi.launcher.schema import TargetSpec
from ws_fixtures import fake_prefix


@pytest.fixture
def ctx(tmp_path):
    fake_prefix(tmp_path / 'install' / 'pkg_a', 'pkg_a', executables=['node_a'],
                launch_files=['demo.launch.py'])
    (tmp_path / 'params.yaml').write_text('node_a:\n  ros__parameters: {x: 1}\n')
    outside = tmp_path.parent / f'{tmp_path.name}_outside.yaml'
    outside.write_text('{}\n')
    ws = Workspace(str(tmp_path), env={'AMENT_PREFIX_PATH': ''})
    return CommandContext(ws, (ws.root,)), outside


def run_spec(**kw):
    return TargetSpec(**{'id': 't1', 'kind': 'run', 'package': 'pkg_a', 'executable': 'node_a',
                         **kw})


def test_run_command_puts_every_value_in_its_own_argv_item(ctx):
    context, _ = ctx
    argv = target_command(run_spec(name='my_node', namespace='robot1',
                                   params={'rate': 10, 'label': 'a b; rm -rf /', 'on': True},
                                   remaps={'in': '/camera/image'}, args=['--verbose'],
                                   params_file='params.yaml'), context)
    assert argv[1:5] == ['run', 'pkg_a', 'node_a', '--verbose']
    rest = argv[5:]
    assert rest[0] == '--ros-args'
    assert ['-r', '__node:=my_node'] == rest[1:3]
    assert ['-r', '__ns:=/robot1'] == rest[3:5]
    assert '-p' in rest and 'label:=a b; rm -rf /' in rest  # one item, never a shell
    assert 'on:=true' in rest and 'rate:=10' in rest
    assert rest[-2:] == ['--params-file', os.path.realpath(context.workspace.root + '/params.yaml')]


def test_launch_command(ctx):
    context, _ = ctx
    spec = TargetSpec(id='l1', kind='launch', package='pkg_a', launch_file='demo.launch.py',
                      args=['use_sim:=true', 'robot:=$(echo hi)'])
    argv = target_command(spec, context)
    assert argv[1:] == ['launch', 'pkg_a', 'demo.launch.py', 'robot:=$(echo hi)',
                        'use_sim:=true']


@pytest.mark.parametrize('kw,code', [
    ({'package': 'pkg_a; rm -rf /'}, 'invalid_package'),
    ({'package': 'missing_pkg'}, 'unknown_package'),
    ({'executable': '../../bin/sh'}, 'invalid_executable'),
    ({'executable': '-h'}, 'invalid_executable'),
    ({'executable': 'other'}, 'unknown_executable'),
    ({'args': ['--ros-args', '-r', '__node:=x']}, 'invalid_arg'),
    ({'args': ['--']}, 'invalid_arg'),
    ({'args': ['--params-file', '/etc/passwd']}, 'invalid_arg'),
    ({'args': ['--prefix=gdb']}, 'invalid_arg'),
    ({'args': ['__node:=evil']}, 'invalid_arg'),
    ({'args': ['line\nbreak']}, 'invalid_value'),
    ({'params': {'a;b': 1}}, 'invalid_param'),
    ({'params': {'--ros-args': 1}}, 'invalid_param'),
    ({'params': {'x': 'a\x00b'}}, 'invalid_value'),
    ({'remaps': {'__node': 'evil'}}, 'invalid_remap'),
    ({'remaps': {'in': 'bad name!'}}, 'invalid_remap'),
    ({'remaps': {'in:=x': 'y'}}, 'invalid_remap'),
    ({'name': 'bad/name'}, 'invalid_name'),
    ({'name': '$(whoami)'}, 'invalid_name'),
    ({'namespace': '/bad ns'}, 'invalid_namespace'),
    ({'params_file': '../outside.yaml'}, 'forbidden_path'),
    ({'params_file': '/etc/passwd'}, 'forbidden_path'),
])
def test_run_rejects(ctx, kw, code):
    context, _ = ctx
    with pytest.raises(LauncherError) as err:
        target_command(run_spec(**kw), context)
    assert err.value.code == code


def test_params_file_symlink_escape_rejected(ctx):
    context, outside = ctx
    link = os.path.join(context.workspace.root, 'link.yaml')
    os.symlink(outside, link)
    with pytest.raises(LauncherError) as err:
        target_command(run_spec(params_file='link.yaml'), context)
    assert err.value.code == 'forbidden_path'


@pytest.mark.parametrize('args,code', [
    (['--launch-prefix=gdb'], 'invalid_arg'),     # no name:=value
    (['-d'], 'invalid_arg'),
    (['bad-name:=1'], 'invalid_arg'),
    (['x:=a\nb'], 'invalid_value'),
])
def test_launch_rejects(ctx, args, code):
    context, _ = ctx
    spec = TargetSpec(id='l1', kind='launch', package='pkg_a', launch_file='demo.launch.py',
                      args=args)
    with pytest.raises(LauncherError) as err:
        target_command(spec, context)
    assert err.value.code == code


def test_launch_file_must_exist(ctx):
    context, _ = ctx
    for name, code in (('nope.launch.py', 'unknown_launch_file'),
                       ('../x.launch.py', 'invalid_launch_file'),
                       ('script.sh', 'invalid_launch_file')):
        with pytest.raises(LauncherError) as err:
            target_command(TargetSpec(id='l1', kind='launch', package='pkg_a',
                                      launch_file=name), context)
        assert err.value.code == code


@pytest.mark.parametrize('kw', [
    {'kind': 'run', 'executable': None},
    {'kind': 'launch', 'executable': None},
    {'kind': 'launch', 'launch_file': 'a.launch.py', 'name': 'x', 'executable': None},
    {'id': 'Bad ID'},
    {'unknown': 1},
])
def test_schema_rejects(kw):
    base = {'id': 't1', 'kind': 'run', 'package': 'p', 'executable': 'e'}
    with pytest.raises(ValueError):
        TargetSpec(**{**base, **kw})


def test_contained_dir(tmp_path):
    assert validate.contained_dir('out/dummies', str(tmp_path)) == str(tmp_path / 'out/dummies')
    for bad in ('../x', '/etc', 'a/../../x'):
        with pytest.raises(LauncherError):
            validate.contained_dir(bad, str(tmp_path))
