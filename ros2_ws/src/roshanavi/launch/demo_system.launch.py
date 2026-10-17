"""Demo "existing system" for the launch decomposition import (roshanavi docs/design/launcher.md).

Node 一覧 → 「launch ファイルから取り込む」 で roshanavi / demo_system.launch.py を選ぶと、
talker と listener がノードごとの起動設定 (名前空間・リマップ・パラメータ込み) として
取り込まれます。最後の ExecuteProcess は「分解できない部分」の例です。

    ros2 launch roshanavi demo_system.launch.py robot:=demo_robot use_listener:=true
"""

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, ExecuteProcess, GroupAction
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node, PushRosNamespace

TOPIC = '/imported/chatter'


def generate_launch_description() -> LaunchDescription:
    return LaunchDescription([
        DeclareLaunchArgument('robot', default_value='demo_robot',
                              description='namespace of the demo nodes'),
        DeclareLaunchArgument('use_listener', default_value='true',
                              description='also start the listener'),
        GroupAction([
            PushRosNamespace(LaunchConfiguration('robot')),
            Node(package='demo_nodes_cpp', executable='talker', name='imported_talker',
                 parameters=[{'note': 'from demo_system.launch.py'}],
                 remappings=[('chatter', TOPIC)]),
            Node(package='demo_nodes_cpp', executable='listener', name='imported_listener',
                 remappings=[('chatter', TOPIC)],
                 condition=IfCondition(LaunchConfiguration('use_listener'))),
        ]),
        ExecuteProcess(cmd=['ros2', 'topic', 'echo', '--once', TOPIC], output='screen'),
    ])
