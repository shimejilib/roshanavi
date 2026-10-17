"""Strict validation of every user-supplied launcher value.

Nothing here ever reaches a shell: commands are argv lists. Validation still
matters because ``ros2 run`` / ``ros2 launch`` / rcl interpret some argv items
themselves (``--prefix``, ``--ros-args``, ``--params-file``, ``__node:=`` ...),
so free-form values must not be able to smuggle options in.
"""

import os
import re
from typing import Iterable, List, Mapping, Optional, Sequence, Sized, Tuple

from rclpy.exceptions import (InvalidNamespaceException, InvalidNodeNameException,
                              InvalidTopicNameException)
from rclpy.validate_namespace import validate_namespace
from rclpy.validate_node_name import validate_node_name
from rclpy.validate_topic_name import validate_topic_name

from .errors import LauncherError

PACKAGE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,99}$')
EXECUTABLE_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.+\-]{0,127}$')
LAUNCH_FILE_RE = re.compile(r'^[A-Za-z0-9_][A-Za-z0-9_.\-]{0,127}$')
TARGET_ID_RE = re.compile(r'^[a-z0-9][a-z0-9_\-]{0,63}$')
PARAM_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)*$')
LAUNCH_ARG_NAME_RE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')
CONTROL_RE = re.compile(r'[\x00-\x1f\x7f]')
MAX_VALUE_LEN = 4096
MAX_ITEMS = 64
LAUNCH_EXTS = ('.launch.py', '.launch.xml', '.launch.yaml', '.launch.yml', '_launch.py',
               '_launch.xml', '_launch.yaml')
# argv items that ros2 run / rcl would interpret as options for themselves.
FORBIDDEN_ARGS = ('--ros-args', '--', '-r', '--remap', '-p', '--param', '--params-file',
                  '-e', '--enclave', '--log-level', '--log-config-file', '--prefix')
FORBIDDEN_ARG_PREFIXES = ('--ros-', '--log-', '--enable-', '--disable-', '--prefix=')


def _check_value(field: str, value: str) -> str:
    if not isinstance(value, str):
        raise LauncherError('invalid_value', f'{field}: must be a string')
    if len(value) > MAX_VALUE_LEN:
        raise LauncherError('invalid_value', f'{field}: longer than {MAX_VALUE_LEN} characters')
    if CONTROL_RE.search(value):
        raise LauncherError('invalid_value', f'{field}: control characters are not allowed')
    return value


def _check_count(field: str, items: Sized) -> None:
    if len(items) > MAX_ITEMS:
        raise LauncherError('invalid_value', f'{field}: at most {MAX_ITEMS} entries')



def package_name(name: str) -> str:
    if not isinstance(name, str) or not PACKAGE_RE.match(name):
        raise LauncherError('invalid_package', f'invalid package name: {name!r}')
    return name


def executable_name(name: str) -> str:
    if not isinstance(name, str) or not EXECUTABLE_RE.match(name):
        raise LauncherError('invalid_executable', f'invalid executable name: {name!r}')
    return name


def launch_file_name(name: str) -> str:
    if (not isinstance(name, str) or not LAUNCH_FILE_RE.match(name)
            or not name.endswith(LAUNCH_EXTS) or '..' in name):
        raise LauncherError('invalid_launch_file', f'invalid launch file name: {name!r}')
    return name


def target_id(value: str) -> str:
    if not isinstance(value, str) or not TARGET_ID_RE.match(value):
        raise LauncherError('invalid_id', f'invalid id {value!r}: use a-z, 0-9, "_" and "-"')
    return value


def node_name(name: Optional[str]) -> Optional[str]:
    if name in (None, ''):
        return None
    try:
        validate_node_name(name)
    except (InvalidNodeNameException, TypeError) as exc:
        raise LauncherError('invalid_name', f'invalid node name {name!r}: {exc}') from exc
    return name


def namespace(value: Optional[str]) -> Optional[str]:
    if value in (None, ''):
        return None
    if not value.startswith('/'):
        value = '/' + value
    try:
        validate_namespace(value)
    except (InvalidNamespaceException, TypeError) as exc:
        raise LauncherError('invalid_namespace', f'invalid namespace {value!r}: {exc}') from exc
    return value


