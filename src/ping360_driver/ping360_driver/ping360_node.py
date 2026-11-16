"""ROS 2 node for the Blue Robotics Ping360 scanning sonar.

Publishes
  ~/scan            marine_sensor_msgs/Ping360Scan  one message per ping
  ~/status          diagnostic_msgs/DiagnosticStatus (1 Hz)

All settings are ROS parameters and can be changed live with
`ros2 param set /ping360 range_m 30.0` - the sonar is reconfigured on the fly.
"""

import threading
import time

import rclpy
import rclpy.executors
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue
from rcl_interfaces.msg import SetParametersResult
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data

from marine_sensor_msgs.msg import Ping360Scan

from .device import GRADIANS, Ping360Device, Ping360Settings, Ping360Simulator, next_angle

SETTING_PARAMS = ('range_m', 'gain_setting', 'transmit_frequency', 'number_of_samples',
                  'speed_of_sound', 'transmit_duration')
SCAN_PARAMS = ('start_angle', 'stop_angle', 'step', 'sector_mode')


class Ping360Node(Node):
    def __init__(self) -> None:
        super().__init__('ping360')
        p = self.declare_parameter
        # connection
        p('simulate', False)
        p('connection', 'serial')          # serial | udp
        p('port', '/dev/ttyUSB0')
        p('baudrate', 115200)
        p('host', '192.168.2.2')
        p('udp_port', 12345)
        p('frame_id', 'ping360_link')
        p('reconnect_s', 3.0)
        # acoustic settings
        p('range_m', 20.0)
        p('gain_setting', 0)
        p('transmit_frequency', 750)
        p('number_of_samples', 1200)
        p('speed_of_sound', 1500.0)
        p('transmit_duration', 0)
        # scan pattern (gradians, 400 = 360 deg)
        p('start_angle', 0)
        p('stop_angle', 399)
        p('step', 1)
        p('sector_mode', 'sweep')          # sweep (wrap around) | bounce (back and forth)

        self.pub = self.create_publisher(Ping360Scan, '~/scan', qos_profile_sensor_data)
        self.status_pub = self.create_publisher(DiagnosticStatus, '~/status', 10)

        self._lock = threading.Lock()
        self._dirty = True
        self._dev = None
        self._info = {}
        self._error = ''
        self._count = 0
        self._rate = 0.0
        self._angle = int(self.get_parameter('start_angle').value)
        self._dir = 1
        self._running = True
        self._connected_at = 0.0
        self._reconnects = 0
        self._attempts = 0

        self.add_on_set_parameters_callback(self._on_params)
        self.create_timer(1.0, self._publish_status)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    # ------------------------------------------------------------------ params
    def _on_params(self, params):
        for prm in params:
            if prm.name == 'gain_setting' and not 0 <= int(prm.value) <= 2:
                return SetParametersResult(successful=False, reason='gain_setting must be 0..2')
            if prm.name == 'range_m' and not 0.5 <= float(prm.value) <= 100:
                return SetParametersResult(successful=False, reason='range_m must be 0.5..100')
            if prm.name == 'step' and not 1 <= int(prm.value) <= 50:
                return SetParametersResult(successful=False, reason='step must be 1..50')
            if prm.name in SETTING_PARAMS:
                self._dirty = True
        return SetParametersResult(successful=True)

    def _settings(self) -> Ping360Settings:
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        return Ping360Settings(
            range_m=float(g('range_m')), gain_setting=int(g('gain_setting')),
            transmit_frequency=int(g('transmit_frequency')),
            number_of_samples=int(g('number_of_samples')),
            speed_of_sound=float(g('speed_of_sound')),
            transmit_duration=int(g('transmit_duration')))

    # -------------------------------------------------------------- hardware
    def _make_device(self):
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        if g('simulate'):
            return Ping360Simulator()
        return Ping360Device(connection=g('connection'), port=g('port'),
                             baudrate=int(g('baudrate')), host=g('host'),
                             udp_port=int(g('udp_port')))

    def _next_angle(self) -> int:
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        self._angle, self._dir = next_angle(
            self._angle, int(g('start_angle')), int(g('stop_angle')), int(g('step')),
            g('sector_mode'), self._dir)
        return self._angle

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
                    self.get_logger().info(f'Ping360 connected: {self._info}')
                except Exception as exc:  # noqa: BLE001
                    self._error = str(exc)
                    self._attempts += 1
                    self.get_logger().error(f'Ping360 connect failed: {exc}',
                                            throttle_duration_sec=10.0)
                    time.sleep(float(self.get_parameter('reconnect_s').value))
                    continue
            try:
                if self._dirty:
                    self._dirty = False
                    self._dev.configure(self._settings())
                angle = self._next_angle()
                res = self._dev.ping(angle)
                if res is None:
                    self._error = 'no reply to transducer command'
                    continue
                self._publish(res)
                self._error = ''
                self._count += 1
                n_rate += 1
                now = time.monotonic()
                if now - t_rate >= 1.0:
                    self._rate = n_rate / (now - t_rate)
                    t_rate, n_rate = now, 0
            except Exception as exc:  # noqa: BLE001
                self._error = str(exc)
                self.get_logger().error(f'Ping360 error, reconnecting: {exc}')
                try:
                    self._dev.close()
                finally:
                    self._dev = None
                    self._reconnects += 1

    def _publish(self, r: dict) -> None:
        m = Ping360Scan()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = self.get_parameter('frame_id').value
        m.angle = r['angle']
        m.angle_deg = float(r['angle'] * 360.0 / GRADIANS)
        m.range_m = float(r['range_m'])
        m.speed_of_sound = float(r['speed_of_sound'])
        m.mode = int(r['mode'])
        m.gain_setting = int(r['gain_setting'])
        m.transmit_duration = int(r['transmit_duration'])
        m.sample_period = int(r['sample_period'])
        m.transmit_frequency = int(r['transmit_frequency'])
        m.number_of_samples = int(r['number_of_samples'])
        m.intensities = r['data']
        self.pub.publish(m)

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
        kv = {'pings': self._count, 'rate_hz': f'{self._rate:.1f}',
              'firmware': self._info.get('firmware', ''), 'angle': self._angle}
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
    node = Ping360Node()
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
