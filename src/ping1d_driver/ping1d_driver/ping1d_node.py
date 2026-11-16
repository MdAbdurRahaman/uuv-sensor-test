"""ROS 2 node for Blue Robotics Ping / Ping2 echosounders (Ping1D protocol).

Publishes
  ~/data     marine_sensor_msgs/Ping1DData   distance, confidence, echo profile
  ~/range    sensor_msgs/Range               standard message for other tools/projects
  ~/status   diagnostic_msgs/DiagnosticStatus (1 Hz)
"""

import math
import threading
import time

import rclpy
import rclpy.executors
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from sensor_msgs.msg import Range

from marine_sensor_msgs.msg import Ping1DData

from .device import Ping1DDevice, Ping1DSettings, Ping1DSimulator

SETTING_PARAMS = ('speed_of_sound', 'auto_mode', 'scan_start_m', 'scan_length_m',
                  'gain_setting', 'ping_interval_ms', 'publish_profile')


class Ping1DNode(Node):
    def __init__(self) -> None:
        super().__init__('ping1d')
        p = self.declare_parameter
        p('simulate', False)
        p('connection', 'serial')          # serial | udp
        p('port', '/dev/ttyUSB1')
        p('baudrate', 115200)
        p('host', '192.168.2.2')
        p('udp_port', 9090)
        p('frame_id', 'ping1d_link')
        p('reconnect_s', 3.0)
        p('speed_of_sound', 1500.0)
        p('auto_mode', True)
        p('scan_start_m', 0.0)
        p('scan_length_m', 30.0)
        p('gain_setting', 0)
        p('ping_interval_ms', 100)
        p('publish_profile', True)
        p('min_confidence', 0)            # below this, Range.range is published as +inf
        p('field_of_view_deg', 25.0)      # Ping: 25 deg (30 deg at -6 dB); Ping2 similar
        p('min_range_m', 0.3)
        p('max_range_m', 100.0)

        self.pub = self.create_publisher(Ping1DData, '~/data', qos_profile_sensor_data)
        self.range_pub = self.create_publisher(Range, '~/range', qos_profile_sensor_data)
        self.status_pub = self.create_publisher(DiagnosticStatus, '~/status', 10)

        self._dirty = True
        self._dev = None
        self._info = {}
        self._error = ''
        self._count = 0
        self._rate = 0.0
        self._last = None
        self._running = True
        self._connected_at = 0.0
        self._reconnects = 0
        self._attempts = 0
        self.add_on_set_parameters_callback(self._on_params)
        self.create_timer(1.0, self._publish_status)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _on_params(self, params):
        for prm in params:
            if prm.name == 'gain_setting' and not 0 <= int(prm.value) <= 6:
                return SetParametersResult(successful=False, reason='gain_setting must be 0..6')
            if prm.name in SETTING_PARAMS:
                self._dirty = True
        return SetParametersResult(successful=True)

    def _settings(self) -> Ping1DSettings:
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        return Ping1DSettings(
            speed_of_sound=float(g('speed_of_sound')), auto_mode=bool(g('auto_mode')),
            scan_start_m=float(g('scan_start_m')), scan_length_m=float(g('scan_length_m')),
            gain_setting=int(g('gain_setting')), ping_interval_ms=int(g('ping_interval_ms')),
            profile=bool(g('publish_profile')))

    def _make_device(self):
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        if g('simulate'):
            return Ping1DSimulator()
        return Ping1DDevice(connection=g('connection'), port=g('port'),
                            baudrate=int(g('baudrate')), host=g('host'),
                            udp_port=int(g('udp_port')))

    def _loop(self) -> None:
        t_rate, n_rate = time.monotonic(), 0
        while self._running and rclpy.ok():
            if self._dev is None:
                try:
                    dev = self._make_device()
                    self._info = dev.open()
                    self._dev = dev
                    self._connected_at = time.time()
                    self._attempts = 0
                    self._dirty = True
                    self._error = ''
                    self.get_logger().info(f'Ping1D connected: {self._info}')
                except Exception as exc:  # noqa: BLE001
                    self._error = str(exc)
                    self._attempts += 1
                    self.get_logger().error(f'Ping1D connect failed: {exc}',
                                            throttle_duration_sec=10.0)
                    time.sleep(float(self.get_parameter('reconnect_s').value))
                    continue
            try:
                if self._dirty:
                    self._dirty = False
                    self._dev.configure(self._settings())
                r = self._dev.read()
                if r is None:
                    self._error = 'no reply'
                    time.sleep(0.05)
                    continue
                self._error = ''
                self._publish(r)
                self._count += 1
                n_rate += 1
                now = time.monotonic()
                if now - t_rate >= 1.0:
                    self._rate = n_rate / (now - t_rate)
                    t_rate, n_rate = now, 0
            except Exception as exc:  # noqa: BLE001
                self._error = str(exc)
                self.get_logger().error(f'Ping1D error, reconnecting: {exc}')
                try:
                    self._dev.close()
                finally:
                    self._dev = None
                    self._reconnects += 1

    def _publish(self, r: dict) -> None:
        stamp = self.get_clock().now().to_msg()
        frame = self.get_parameter('frame_id').value
        m = Ping1DData()
        m.header.stamp, m.header.frame_id = stamp, frame
        m.distance_m = float(r['distance_m'])
        m.confidence = int(r['confidence'])
        m.transmit_duration = int(r['transmit_duration'])
        m.ping_number = int(r['ping_number'])
        m.scan_start_m = float(r['scan_start_m'])
        m.scan_length_m = float(r['scan_length_m'])
        m.gain_setting = int(r['gain_setting'])
        m.speed_of_sound = float(r['speed_of_sound'])
        m.profile = r['profile']
        self.pub.publish(m)
        self._last = r

        g = lambda n: self.get_parameter(n).value  # noqa: E731
        rg = Range()
        rg.header.stamp, rg.header.frame_id = stamp, frame
        rg.radiation_type = Range.ULTRASOUND
        rg.field_of_view = math.radians(float(g("field_of_view_deg")))
        rg.min_range = float(g('min_range_m'))
        rg.max_range = float(g('max_range_m'))
        ok = r['confidence'] >= int(g('min_confidence'))
        rg.range = float(r['distance_m']) if ok else float('inf')
        self.range_pub.publish(rg)

    def _publish_status(self) -> None:
        st = DiagnosticStatus()
        st.name = self.get_fully_qualified_name()
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        target = 'simulator' if g('simulate') else (f"udp://{g('host')}:{g('udp_port')}" if g('connection') == 'udp' else f"{g('port')}@{g('baudrate')}")
        st.hardware_id = str(self._info.get('where', '')) if self._dev is not None else target
        if self._dev is None:
            st.level, st.message = DiagnosticStatus.ERROR, self._error or 'disconnected'
        elif self._error:
            st.level, st.message = DiagnosticStatus.WARN, self._error
        else:
            st.level, st.message = DiagnosticStatus.OK, 'streaming'
        connected = self._dev is not None
        conn = {'connected': str(connected).lower(),
                'connected_since': f'{self._connected_at:.0f}' if connected else '',
                'connect_attempts': self._attempts, 'reconnects': self._reconnects,
                'target': target}
        kv = {'readings': self._count, 'rate_hz': f'{self._rate:.1f}',
              'firmware': self._info.get('firmware', ''),
              'model': self._info.get('device_model', '')}
        if self._last:
            kv['distance_m'] = f"{self._last['distance_m']:.3f}"
            kv['confidence'] = self._last['confidence']
        kv.update(conn)
        st.values = [KeyValue(key=k, value=str(v)) for k, v in kv.items()]
        self.status_pub.publish(st)

    def destroy_node(self):
        self._running = False
        self._thread.join(timeout=2.0)
        if self._dev is not None:
            self._dev.close()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = Ping1DNode()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
