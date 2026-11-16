cmake_minimum_required(VERSION 3.8)
project(marine_sensor_msgs)

find_package(ament_cmake REQUIRED)
find_package(std_msgs REQUIRED)
find_package(rosidl_default_generators REQUIRED)

rosidl_generate_interfaces(${PROJECT_NAME}
  "msg/Ping360Scan.msg"
  "msg/Ping1DData.msg"
  "msg/DvlBeam.msg"
  "msg/DvlData.msg"
  "msg/DvlPosition.msg"
  "msg/LoggerStatus.msg"
  "srv/StartLog.srv"
  DEPENDENCIES std_msgs
)

ament_export_dependencies(rosidl_default_runtime)
ament_package()
