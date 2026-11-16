# ping360_driver

Node `ping360_node` (default name `/ping360`) for the Blue Robotics Ping360. It connects over serial or UDP and uses the `brping` library.

```bash
ros2 launch ping360_driver ping360.launch.py                 # uses config/ping360.yaml
ros2 launch ping360_driver ping360.launch.py simulate:=true
ros2 param set /ping360 range_m 10.0                         # live reconfigure
```

**Publishes:** `~/scan` (`marine_sensor_msgs/Ping360Scan`, one message per ping) and `~/status` (`diagnostic_msgs/DiagnosticStatus`).

**Main parameters:** `connection` (serial|udp), `port`, `baudrate`, `host`, `udp_port`, `range_m`, `gain_setting` (0–2), `transmit_frequency` (kHz), `number_of_samples`, `speed_of_sound`, `transmit_duration` (0 = auto), `start_angle`/`stop_angle`/`step` (in gradians, 400 = 360°), `sector_mode` (sweep|bounce).

The sample period and transmit duration are calculated from `range_m`, using the same rule as Ping Viewer.
`ping360_driver/device.py` has no ROS dependency, so you can use it on its own.

Dependencies: `marine_sensor_msgs`, and `pip install bluerobotics-ping`.
