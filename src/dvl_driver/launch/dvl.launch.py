"""Start only the dvl node.  ros2 launch dvl_driver dvl.launch.py simulate:=true"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    default_cfg = os.path.join(get_package_share_directory('dvl_driver'), 'config', 'dvl.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=default_cfg),
        DeclareLaunchArgument('simulate', default_value='false'),
        DeclareLaunchArgument('namespace', default_value=''),
        Node(
            package='dvl_driver', executable='dvl_node', name='dvl',
            namespace=LaunchConfiguration('namespace'), output='screen',
            parameters=[LaunchConfiguration('params_file'),
                        {'simulate': ParameterValue(LaunchConfiguration('simulate'), value_type=bool)}],
        ),
    ])
