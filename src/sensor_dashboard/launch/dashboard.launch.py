"""Start only the sensor_dashboard node."""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def generate_launch_description():
    default_cfg = os.path.join(get_package_share_directory('sensor_dashboard'), 'config', 'dashboard.yaml')
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=default_cfg),
        Node(package='sensor_dashboard', executable='dashboard_node', name='sensor_dashboard', output='screen',
             parameters=[LaunchConfiguration('params_file')]),
    ])