def ros_name(field: str, value: str) -> str:
    """A topic-like ROS name for remapping (relative, absolute or ``~``)."""
    if not isinstance(value, str) or not value or value.startswith('__'):
        raise LauncherError('invalid_remap', f'{field}: invalid name {value!r}')
    try:
        validate_topic_name(value)
    except (InvalidTopicNameException, TypeError) as exc:
        raise LauncherError('invalid_remap', f'{field}: invalid name {value!r}: {exc}') from exc
    return value


def params(values: Mapping[str, str]) -> List[Tuple[str, str]]:
    """``{name: value}`` -> sorted pairs; names are dotted identifiers."""
    _check_count('params', list(values))
    result = []
    for name, value in values.items():
        if not isinstance(name, str) or not PARAM_NAME_RE.match(name) or len(name) > 200:
            raise LauncherError('invalid_param', f'invalid parameter name: {name!r}')
        result.append((name, _check_value(f'params.{name}', value)))
    return sorted(result)


def remaps(values: Mapping[str, str]) -> List[Tuple[str, str]]:
    _check_count('remaps', list(values))
    return sorted((ros_name('remaps (from)', src), ros_name('remaps (to)', dst))
                  for src, dst in values.items())


def launch_args(values: Mapping[str, str]) -> List[Tuple[str, str]]:
    _check_count('launch args', list(values))
    result = []
    for name, value in values.items():
        if not isinstance(name, str) or not LAUNCH_ARG_NAME_RE.match(name) or len(name) > 200:
            raise LauncherError('invalid_arg', f'invalid launch argument name: {name!r}')
        result.append((name, _check_value(f'args.{name}', value)))
    return sorted(result)


def run_args(values: Iterable[str]) -> List[str]:
    """Extra argv for the executable itself; must not look like ROS / ros2 options."""
    items = list(values)
    _check_count('args', items)
    for item in items:
        _check_value('args', item)
        if not item or len(item) > 256:
            raise LauncherError('invalid_arg', 'args: empty or too long item')
        lowered = item.lower()
        if lowered in FORBIDDEN_ARGS or lowered.startswith(FORBIDDEN_ARG_PREFIXES):
            raise LauncherError('invalid_arg', f'args: {item!r} is reserved for ROS; use the '
                                'params / remaps / namespace / name fields instead')
        if ':=' in item and '__' in item.split(':=', 1)[0]:
            raise LauncherError('invalid_arg', f'args: {item!r} looks like a ROS special remap')
    return items


def contained_file(user_path: str, roots: Sequence[str], exts: Sequence[str] = ()) -> str:
    """realpath of ``user_path`` if it is an existing file inside one of ``roots``."""
    if not isinstance(user_path, str) or not user_path or CONTROL_RE.search(user_path):
        raise LauncherError('forbidden_path', 'path must be a non-empty string')
    for root in roots:
        real_root = os.path.realpath(root)
        candidate = os.path.realpath(os.path.join(real_root, user_path))
        if os.path.commonpath([real_root, candidate]) == real_root and os.path.isfile(candidate):
            if exts and not candidate.lower().endswith(tuple(exts)):
                raise LauncherError('invalid_file', f'file must end with one of {list(exts)}')
            return candidate
    raise LauncherError('forbidden_path',
                        f'{user_path!r} is not an existing file inside the workspace or data dir')


def contained_dir(user_path: str, root: str) -> str:
    """realpath of directory ``user_path`` (may not exist yet) inside ``root``."""
    if not isinstance(user_path, str) or not user_path or CONTROL_RE.search(user_path):
        raise LauncherError('forbidden_path', 'directory must be a non-empty string')
    real_root = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(real_root, user_path))
    if os.path.commonpath([real_root, candidate]) != real_root:
        raise LauncherError('forbidden_path', f'{user_path!r} is outside the workspace')
    if os.path.exists(candidate) and not os.path.isdir(candidate):
        raise LauncherError('invalid_file', f'{user_path!r} exists and is not a directory')
    return candidate
