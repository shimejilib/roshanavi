"""Child-process side: turn evaluated launch entities into plain JSON-able dicts.

Reads launch_ros ``Node`` settings (package, executable, name, namespace,
parameters, remappings, arguments) by performing their substitutions in the
walker's ``LaunchContext`` -- the same steps ``Node.execute`` takes, but
without building a command line or starting anything. launch_ros keeps these
settings in name-mangled attributes; they are read defensively.
"""

import os
import pathlib
from typing import Any, Dict, List, Optional

import yaml
from launch.utilities import normalize_to_list_of_substitutions, perform_substitutions
from launch_ros.descriptions import Parameter as ParameterDescription
from launch_ros.utilities import evaluate_parameters, make_namespace_absolute, prefix_namespace

MAX_PARAM_FILE_BYTES = 1024 * 1024


def subst(context: Any, value: Any) -> Optional[str]:
    if value is None:
        return None
    return perform_substitutions(context, normalize_to_list_of_substitutions(value))


def _private(obj: Any, cls_name: str, attr: str, default: Any = None) -> Any:
    return getattr(obj, f'_{cls_name}__{attr}', default)


def yaml_value(text: Any) -> Any:
    """A ``-p name:=value`` style string as rcl would type it (YAML scalar)."""
    if not isinstance(text, str):
        return text
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return text


def file_source(path: str, is_global: bool = False) -> Dict[str, Any]:
    """A parameter file's YAML (size-limited) so the server never reads paths itself."""
    source: Dict[str, Any] = {'kind': 'file', 'path': os.path.abspath(path),
                              'global': is_global}
    try:
        if os.path.getsize(path) > MAX_PARAM_FILE_BYTES:
            return {**source, 'error': 'the parameter file is larger than 1 MB'}
        with open(path, encoding='utf-8') as handle:
            source['content'] = yaml.safe_load(handle)
    except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
        source['error'] = f'{type(exc).__name__}: {exc}'
    return source


def _global_params(context: Any) -> List[Dict[str, Any]]:
    sources = []
    for item in context.launch_configurations.get('global_params', None) or []:
        if isinstance(item, tuple):
            sources.append({'kind': 'param', 'name': str(item[0]),
                            'value': yaml_value(item[1]), 'global': True})
        else:
            sources.append(file_source(str(item), is_global=True))
    return sources


def param_sources(node: Any, context: Any) -> List[Dict[str, Any]]:
    """Global (SetParameter / SetParametersFromFile) first, then the node's own, in order."""
    sources = _global_params(context)
    raw = _private(node, 'Node', 'parameters') or []
    if not raw:
        return sources
    for item in evaluate_parameters(context, raw):
        if isinstance(item, dict):
            sources.append({'kind': 'dict', 'values': item})
        elif isinstance(item, pathlib.Path):
            sources.append(file_source(str(item)))
        elif isinstance(item, ParameterDescription):
            name, value = item.evaluate(context)
            sources.append({'kind': 'param', 'name': name, 'value': value})
    return sources


def _has_prefix(description: Any, context: Any) -> bool:
    prefix = getattr(description, 'prefix', None)
    try:
        return bool(prefix) and bool((subst(context, prefix) or '').strip())
    except Exception:  # unresolved prefix substitution: treat as set
        return True


def _process_warnings(node: Any, context: Any) -> List[str]:
    warnings = []
    description = getattr(node, 'process_description', None)
    if description is not None:
        if getattr(description, 'env', None) or getattr(description, 'additional_env', None):
            warnings.append('env_not_imported')
        if _has_prefix(description, context):
            warnings.append('prefix_ignored')
    if _private(node, 'Node', 'ros_arguments'):
        warnings.append('ros_arguments_ignored')
    return warnings


def extract_node(node: Any, context: Any, lifecycle: bool) -> Dict[str, Any]:
    """Everything needed to start this Node on its own with ``ros2 run``."""
    raw_name = _private(node, 'Node', 'node_name')
    raw_ns = _private(node, 'Node', 'node_namespace')
    namespace = make_namespace_absolute(prefix_namespace(
        context.launch_configurations.get('ros_namespace', None), subst(context, raw_ns)))
    remaps = [list(pair) for pair in context.launch_configurations.get('ros_remaps', None) or []]
    remaps += [[subst(context, src), subst(context, dst)]
               for src, dst in _private(node, 'Node', 'remappings') or []]
    return {
        'package': subst(context, node.node_package),
        'executable': subst(context, node.node_executable),
        'name': subst(context, raw_name),
        'namespace': namespace if namespace not in (None, '/') else None,
        'remaps': remaps,
        'args': [subst(context, a) for a in _private(node, 'Node', 'arguments') or []],
        'param_sources': param_sources(node, context),
        'lifecycle': lifecycle,
        'file': current_file(context),
        'warnings': _process_warnings(node, context),
    }


def current_file(context: Any) -> Optional[str]:
    try:
        return context.get_locals_as_dict().get('current_launch_file_path')
    except (AttributeError, KeyError):
        return None


def describe(entity: Any, context: Any) -> str:
    """Short human-readable description of an entity for the preview."""
    name = type(entity).__name__
    try:
        if hasattr(entity, 'node_package') and hasattr(entity, 'node_executable'):
            node_name = subst(context, _private(entity, 'Node', 'node_name'))
            text = f'{name} {subst(context, entity.node_package)}/' \
                   f'{subst(context, entity.node_executable)}'
            return f'{text} ({node_name})' if node_name else text
        cmd = getattr(entity, 'cmd', None)
        if cmd:
            return f"{name}: {' '.join(subst(context, part) or '' for part in cmd)}"
    except Exception:  # best effort only: unresolved substitutions keep the class name
        return name
    return name


def container_nodes(entity: Any, context: Any) -> List[str]:
    """``package/plugin (name)`` of the composable nodes declared in a container / loader."""
    descriptions = (_private(entity, 'ComposableNodeContainer', 'composable_node_descriptions')
                    or _private(entity, 'LoadComposableNodes', 'composable_node_descriptions')
                    or [])
    result = []
    for desc in descriptions:
        try:
            text = f'{subst(context, desc.package)}/{subst(context, desc.node_plugin)}'
            node_name = subst(context, desc.node_name)
            result.append(f'{text} ({node_name})' if node_name else text)
        except Exception:  # unresolved substitution: keep going, the entity is reported anyway
            result.append('?')
    return result
