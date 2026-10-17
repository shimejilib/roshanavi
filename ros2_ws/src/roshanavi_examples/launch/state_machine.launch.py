"""Start state_machine: /cmd (start/stop/fault/reset) -> /state (IDLE/RUNNING/ERROR).

    ros2 launch roshanavi_examples state_machine.launch.py
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    args = [
        DeclareLaunchArgument('cmd', default_value='/cmd', description='command topic'),
        DeclareLaunchArgument('state', default_value='/state', description='state topic'),
    ]
    node = Node(
        package='roshanavi_examples', executable='state_machine', name='state_machine',
        output='screen',
        remappings=[('cmd', LaunchConfiguration('cmd')), ('state', LaunchConfiguration('state'))],
    )
    return LaunchDescription([*args, node])
