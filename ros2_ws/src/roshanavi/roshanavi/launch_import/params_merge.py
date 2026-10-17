"""Resolve a launch Node's parameters into one set of values (pure, server side).

Sources come from the evaluation child in launch order: global parameters
(``SetParameter`` / ``SetParametersFromFile``) first, then the node's own dicts,
``Parameter`` entries and parameter files. Later sources win, as in launch_ros.
Parameter files follow the rcl YAML rules: ``<node path>: ros__parameters:``
where the path may be nested, absolute or use ``*`` / ``**`` wildcards;
wildcard entries are applied before entries naming the node.

The result is split into scalars (``TargetSpec.params``, editable in the UI)
and everything else (lists, odd names), which goes into a parameter file.
"""

import re
from typing import Any, Dict, Iterator, List, Mapping, Optional, Sequence, Tuple

from ..launcher import validate

ROS_PARAMETERS = 'ros__parameters'
MAX_STRING = 4096


def flatten(values: Mapping[str, Any], prefix: str = '') -> Dict[str, Any]:
    """``{'a': {'b': 1}}`` -> ``{'a.b': 1}`` (dict order kept)."""
    result: Dict[str, Any] = {}
    for key, value in values.items():
        name = f'{prefix}.{key}' if prefix else str(key)
        if isinstance(value, Mapping):
            result.update(flatten(value, name))
        else:
            result[name] = value
    return result


def unflatten(values: Mapping[str, Any]) -> Dict[str, Any]:
    """``{'a.b': 1}`` -> ``{'a': {'b': 1}}`` (for writing a parameter file)."""
    result: Dict[str, Any] = {}
    for name, value in values.items():
        parts = name.split('.')
        cursor = result
        for part in parts[:-1]:
            nested = cursor.get(part)
            if not isinstance(nested, dict):
                nested = cursor[part] = {}
            cursor = nested
        cursor[parts[-1]] = value
    return result


def iter_entries(content: Any, prefix: str = '') -> Iterator[Tuple[str, Mapping[str, Any]]]:
    """``(node path, ros__parameters)`` pairs of an rcl parameter file."""
    if not isinstance(content, Mapping):
        return
    for key, value in content.items():
        if key == ROS_PARAMETERS and isinstance(value, Mapping):
            yield (prefix or '/'), value
        elif isinstance(value, Mapping):
            yield from iter_entries(value, f"{prefix}/{str(key).strip('/')}")


def _pattern(path: str) -> 're.Pattern[str]':
    parts = []
    for segment in path.strip('/').split('/'):
        if segment == '**':
            parts.append('(?:/[^/]+)*')
        else:
            parts.append('/' + re.escape(segment).replace(r'\*', '[^/]*'))
    return re.compile(''.join(parts))


def is_wildcard(path: str) -> bool:
    return '*' in path


def matches(path: str, fq_name: Optional[str]) -> bool:
    """Does the parameter-file node path apply to ``fq_name``?

    Without a known node name only pure ``/**`` entries can be applied.
    """
    if fq_name is None:
        return all(seg == '**' for seg in path.strip('/').split('/'))
    return bool(_pattern(path).fullmatch(fq_name))


def file_values(content: Any, fq_name: Optional[str]) -> Dict[str, Any]:
    entries = [(p, v) for p, v in iter_entries(content) if matches(p, fq_name)]
    entries.sort(key=lambda e: not is_wildcard(e[0]))  # stable: wildcards first
    result: Dict[str, Any] = {}
    for _path, values in entries:
        result.update(flatten(values))
    return result


def merge_sources(sources: Sequence[Mapping[str, Any]], fq_name: Optional[str]
                  ) -> Tuple[Dict[str, Any], List[str], List[Dict[str, str]]]:
    """(merged values, parameter file paths, problems) in launch order."""
    merged: Dict[str, Any] = {}
    files: List[str] = []
    problems: List[Dict[str, str]] = []
    for source in sources:
        kind = source.get('kind')
        if kind == 'dict':
            merged.update(flatten(source.get('values') or {}))
        elif kind == 'param':
            merged[str(source.get('name'))] = source.get('value')
        elif kind == 'file':
            files.append(str(source.get('path')))
            if source.get('error'):
                problems.append({'code': 'param_file_unreadable', 'detail':
                                 f"{source.get('path')}: {source['error']}"})
            else:
                merged.update(file_values(source.get('content'), fq_name))
    return merged, files, problems


def is_scalar_param(name: str, value: Any) -> bool:
    if not validate.PARAM_NAME_RE.match(name):
        return False
    if isinstance(value, str):
        return len(value) <= MAX_STRING and not validate.CONTROL_RE.search(value)
    return isinstance(value, (bool, int, float))


def split_params(merged: Mapping[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(scalars for ``TargetSpec.params``, the rest for a generated parameter file)."""
    scalars, rest = {}, {}
    for name, value in merged.items():
        if value is None:
            continue
        if is_scalar_param(name, value):
            scalars[name] = value
        else:
            rest[name] = value
    return scalars, rest
