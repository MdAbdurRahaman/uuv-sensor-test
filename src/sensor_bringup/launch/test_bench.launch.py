"""Sensor test bench: Ping360 + Ping1D/Ping2 + DVL drivers, logger and dashboard.

  ros2 launch sensor_bringup test_bench.launch.py                 # real hardware
  ros2 launch sensor_bringup test_bench.launch.py simulate:=true  # no hardware
  ros2 launch sensor_bringup test_bench.launch.py dvl:=false ping360:=false
  ros2 launch sensor_bringup test_bench.launch.py params_file:=/path/my_bench.yaml

Dashboard: http://<this-machine-ip>:8765
"""
import os

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument
from launch.conditions import IfCondition
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node
from launch_ros.parameter_descriptions import ParameterValue


def generate_launch_description():
    cfg = os.path.join(get_package_share_directory('sensor_bringup'), 'config', 'test_bench.yaml')
    L = LaunchConfiguration
    params = L('params_file')
    sim = {'simulate': ParameterValue(L('simulate'), value_type=bool)}

    args = [
        DeclareLaunchArgument('params_file', default_value=cfg),
        DeclareLaunchArgument('simulate', default_value='false',
                              description='use built-in simulators instead of hardware'),
        DeclareLaunchArgument('ping360', default_value='true'),
        DeclareLaunchArgument('ping1d', default_value='true'),
        DeclareLaunchArgument('dvl', default_value='true'),
        DeclareLaunchArgument('logger', default_value='true'),
        DeclareLaunchArgument('dashboard', default_value='true'),
        DeclareLaunchArgument('record_bag', default_value='false',
                              description='also record a rosbag2 in each log session'),
        DeclareLaunchArgument('log_dir', default_value='~/sensor_logs'),
        DeclareLaunchArgument('port', default_value='8765', description='dashboard HTTP port'),
    ]
    nodes = [
        Node(package='ping360_driver', executable='ping360_node', name='ping360', output='screen',
             parameters=[params, sim], condition=IfCondition(L('ping360')), respawn=True,
             respawn_delay=3.0),
        Node(package='ping1d_driver', executable='ping1d_node', name='ping1d', output='screen',
             parameters=[params, sim], condition=IfCondition(L('ping1d')), respawn=True,
             respawn_delay=3.0),
        Node(package='dvl_driver', executable='dvl_node', name='dvl', output='screen',
             parameters=[params, sim], condition=IfCondition(L('dvl')), respawn=True,
             respawn_delay=3.0),
        Node(package='sensor_logger', executable='sensor_logger_node', name='sensor_logger',
             output='screen', condition=IfCondition(L('logger')),
             parameters=[params, {'log_dir': L('log_dir'),
                                  'record_bag': ParameterValue(L('record_bag'), value_type=bool)}]),
        Node(package='sensor_dashboard', executable='dashboard_node', name='sensor_dashboard',
             output='screen', condition=IfCondition(L('dashboard')),
             parameters=[params, {'log_dir': L('log_dir'),
                                  'port': ParameterValue(L('port'), value_type=int)}]),
    ]
    return LaunchDescription(args + nodes)
