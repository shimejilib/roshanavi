"""Launch files written at test time for the decomposition-import tests."""

import os
from typing import Dict

MAIN_PY = '''
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, ExecuteProcess, GroupAction,
                            IncludeLaunchDescription, LogInfo, TimerAction)
from launch.conditions import IfCondition, UnlessCondition
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, ThisLaunchFileDir
from launch_ros.actions import (ComposableNodeContainer, Node, PushRosNamespace, SetParameter,
                                SetRemap)
from launch_ros.descriptions import ComposableNode


def generate_launch_description():
    here = ThisLaunchFileDir()
    return LaunchDescription([
        DeclareLaunchArgument('robot', default_value='r1'),
        DeclareLaunchArgument('use_listener', default_value='true'),
        DeclareLaunchArgument('rate', description='publish rate'),
        SetParameter(name='use_sim_time', value=False),
        GroupAction([
            PushRosNamespace(LaunchConfiguration('robot')),
            SetRemap(src='chatter', dst='talk'),
            Node(package='demo_nodes_cpp', executable='talker', name='talker',
                 parameters=[{'rate': LaunchConfiguration('rate'), 'nested': {'gain': 1.5},
                              'ids': [1, 2]},
                             PathJoinSubstitution([here, 'params.yaml'])],
                 remappings=[('extra', '/abs_extra')]),
        ]),
        Node(package='demo_nodes_cpp', executable='listener', name='listener',
             condition=IfCondition(LaunchConfiguration('use_listener'))),
        Node(package='demo_nodes_py', executable='listener', name='py_listener',
             condition=UnlessCondition(LaunchConfiguration('use_listener'))),
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([here, 'sub.launch.py'])),
            launch_arguments={'who': 'inner'}.items()),
        IncludeLaunchDescription(PythonLaunchDescriptionSource('/nonexistent/x.launch.py')),
        ComposableNodeContainer(
            name='container', namespace='', package='rclcpp_components',
            executable='component_container',
            composable_node_descriptions=[ComposableNode(
                package='composition', plugin='composition::Talker', name='comp_talker')]),
        ExecuteProcess(cmd=['touch', LaunchConfiguration('marker', default='/tmp/never')]),
        TimerAction(period=1.0, actions=[
            Node(package='demo_nodes_cpp', executable='talker', name='late')]),
        LogInfo(msg='hello'),
    ])
'''

PARAMS_YAML = '''
/**:
  ros__parameters:
    common: 7
/r1/talker:
  ros__parameters:
    from_file: "yes"
    rate: 99
other_node:
  ros__parameters:
    ignored: 1
'''

SUB_PY = '''
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('who'),
        Node(package='demo_nodes_cpp', executable='talker',
             name=[LaunchConfiguration('who'), '_talker']),
    ])
'''

MAIN_XML = '''<launch>
  <arg name="ns" default="xml_ns"/>
  <arg name="with_listener" default="false"/>
  <let name="topic" value="/xml_chatter"/>
  <group>
    <push-ros-namespace namespace="$(var ns)"/>
    <node pkg="demo_nodes_cpp" exec="talker" name="xml_talker">
      <param name="greeting" value="hi"/>
      <param name="count" value="3"/>
      <remap from="chatter" to="$(var topic)"/>
    </node>
  </group>
  <node pkg="demo_nodes_cpp" exec="listener" name="xml_listener" if="$(var with_listener)"/>
  <executable cmd="echo xml" output="screen"/>
</launch>
'''

MAIN_YAML = '''launch:
- arg:
    name: "who"
    default: "yaml"
- node:
    pkg: "demo_nodes_cpp"
    exec: "listener"
    name: "$(var who)_listener"
    namespace: "/yaml_ns"
    param:
    - name: "flag"
      value: true
'''

SLOW_PY = '''
import time
from launch import LaunchDescription


def generate_launch_description():
    time.sleep(60)
    return LaunchDescription([])
'''

BROKEN_PY = 'def generate_launch_description(:\n'

PRINTS_PY = '''
from launch import LaunchDescription
from launch_ros.actions import Node

print('noise on stdout')


def generate_launch_description():
    print('more noise')
    return LaunchDescription([Node(package='demo_nodes_cpp', executable='talker')])
'''

UNKNOWN_PY = '''
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='demo_nodes_cpp', executable='no_such_exe', name='ghost'),
        Node(package='demo_nodes_cpp', executable='listener', name='ok_listener',
             arguments=['--ros-args', '-r', 'x:=y']),
    ])
'''

FILES: Dict[str, str] = {
    'main.launch.py': MAIN_PY, 'params.yaml': PARAMS_YAML, 'sub.launch.py': SUB_PY,
    'main.launch.xml': MAIN_XML, 'main.launch.yaml': MAIN_YAML, 'slow.launch.py': SLOW_PY,
    'broken.launch.py': BROKEN_PY, 'prints.launch.py': PRINTS_PY,
    'unknown.launch.py': UNKNOWN_PY,
}


def write_fixtures(directory: str) -> str:
    os.makedirs(directory, exist_ok=True)
    for name, text in FILES.items():
        with open(os.path.join(directory, name), 'w', encoding='utf-8') as handle:
            handle.write(text)
    return directory
