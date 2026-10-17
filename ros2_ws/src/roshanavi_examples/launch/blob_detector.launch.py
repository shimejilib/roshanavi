"""Start blob_detector: Image -> vision_msgs/Detection2DArray of bright blobs.

    ros2 launch roshanavi_examples blob_detector.launch.py image:=/camera/gray threshold:=180
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    args = [
        DeclareLaunchArgument('image', default_value='/camera/gray', description='input Image topic'),
        DeclareLaunchArgument('detections', default_value='/camera/detections',
                              description='Detection2DArray output'),
        DeclareLaunchArgument('threshold', default_value='200', description='brightness 0..255'),
        DeclareLaunchArgument('min_area', default_value='30', description='smallest blob (pixels)'),
    ]
    node = Node(
        package='roshanavi_examples', executable='blob_detector', name='blob_detector',
        output='screen',
        parameters=[{
            'threshold': ParameterValue(LaunchConfiguration('threshold'), value_type=int),
            'min_area': ParameterValue(LaunchConfiguration('min_area'), value_type=int),
        }],
        remappings=[('image', LaunchConfiguration('image')),
                    ('detections', LaunchConfiguration('detections'))],
    )
    return LaunchDescription([*args, node])
