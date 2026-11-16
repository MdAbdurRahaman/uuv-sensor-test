# ping1d_driver

Node `ping1d_node` (default name `/ping1d`) for the Blue Robotics **Ping** and **Ping2** echosounders. Both use the Ping1D protocol. It connects over serial or UDP; a BlueOS ping service listens on UDP 9090.

```bash
ros2 launch ping1d_driver ping1d.launch.py
ros2 launch ping1d_driver ping1d.launch.py simulate:=true
```

**Publishes:**
- `~/data` (`marine_sensor_msgs/Ping1DData`): distance, confidence and echo profile
- `~/range` (`sensor_msgs/Range`): range is set to `+inf` when confidence is below `min_confidence`
- `~/status`

**Main parameters:** `connection`, `port`, `baudrate`, `host`, `udp_port`, `speed_of_sound`, `auto_mode`, `scan_start_m`, `scan_length_m`, `gain_setting` (0–6), `ping_interval_ms`, `publish_profile`, `min_confidence`.
