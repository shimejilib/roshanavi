"""Start image_filter: Image -> grayscale + edges.

    ros2 launch roshanavi_examples image_filter.launch.py image:=/camera/image keep_stamp:=false
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    args = [
        DeclareLaunchArgument('image', default_value='/camera/image', description='input Image topic'),
        DeclareLaunchArgument('gray', default_value='/camera/gray', description='grayscale output'),
        DeclareLaunchArgument('edges', default_value='/camera/edges', description='edges output'),
        DeclareLaunchArgument('keep_stamp', default_value='true',
                              description='true: copy the input stamp; false: stamp with now'),
        DeclareLaunchArgument('process_delay_ms', default_value='0',
                              description='simulated processing time per image (ms)'),
    ]
    node = Node(
        package='roshanavi_examples', executable='image_filter', name='image_filter',
        output='screen',
        parameters=[{
            'keep_stamp': ParameterValue(LaunchConfiguration('keep_stamp'), value_type=bool),
            'process_delay_ms': ParameterValue(LaunchConfiguration('process_delay_ms'),
                                               value_type=int),
        }],
        remappings=[('image', LaunchConfiguration('image')),
                    ('image_gray', LaunchConfiguration('gray')),
                    ('image_edges', LaunchConfiguration('edges'))],
    )
    return LaunchDescription([*args, node])
