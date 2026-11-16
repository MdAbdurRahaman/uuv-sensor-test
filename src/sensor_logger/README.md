# sensor_logger

Logs the driver topics to CSV in `<log_dir>/<timestamp>_<name>/`. It can also record a rosbag2 at the same time (`record_bag: true`).

- **Start:** `ros2 service call /sensor_logger/start marine_sensor_msgs/srv/StartLog "{session_name: 'run1', note: ''}"`
- **Stop:** `ros2 service call /sensor_logger/stop std_srvs/srv/Trigger`
- **Status:** `~/status` (`marine_sensor_msgs/LoggerStatus`, 1 Hz)

Set any `*_topic` parameter to `''` to skip that sensor. `sensor_logger/session.py` has no ROS dependency.
