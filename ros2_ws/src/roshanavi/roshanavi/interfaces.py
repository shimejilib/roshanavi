"""Interface definitions (``ros2 interface show`` equivalent) from the rosidl files.

``show("std_msgs/msg/Header")`` returns the raw ``.msg`` text and an expanded
form in which every nested message type is followed by its own fields,
indented by one tab per level (comments of nested types are left out to keep
it short). Lookup goes through ``rosidl_runtime_py.get_interface_path``, so only
installed packages' share/ directories are read.
"""

import os
import re
from typing import Any, Dict, List, Optional, Set

from rosidl_runtime_py import get_interface_path

from .api_errors import ApiError

INTERFACE_RE = re.compile(r'^[A-Za-z][A-Za-z0-9_]*/(msg|srv|action)/[A-Z][A-Za-z0-9_]*$')
PRIMITIVES = frozenset({
    'bool', 'byte', 'char', 'float32', 'float64', 'int8', 'uint8', 'int16', 'uint16',
    'int32', 'uint32', 'int64', 'uint64', 'string', 'wstring',
    # ROS 1 style aliases still accepted by rosidl
    'duration', 'time'})
MAX_DEPTH = 6
MAX_LINES = 2000
MAX_FILE_BYTES = 256 * 1024


def check_name(type_name: str) -> str:
    if not INTERFACE_RE.match(type_name):
        raise ApiError('invalid_interface', f'invalid interface name {type_name!r} '
                       '(expected pkg/msg/Name, pkg/srv/Name or pkg/action/Name)')
    return type_name


def read_definition(type_name: str) -> str:
    check_name(type_name)
    try:
        path = get_interface_path(type_name)
    except (LookupError, ValueError) as exc:
        raise ApiError('unknown_interface', f'{type_name} is not installed', 404) from exc
    try:
        if os.path.getsize(path) > MAX_FILE_BYTES:
            raise ApiError('invalid_interface', f'{type_name}: definition file too large')
        with open(path, encoding='utf-8') as fh:
            return fh.read()
    except OSError as exc:
        raise ApiError('unknown_interface', f'cannot read {type_name}: {exc}', 404) from exc


def field_type(line: str) -> Optional[str]:
    """Base type token of a field / constant line, or None for blanks, comments, ``---``."""
    stripped = line.strip()
    if not stripped or stripped.startswith('#') or stripped == '---':
        return None
    token = stripped.split()[0]
    token = re.sub(r'\[[^\]]*\]$', '', token)  # arrays: int32[], int32[3], int32[<=3]
    return re.sub(r'<=\d+$', '', token)        # bounded strings: string<=10


def nested_type(token: str, package: str) -> Optional[str]:
    """Full message type for a non-primitive field type token (None for primitives)."""
    if token in PRIMITIVES:
        return None
    parts = token.split('/')
    if len(parts) == 1:
        return 'std_msgs/msg/Header' if token == 'Header' else f'{package}/msg/{token}'
    if len(parts) == 2:
        return f'{parts[0]}/msg/{parts[1]}'
    return token


def _strip_comment(line: str) -> str:
    # A '#' inside a quoted string constant stays; only real comments are removed.
    in_quote: Optional[str] = None
    for i, ch in enumerate(line):
        if ch in ('"', "'"):
            in_quote = None if in_quote == ch else (in_quote or ch)
        elif ch == '#' and in_quote is None:
            return line[:i].rstrip()
    return line.rstrip()


def _expand(text: str, package: str, depth: int, seen: Set[str], out: List[str],
            keep_comments: bool) -> None:
    indent = '\t' * depth
    for raw in text.splitlines():
        if len(out) >= MAX_LINES:
            return
        line = raw.rstrip() if keep_comments else _strip_comment(raw)
        if not line.strip():
            if keep_comments:
                out.append(indent + line)
            continue
        out.append(indent + line)
        token = field_type(line)
        if token is None or '=' in line.split('#')[0]:
            continue  # comments, separators and constants have no nested fields
        child = nested_type(token, package)
        if child is None or child in seen or depth + 1 > MAX_DEPTH:
            continue
        try:
            child_text = read_definition(child)
        except ApiError:
            out.append(f'{indent}\t# ({child} not found)')
            continue
        _expand(child_text, child.split('/')[0], depth + 1, seen | {child}, out, False)


def show(type_name: str) -> Dict[str, Any]:
    """``{type, text, expanded}`` for one interface."""
    text = read_definition(type_name)
    lines: List[str] = []
    _expand(text, type_name.split('/')[0], 0, {type_name}, lines, True)
    return {'type': type_name, 'text': text, 'expanded': '\n'.join(lines),
            'truncated': len(lines) >= MAX_LINES}
