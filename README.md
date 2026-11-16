# uuv-sensor-test – ROS 2 marine sensor test bench

ROS 2 **Jazzy** workspace (Ubuntu 24.04) for testing a **Blue Robotics Ping360**, a **Blue Robotics Ping / Ping2** echosounder and a **Nortek Nucleus1000** DVL. It also has a browser dashboard and data logging.
Every sensor is its own `ament_python` package and node, so you can copy any of them into another project.

```
uuv-sensor-test/              (this repo = a colcon workspace root)
├── src/
│   ├── marine_sensor_msgs/   ament_cmake   messages + StartLog service (shared by all)
│   ├── ping360_driver/       ament_python  node: /ping360
│   ├── ping1d_driver/        ament_python  node: /ping1d   (Ping and Ping2)
│   ├── dvl_driver/           ament_python  node: /dvl      (Nortek Nucleus1000; Water Linked also supported)
│   ├── sensor_logger/        ament_python  node: /sensor_logger  CSV (+ optional rosbag2)
│   ├── sensor_dashboard/     ament_python  node: /sensor_dashboard  web UI on :8765
│   └── sensor_bringup/       ament_python  launch + one params file for the whole bench
├── tools/plot_session.py     offline report (PNG) from a logged session
└── windows/                  double-click launchers for Windows + WSL (see below)
```

Every driver has a **simulator** (`simulate:=true`), so you can test the dashboard, the logger and your own code without any hardware.

---

## Quick start on Windows (WSL Ubuntu-24.04 + ROS 2 Jazzy)

Clone or download the repo anywhere on Windows, open the `windows/` folder, and double-click the files in this order:

| File | What it does |
|---|---|
| `1_SETUP.bat` | One-time setup. Installs the dependencies, copies `src/` into `~/ros2_ws` in WSL and builds it. Asks for your WSL password. |
| `2_RUN_SIMULATION.bat` | Runs everything with simulated sensors and opens the dashboard. |
| `4_ATTACH_USB_SENSORS.bat` | Shares the Ping360 / Ping2 USB adapters with WSL (installs usbipd; admin). Works out which port is which sensor and writes both ports into `windows/test_bench.yaml`. |
| `3_RUN_REAL_SENSORS.bat` | Runs with the real sensors, using `windows/test_bench.yaml` (ports, Nucleus IP). |
| `5_DIAGNOSE.bat` | Writes `diag.txt`, covering networking, ports and nodes. |
| `6_RELEASE_USB_TO_WINDOWS.bat` | Gives the USB adapters back to Windows (e.g. for Ping Viewer). |

The run scripts rebuild automatically when anything in `src/` has changed since the last build.
The dashboard runs on port **8765**. Port 8080 is often taken on Windows.
If USBPcap (Wireshark) is installed, usbipd needs `bind --force`, which the attach script uses. A Windows restart may be required after the first bind.

## 1. Install

ROS 2 Jazzy must already be installed (`ros-jazzy-desktop`, `ros-dev-tools`). Then:

```bash
sudo apt install python3-serial python3-colcon-common-extensions
pip install --break-system-packages bluerobotics-ping      # brping: Ping360 + Ping1D/Ping2 protocol
# optional, for tools/plot_session.py
sudo apt install python3-numpy python3-matplotlib
```

## 2. Build

```bash
cd ~/ros2_ws          # or the folder you cloned this repo into
rosdep install --from-paths src --ignore-src -r -y
colcon build --symlink-install
source install/setup.bash          # or add it to ~/.bashrc
```

> If you change a `.msg`, rebuild with `colcon build --symlink-install --cmake-clean-cache`.

## 3. Run

**No hardware (simulators):**
```bash
ros2 launch sensor_bringup test_bench.launch.py simulate:=true
```
Open **http://localhost:8765**. From another PC on the network, use `http://<robot-ip>:8765`.

