"""Start only the ping360 node.  ros2 launch ping360_driver ping360.launch.py simulate:=true"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_cfg = os.path.join(get_package_share_directory('ping360_driver'), 'config', 'ping360.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=default_cfg),
        DeclareLaunchArgument('simulate', default_value='false'),
        DeclareLaunchArgument('namespace', default_value=''),
        Node(
            package='ping360_driver', executable='ping360_node', name='ping360',
            namespace=LaunchConfiguration('namespace'), output='screen',
            parameters=[LaunchConfiguration('params_file'),
                        {'simulate': ParameterValue(LaunchConfiguration('simulate'), value_type=bool)}],
        ),
    ])
