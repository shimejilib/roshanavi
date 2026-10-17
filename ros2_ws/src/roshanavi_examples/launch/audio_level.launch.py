"""Start audio_level: 16-bit audio -> level (dB) + silence flag.

    ros2 launch roshanavi_examples audio_level.launch.py audio:=/mic/audio input_type:=int16
"""
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    args = [
        DeclareLaunchArgument('audio', default_value='/audio', description='input audio topic'),
        DeclareLaunchArgument('input_type', default_value='stamped',
                              description='stamped (AudioDataStamped) or int16 (Int16MultiArray)'),
        DeclareLaunchArgument('silence_below_db', default_value='-45.0'),
        DeclareLaunchArgument('sound_above_db', default_value='-35.0'),
    ]
    node = Node(
        package='roshanavi_examples', executable='audio_level', name='audio_level',
        output='screen',
        parameters=[{
            'input_type': LaunchConfiguration('input_type'),
            'silence_below_db': ParameterValue(LaunchConfiguration('silence_below_db'),
                                               value_type=float),
            'sound_above_db': ParameterValue(LaunchConfiguration('sound_above_db'),
                                             value_type=float),
        }],
        remappings=[('audio', LaunchConfiguration('audio')),
                    ('level_db', '/audio/level_db'), ('silence', '/audio/silence')],
    )
    return LaunchDescription([*args, node])