**Real sensors:** first edit `src/sensor_bringup/config/test_bench.yaml` (ports, IPs), rebuild, then:
```bash
ros2 launch sensor_bringup test_bench.launch.py
ros2 launch sensor_bringup test_bench.launch.py dvl:=false               # only some sensors
ros2 launch sensor_bringup test_bench.launch.py record_bag:=true         # CSV + rosbag2
ros2 launch sensor_bringup test_bench.launch.py params_file:=/path/my.yaml log_dir:=/data/logs port:=9000
```

**One sensor only** (each package has its own launch + yaml):
```bash
ros2 launch ping360_driver ping360.launch.py
ros2 launch ping1d_driver  ping1d.launch.py simulate:=true
ros2 launch dvl_driver     dvl.launch.py
ros2 run ping360_driver ping360_node --ros-args -p port:=/dev/ttyUSB0 -p range_m:=10.0
```

### Default connections

| Sensor | Default | Change with |
|---|---|---|
| Ping360 | serial `/dev/ttyUSB0` @115200 (UDP: `192.168.2.2:12345`) | `connection`, `port`, `host`, `udp_port` |
| Ping / Ping2 | serial `/dev/ttyUSB1` @115200 (BlueOS UDP: `192.168.2.2:9090`) | same |
| DVL (Nortek Nucleus1000) | TCP `192.168.2.201:9002` (data port) – **set `host` to your Nucleus IP** | `connection` (tcp\|serial), `host`, `data_port`, `port` |

### Nortek Nucleus1000 notes
* The driver reads Nortek's native binary format: bottom track `0xB4`, altimeter `0xAA` and AHRS `0xD2`. It needs no extra Python package.
* **Finding the IP:** the Nucleus gets its IP from DHCP by default, and you can also reach it as `NORTEK-<serial>.local`. Put either one in `host`.
* **Ports:** the driver reads from the data-only port **9002**, which needs no password and allows up to 2 clients. That means Nortek's own software can stay connected at the same time.
* **Starting a measurement:** if the Nucleus isn't already measuring, set `send_start: true`. The driver then logs in on command port **9000** (set by the `password` parameter, default `nortek`), sends `STOP`, then anything in `init_commands`, then `START`. Set `stop_on_close: true` if you want it to send `STOP` when the node exits.
* **Serial:** set `connection: serial` and `port`. It runs at 115200 baud, with commands and data on the same line.
* **What gets published:**
  * Velocity from bottom-track X/Y/Z, in the instrument frame.
  * Altitude from the vertical altimeter beam (falls back to the slant beams).
  * FOM and covariance from the bottom-track uncertainty.
  * Temperature, pressure and sound speed.
  * Roll, pitch and heading from the AHRS, published in `~/position`.
* **Dead reckoning:** the Nucleus doesn't output a position in these records, so the node integrates velocity using the AHRS rotation into a local north/east track. `~/reset_dead_reckoning` zeroes it. It's good enough for a test bench, but it isn't a navigation filter.

Tip: use `/dev/serial/by-id/...` paths instead of `ttyUSBx` so the ports don't swap after a reboot.

### Running in WSL on Windows
* USB serial sensors must be attached to WSL with **usbipd-win**. `windows/4_ATTACH_USB_SENSORS.bat` does this for you. To do it by hand, run these in an admin PowerShell: `usbipd list`, then `usbipd bind --busid <id>` (add `--force` if USBPcap is installed), then `usbipd attach --wsl --busid <id>`. After that the sensor shows up as `/dev/ttyUSB*` (or `/dev/ttyACM*`) in WSL.
* Ethernet sensors (Ping360 Ethernet, DVL A50) work directly. If WSL can't reach the `192.168.x.x` network, turn on mirrored networking: add `networkingMode=mirrored` to `%UserProfile%\.wslconfig`.
* The dashboard opens from the Windows browser at `http://localhost:8765`.

---

## 4. Dashboard

* **Connection indicator** for each sensor, shown on its card and in its panel header:
  * **Connected:** the device is open and data is flowing. Also shows uptime and reconnect count.
  * **Connected · no data:** the port is open but nothing has arrived for 3 s.
  * **Disconnected:** the node is running but can't open the port or socket. Shows the address and retry count; hover to see the error.
  * **Node offline:** no status is coming from the node.
