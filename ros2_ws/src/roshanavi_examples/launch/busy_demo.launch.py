"""Start the MultiThreadedExecutor busy-loop demo: a 100 Hz driver + executor_busy_demo.

    ros2 launch roshanavi_examples busy_demo.launch.py                              # the problem
    ros2 launch roshanavi_examples busy_demo.launch.py qos_events:=off              # the workaround
    ros2 launch roshanavi_examples busy_demo.launch.py executor:=single             # also fine
    ros2 topic echo /busy_demo/stats

See roshanavi_examples/executor_busy_demo.py for what the numbers mean.
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    args = [
        DeclareLaunchArgument('executor', default_value='multi', description='single or multi'),
        DeclareLaunchArgument('qos_events', default_value='default',
                              description='default (rclpy QoS event handlers) or off'),
        DeclareLaunchArgument('work_ms', default_value='5.0',
                              description='time the callback spends per message (ms)'),
        DeclareLaunchArgument('num_threads', default_value='4',
                              description='worker threads of the multi executor (0 = automatic)'),
        DeclareLaunchArgument('rate_hz', default_value='100.0',
                              description='messages per second from the driver'),
        DeclareLaunchArgument('input_topic', default_value='/busy_demo/in'),
        DeclareLaunchArgument('stats_topic', default_value='/busy_demo/stats'),
    ]
    driver = Node(
        package='roshanavi_examples', executable='busy_demo_driver', name='busy_demo_driver',
        output='screen',
        parameters=[{
            'rate_hz': ParameterValue(LaunchConfiguration('rate_hz'), value_type=float),
            'topic': LaunchConfiguration('input_topic'),
        }],
    )
    demo = Node(
        package='roshanavi_examples', executable='executor_busy_demo', name='executor_busy_demo',
        output='screen',
        parameters=[{
            # value_type=str: otherwise launch parses the text as YAML and `off` becomes False
            'executor': ParameterValue(LaunchConfiguration('executor'), value_type=str),
            'qos_events': ParameterValue(LaunchConfiguration('qos_events'), value_type=str),
            'work_ms': ParameterValue(LaunchConfiguration('work_ms'), value_type=float),
            'num_threads': ParameterValue(LaunchConfiguration('num_threads'), value_type=int),
            'input_topic': LaunchConfiguration('input_topic'),
            'stats_topic': LaunchConfiguration('stats_topic'),
        }],
    )
    return LaunchDescription([*args, driver, demo])
