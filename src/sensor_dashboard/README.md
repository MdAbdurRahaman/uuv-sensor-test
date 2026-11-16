# sensor_dashboard

Web dashboard node. It uses only the Python standard library on the server side and has no CDN or JS libraries, so it works offline on a robot.

```bash
ros2 launch sensor_dashboard dashboard.launch.py      # http://<host>:8765
```

It subscribes to the driver and logger topics, streams data to the browser with Server-Sent Events, and uses ROS services to start/stop the logger, reset the DVL and get/set the sensors' parameters.
Topic and node names are parameters (see `config/dashboard.yaml`), so it can point at namespaced nodes.
