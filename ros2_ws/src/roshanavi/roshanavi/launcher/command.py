"""Turn validated specs into argv lists (never a shell string).

Every value is checked against the workspace discovery and the strict rules
in :mod:`.validate`. ROS options are emitted only by this module, each user
value as its own argv item, after ``--ros-args``.
"""

import shlex
import shutil
from dataclasses import dataclass
from typing import Any, List, Optional, Sequence

from . import validate
from .discovery import Workspace
from .errors import LauncherError
from .schema import ClassSpec, DummySpec, FunctionSpec, TargetSpec, TransformSpec, param_text

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
        validate.env_vars(spec.env)
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


def _absolute_topic(topic: str) -> None:
    validate.ros_name('topic', topic)
    if not topic.startswith('/'):
        raise LauncherError('invalid_topic', f'topic must be absolute (start with /): {topic}')


def validate_transform(spec: TransformSpec) -> None:
    validate.target_id(spec.id)
    validate.node_name(spec.name)
    validate.namespace(spec.namespace)
    for inp in spec.inputs:
        _absolute_topic(inp.topic)
    _absolute_topic(spec.output.topic)
    if spec.output.topic in {inp.topic for inp in spec.inputs}:
        raise LauncherError('invalid_topic', f'output topic {spec.output.topic} is also an '
                            'input (the node would receive its own output)')


def validate_function(spec: FunctionSpec, workspace_root: Any) -> None:
    """Names / topics like a transform, and the module must resolve (``workspace_root``: the
    workspace root or the CodeLocations of the project, docs/design/user-code.md)."""
    from ..function.modules import resolve_module  # the launcher does not need it otherwise
    validate.target_id(spec.id)
    validate.node_name(spec.name)
    validate.namespace(spec.namespace)
    # An empty topic is a port that is not wired yet (map wiring, docs/design/wiring.md).
    for inp in spec.inputs:
        if inp.topic:
            _absolute_topic(inp.topic)
    if spec.output.topic:
        _absolute_topic(spec.output.topic)
        if spec.output.topic in {inp.topic for inp in spec.inputs}:
            raise LauncherError('invalid_topic', f'output topic {spec.output.topic} is also an '
                                'input (the node would receive its own output)')
    resolve_module(workspace_root, spec.module)


def validate_class(spec: ClassSpec, workspace_root: Any) -> None:
    """Names / topics like a function node, and the module must resolve inside the workspace."""
    from ..function.modules import resolve_module
    validate.target_id(spec.id)
    validate.node_name(spec.name)
    validate.namespace(spec.namespace)
    for method in spec.methods:
        for port in [*method.inputs, *method.outputs]:
            if port.topic:  # empty: not wired yet
                _absolute_topic(port.topic)
    resolve_module(workspace_root, spec.module)


def class_command(spec: ClassSpec, config_path: str, workspace_root: Any,
                  python: Optional[str] = None) -> List[str]:
    validate_class(spec, workspace_root)
    return node_command('function', spec.name, spec.namespace, config_path, python)


def function_command(spec: FunctionSpec, config_path: str, workspace_root: Any,
                     python: Optional[str] = None) -> List[str]:
    validate_function(spec, workspace_root)
    return node_command('function', spec.name, spec.namespace, config_path, python)


def node_command(executable: str, name: str, namespace: str, config_path: str,
                 python: Optional[str] = None) -> List[str]:
    """``ros2 run roshanavi <executable>``; ``python`` (a venv's interpreter, chosen by the server,
    never by the client) runs the entry script through ``ros2 run --prefix``."""
    args = ['-r', f'__node:={name}']
    ns = validate.namespace(namespace)
    if ns:
        args += ['-r', f'__ns:={ns}']
    prefix = ['--prefix', shlex.quote(python)] if python else []
    return [ros2_binary(), 'run', *prefix, 'roshanavi', executable, '--config', config_path,
            '--ros-args', *args]


def transform_command(spec: TransformSpec, config_path: str) -> List[str]:
    validate_transform(spec)
    return node_command('transform', spec.name, spec.namespace, config_path)


def dummy_command(spec: DummySpec, config_path: str) -> List[str]:
    validate_dummy(spec)
    args = ['-r', f'__node:={spec.name}']
    namespace = validate.namespace(spec.namespace)
    if namespace:
        args += ['-r', f'__ns:={namespace}']
    return [ros2_binary(), 'run', 'roshanavi', 'dummy', '--config', config_path,
            '--ros-args', *args]
