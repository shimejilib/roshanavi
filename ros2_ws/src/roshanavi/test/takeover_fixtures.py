"""A fake installed package ``tk_demo`` with launch files for the launch takeover tests."""

from pathlib import Path

from ws_fixtures import fake_prefix

PACKAGE = 'tk_demo'

# Every launch behaviour per-node takeover cannot keep, plus what it carries over.
FULL_PY = '''
import os
from launch import LaunchDescription
from launch.actions import (DeclareLaunchArgument, EmitEvent, ExecuteProcess,
                            IncludeLaunchDescription, LogInfo, RegisterEventHandler,
                            SetEnvironmentVariable, Shutdown, TimerAction)
from launch.conditions import IfCondition
from launch.event_handlers import OnProcessExit
from launch.launch_description_sources import PythonLaunchDescriptionSource
from launch.substitutions import LaunchConfiguration, PathJoinSubstitution, ThisLaunchFileDir
from launch_ros.actions import Node


def generate_launch_description():
    here = ThisLaunchFileDir()
    listener = Node(package='demo_nodes_cpp', executable='listener', name='tk_listener',
                    on_exit=Shutdown())
    return LaunchDescription([
        DeclareLaunchArgument('rate', default_value='5'),
        DeclareLaunchArgument('with_extra', default_value='true'),
        SetEnvironmentVariable('TK_COLOR', 'blue'),
        Node(package='demo_nodes_cpp', executable='talker', name='tk_talker', respawn=True,
             respawn_delay=2.0,
             parameters=[{'rate': LaunchConfiguration('rate')},
                         PathJoinSubstitution([here, 'tk_params.yaml'])],
             additional_env={'TK_SHAPE': 'square'}),
        listener,
        IncludeLaunchDescription(
            PythonLaunchDescriptionSource(PathJoinSubstitution([here, 'tk_sub.launch.py']))),
        Node(package='demo_nodes_cpp', executable='talker', name='tk_extra',
             condition=IfCondition(LaunchConfiguration('with_extra'))),
        TimerAction(period=0.5, actions=[
            Node(package='demo_nodes_cpp', executable='listener', name='tk_late')]),
        RegisterEventHandler(OnProcessExit(target_action=listener,
                                           on_exit=[LogInfo(msg='listener ended')])),
        ExecuteProcess(cmd=['sleep', '600'], name='tk_sleeper'),
    ])
'''

SUB_PY = '''
from launch import LaunchDescription
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        Node(package='demo_nodes_cpp', executable='talker', name='tk_inner'),
    ])
'''

PARAMS_YAML = '''
/tk_talker:
  ros__parameters:
    gains: [1.0, 2.0]
    label: "from file"
'''

# Only plain nodes: per-node takeover without a remainder target.
SIMPLE_PY = '''
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    return LaunchDescription([
        DeclareLaunchArgument('topic', default_value='tk_chatter'),
        Node(package='demo_nodes_cpp', executable='talker', name='tk_a',
             remappings=[('chatter', LaunchConfiguration('topic'))]),
        Node(package='demo_nodes_cpp', executable='listener', name='tk_b',
             remappings=[('chatter', LaunchConfiguration('topic'))]),
    ])
'''

# Whole mode must keep event handlers: the sleeper ends after 1 s and shuts the launch down.
EXIT_PY = '''
from launch import LaunchDescription
from launch.actions import EmitEvent, ExecuteProcess, RegisterEventHandler
from launch.event_handlers import OnProcessExit
from launch.events import Shutdown
from launch_ros.actions import Node


def generate_launch_description():
    sleeper = ExecuteProcess(cmd=['sleep', '1.5'], name='tk_short')
    return LaunchDescription([
        Node(package='demo_nodes_cpp', executable='talker', name='tk_whole_talker'),
        sleeper,
        RegisterEventHandler(OnProcessExit(target_action=sleeper,
                                           on_exit=[EmitEvent(event=Shutdown())])),
    ])
'''

FILES = {'tk_full.launch.py': FULL_PY, 'tk_sub.launch.py': SUB_PY,
         'tk_params.yaml': PARAMS_YAML, 'tk_simple.launch.py': SIMPLE_PY,
         'tk_exit.launch.py': EXIT_PY}


def make_workspace(root: Path) -> Path:
    """``<root>/install/tk_demo`` (isolated layout) with the launch files; returns launch dir."""
    prefix = fake_prefix(root / 'install' / PACKAGE, PACKAGE)
    launch = prefix / 'share' / PACKAGE / 'launch'
    for name, text in FILES.items():
        (launch / name).write_text(text)
    return launch
