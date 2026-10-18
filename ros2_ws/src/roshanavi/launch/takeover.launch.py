"""Start roshanavi taking over a launch file, from a bringup (docs/guide).

    ros2 launch roshanavi takeover.launch.py package:=turtle_patrol \\
        launch_file:=patrol.launch.py args:='side_length:=2.0' mine:=patrol

The same as ``ros2 run roshanavi server --launch <package> <launch_file> [args] --mine ...``:
roshanavi starts the launch file's nodes itself, so they can be stopped, restarted and
inspected one by one. ``args`` and ``mine`` are space-separated lists.
"""

import shlex

from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node

ARGS = (('package', None, 'package of the launch file to take over'),
        ('launch_file', None, 'the launch file to take over'),
        ('args', '', 'its launch arguments, space-separated name:=value'),
        ('mine', '', 'nodes you are developing, space-separated'),
        ('mode', 'node', 'node (one target per node) or whole (the launch file as one)'),
        ('host', '127.0.0.1', 'bind address of the web UI'),
        ('port', '6871', 'port of the web UI'),
        ('data_dir', '/data', 'roshanavi data dir'),
        ('extra', '', 'more roshanavi server options, space-separated'))


def _server(context):
    value = {name: LaunchConfiguration(name).perform(context) for name, _, _ in ARGS}
    argv = ['--host', value['host'], '--port', value['port'], '--data-dir', value['data_dir'],
            '--launch-mode', value['mode'],
            '--launch', value['package'], value['launch_file'], *shlex.split(value['args'])]
    for node in shlex.split(value['mine']):
        argv += ['--mine', node]
    argv += shlex.split(value['extra'])
    return [Node(package='roshanavi', executable='server', arguments=argv, output='screen')]


def generate_launch_description():
    declared = [DeclareLaunchArgument(name, default_value=default, description=text)
                if default is not None else DeclareLaunchArgument(name, description=text)
                for name, default, text in ARGS]
    return LaunchDescription([*declared, OpaqueFunction(function=_server)])
