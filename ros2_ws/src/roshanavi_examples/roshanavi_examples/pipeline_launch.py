"""Launch description of a generated relay pipeline: one process per node or composable containers.

Reads the spec JSON written by ``scripts/gen_pipeline.py`` (format: docs/design/nodes.md) and
builds either a ``Node`` per pipeline node (mode ``process``) or ``ComposableNodeContainer``
actions holding every pipeline node as a composable node (mode ``container``). Used by the
installed ``launch/pipeline.launch.py`` and by the ``pipeline.launch.py`` next to a generated spec.

Launch arguments (all optional, they override the defaults stored in the spec):
  spec            path of the spec JSON (only the installed launch file needs it)
  mode            process | container
  containers      number of containers (container mode)
  container_type  st = component_container (single-threaded), mt = component_container_mt
  intra_process   true | false: use_intra_process_comms of the composable nodes
"""

import json
from typing import Any, Dict, List, Mapping

from launch import LaunchContext, LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import ComposableNodeContainer, Node
from launch_ros.descriptions import ComposableNode

from .pipeline_gen import (CONTAINER_TYPES, EXECUTABLES, MODES, PACKAGE, PLUGINS, PipelineNode,
                           assign_containers, container_name)

CONTAINER_EXECUTABLES = {'st': 'component_container', 'mt': 'component_container_mt'}


def load_spec(path: str) -> Dict[str, Any]:
    with open(path, encoding='utf-8') as fh:
        spec = json.load(fh)
    if spec.get('version') != 1 or not spec.get('nodes'):
        raise ValueError(f'{path} is not a pipeline spec (version 1 with nodes)')
    return spec


def _truthy(value: str) -> bool:
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _process_actions(spec: Mapping[str, Any]) -> List[Node]:
    return [Node(package=PACKAGE, executable=EXECUTABLES[n['kind']], name=n['name'],
                 parameters=[dict(n['params'])] if n['params'] else [],
                 remappings=list(n['remaps'].items()), output='screen')
            for n in spec['nodes']]


def _composable(node: Mapping[str, Any], intra_process: bool) -> ComposableNode:
    return ComposableNode(
        package=PACKAGE, plugin=PLUGINS[node['kind']], name=node['name'],
        parameters=[dict(node['params'])] if node['params'] else [],
        remappings=list(node['remaps'].items()),
        extra_arguments=[{'use_intra_process_comms': intra_process}])


def _container_actions(spec: Mapping[str, Any], count: int, container_type: str,
                       intra_process: bool) -> List[ComposableNodeContainer]:
    if container_type not in CONTAINER_TYPES:
        raise ValueError(f'container_type must be one of {CONTAINER_TYPES}')
    nodes = [PipelineNode(n['name'], n['kind'], n['stage'], n['lane'], n['params'], (), ())
             for n in spec['nodes']]
    by_name = {n['name']: n for n in spec['nodes']}
    groups = assign_containers(nodes, count)
    return [ComposableNodeContainer(
        name=container_name(i, len(groups)), namespace='', package='rclcpp_components',
        executable=CONTAINER_EXECUTABLES[container_type],
        composable_node_descriptions=[_composable(by_name[n.name], intra_process) for n in group],
        output='screen')
        for i, group in enumerate(groups)]


def build_actions(spec: Mapping[str, Any], mode: str, containers: int, container_type: str,
                  intra_process: bool) -> List[Any]:
    if mode not in MODES:
        raise ValueError(f'mode must be one of {MODES}, not {mode!r}')
    if mode == 'process':
        return list(_process_actions(spec))
    return list(_container_actions(spec, containers, container_type, intra_process))


def launch_description(spec_path: str = '') -> LaunchDescription:
    """The launch description; ``spec_path`` empty = the ``spec`` launch argument."""
    def setup(context: LaunchContext) -> List[Any]:
        path = spec_path or LaunchConfiguration('spec').perform(context)
        spec = load_spec(path)
        mode = LaunchConfiguration('mode').perform(context) or spec['launch']['mode']
        count = LaunchConfiguration('containers').perform(context)
        ctype = LaunchConfiguration('container_type').perform(context)
        intra = LaunchConfiguration('intra_process').perform(context)
        return build_actions(
            spec, mode, int(count) if count else int(spec['launch']['containers']),
            ctype or spec['launch']['container_type'],
            _truthy(intra) if intra else bool(spec['launch']['intra_process']))

    arguments = [DeclareLaunchArgument('mode', default_value='',
                                       description='process | container (default: from the spec)'),
                 DeclareLaunchArgument('containers', default_value='',
                                       description='number of containers'),
                 DeclareLaunchArgument('container_type', default_value='',
                                       description='st | mt'),
                 DeclareLaunchArgument('intra_process', default_value='',
                                       description='true | false')]
    if not spec_path:
        arguments.insert(0, DeclareLaunchArgument('spec', description='path of the pipeline JSON'))
    return LaunchDescription([*arguments, OpaqueFunction(function=setup)])
