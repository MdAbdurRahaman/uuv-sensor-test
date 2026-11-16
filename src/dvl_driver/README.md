# dvl_driver

Node `dvl_node` (default name `/dvl`) for Doppler Velocity Logs. The default protocol is the **Nortek Nucleus1000**.

| `protocol` | Device |
|---|---|
| `nortek_nucleus` (default) | Nortek Nucleus1000, native binary format. TCP: data port 9002, optional command port 9000. Serial: 115200 baud. |
| `waterlinked_tcp` | Water Linked DVL A50 / A125, JSON over TCP 16171 |
| `waterlinked_serial` | Water Linked serial reports (`wrz` / `wrp`) |
| `sim` (or `simulate:=true`) | Nucleus simulator. It produces real Nucleus binary packets and runs them through the same parser as the hardware. |

**Publishes:**
- `~/data` (`DvlData`): velocity, FOM, covariance, altitude, temperature, pressure, sound speed and beams
- `~/twist` (`TwistWithCovarianceStamped`): valid reports only
- `~/position` (`DvlPosition`): for the Nucleus, the driver's own dead reckoning plus AHRS roll/pitch/heading
- `~/status`

**Service:** `~/reset_dead_reckoning`.

**Nucleus parameters:** `connection` (tcp|serial), `host`, `data_port`, `command_port`, `password`, `send_start`, `init_commands`, `stop_on_close`, `port`, `baudrate`, `timeout_s`.

The binary format follows Nortek's *Nucleus Operations and Integration* manual, ch. 8. The code is in `dvl_driver/nortek_nucleus.py` and has no ROS dependency:
```python
from dvl_driver.nortek_nucleus import NortekNucleus
n = NortekNucleus(host='192.168.2.201'); n.open()
while True:
    for e in n.read(): print(e)
```