* **Health cards:** one per node, with the status level and message, the rate, the firmware and the age of the last message.
* **Ping360:** live polar sonar image (hover for angle, range and echo), the latest A-scan, and live settings (range, gain, frequency, step, sector, speed of sound). Settings are applied with `ros2 param set` behind the scenes.
* **Ping / Ping2:** distance, confidence, a 60 s distance chart, an echogram, and live settings.
* **DVL:** bottom-lock state, altitude, FOM, vx/vy/vz chart, per-beam table, and a dead-reckoning track with a reset button.
* **Logging:** set a session name and note, then **Start logging** / **Stop logging**. The **Log sessions** table lists every session; download single CSVs or the whole session as a zip.

## 5. Logged data

`~/sensor_logs/<YYYYmmdd_HHMMSS>_<name>/`

| File | Columns |
|---|---|
| `ping360.csv` | stamp, angle_grad, angle_deg, range_m, gain, frequency, tx duration, sample period, n samples, speed of sound, `intensities_hex` |
| `ping1d.csv` | stamp, distance_m, confidence, tx duration, ping_number, scan_start/length, gain, speed of sound, `profile_hex` |
| `dvl.csv` | stamp, vx, vy, vz, fom, altitude, altitude_source, velocity_valid, status_hex, sound_velocity, temperature, pressure, time_of_validity, covariance, per-beam velocity/distance/fom/rssi/valid |
| `dvl_position.csv` | stamp, x, y, z, std, roll, pitch, yaw, status |
| `session_info.json` | start/stop time, note, row counts, topics |
| `bag/` | rosbag2 (only if `record_bag:=true`) |

Decode the hex columns with `numpy.frombuffer(bytes.fromhex(s), 'u1')`. To make a quick report image:
```bash
python3 tools/plot_session.py ~/sensor_logs/<session>      # -> <session>/report.png
```
Ping360 at full rate writes about 6–7 MB/min. Set `store_ping360_intensities: false` to log only the metadata.

You can also control the logger without the dashboard:
```bash
ros2 service call /sensor_logger/start marine_sensor_msgs/srv/StartLog "{session_name: 'tank1', note: 'gain 1'}"
ros2 service call /sensor_logger/stop std_srvs/srv/Trigger
```

---

## 6. Topics, services, parameters

| Node | Publishes | Services |
|---|---|---|
| `/ping360` | `~/scan` (Ping360Scan), `~/status` (DiagnosticStatus) | params are live: `ros2 param set /ping360 range_m 30.0` |
| `/ping1d` | `~/data` (Ping1DData), `~/range` (sensor_msgs/Range), `~/status` | live params |
| `/dvl` | `~/data` (DvlData), `~/twist` (TwistWithCovarianceStamped, valid only), `~/position` (DvlPosition), `~/status` | `~/reset_dead_reckoning` (Trigger) |
| `/sensor_logger` | `~/status` (LoggerStatus) | `~/start` (StartLog), `~/stop` (Trigger) |

All topics are relative (`~/`), so a namespace or remap moves the whole node. For example, `ros2 launch dvl_driver dvl.launch.py namespace:=auv1` publishes `/auv1/dvl/data`.

## 7. Reusing a node in another project

1. Copy `src/marine_sensor_msgs` and the driver package, e.g. `src/dvl_driver`, into the other workspace's `src/`.
2. Run `colcon build`, then include `dvl_driver/launch/dvl.launch.py` or start `dvl_node` from your own launch file.

Each driver keeps the hardware code in a ROS-free `device.py`, so you can also use it in a plain Python script:
```python
from ping1d_driver.device import Ping1DDevice, Ping1DSettings
d = Ping1DDevice(port='/dev/ttyUSB1'); d.open(); d.configure(Ping1DSettings())
print(d.read()['distance_m'])
```
**Adding another DVL** (Teledyne PD6, …): write a class in `dvl_driver/device.py` with `open()`, `read()` → list of events, `reset_dead_reckoning()` and `close()`, then register it in `make_dvl()`.

## 8. Tests

```bash
colcon test --packages-select ping360_driver ping1d_driver dvl_driver && colcon test-result --verbose
```
