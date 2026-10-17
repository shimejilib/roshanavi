"""Turn validated specs into argv lists (never a shell string).

Every value is checked against the workspace discovery and the strict rules
in :mod:`.validate`. ROS options are emitted only by this module, each user
value as its own argv item, after ``--ros-args``.
"""

import shutil
from dataclasses import dataclass
from typing import List, Sequence

from . import validate
from .discovery import Workspace
from .errors import LauncherError
from .schema import DummySpec, TargetSpec, param_text

PARAMS_FILE_EXTS = ('.yaml', '.yml')


@dataclass(frozen=True)
class CommandContext:
    workspace: Workspace
    allowed_roots: Sequence[str]  # params files must live under one of these


def ros2_binary() -> str:
    path = shutil.which('ros2')
    if path is None:
        raise LauncherError('ros2_not_found', 'the ros2 command is not on PATH '
                            '(is ROS 2 sourced?)', 500)
    return path


def _ros_args(spec: TargetSpec, ctx: CommandContext) -> List[str]:
    args: List[str] = []
    name = validate.node_name(spec.name)
    namespace = validate.namespace(spec.namespace)
    if name:
        args += ['-r', f'__node:={name}']
    if namespace:
        args += ['-r', f'__ns:={namespace}']
    for key, value in validate.params({k: param_text(v) for k, v in spec.params.items()}):
        args += ['-p', f'{key}:={value}']
    for src, dst in validate.remaps(spec.remaps):
        args += ['-r', f'{src}:={dst}']
    if spec.params_file:
        path = validate.contained_file(spec.params_file, ctx.allowed_roots, PARAMS_FILE_EXTS)
        args += ['--params-file', path]
    return ['--ros-args', *args] if args else []


def launch_arg_items(items: Sequence[str]) -> List[str]:
    pairs = {}
    for item in items:
        name, sep, value = item.partition(':=')
        if not sep:
            raise LauncherError('invalid_arg', f'launch argument {item!r} must look like '
                                'name:=value')
        pairs[name] = value
    return [f'{k}:={v}' for k, v in validate.launch_args(pairs)]


def target_command(spec: TargetSpec, ctx: CommandContext) -> List[str]:
    validate.target_id(spec.id)
    ros2 = ros2_binary()
    if spec.kind == 'run':
        ctx.workspace.require_executable(spec.package, spec.executable)
        return [ros2, 'run', spec.package, spec.executable, *validate.run_args(spec.args),
                *_ros_args(spec, ctx)]
    ctx.workspace.require_launch_file(spec.package, spec.launch_file)
    return [ros2, 'launch', spec.package, spec.launch_file, *launch_arg_items(spec.args)]


def validate_dummy(spec: DummySpec) -> None:
    validate.target_id(spec.id)
    validate.node_name(spec.name)
    validate.namespace(spec.namespace)
    validate.ros_name('topic', spec.topic)
    if not spec.topic.startswith('/'):
        raise LauncherError('invalid_topic', f'topic must be absolute (start with /): {spec.topic}')


def dummy_command(spec: DummySpec, config_path: str) -> List[str]:
    validate_dummy(spec)
    args = ['-r', f'__node:={spec.name}']
    namespace = validate.namespace(spec.namespace)
    if namespace:
        args += ['-r', f'__ns:={namespace}']
    return [ros2_binary(), 'run', 'roshanavi', 'dummy', '--config', config_path,
            '--ros-args', *args]
