"""ROS 2 node for a Doppler Velocity Log.

Publishes
  ~/data       marine_sensor_msgs/DvlData                 full velocity report + beams
  ~/twist      geometry_msgs/TwistWithCovarianceStamped   standard message (valid reports only)
  ~/position   marine_sensor_msgs/DvlPosition             DVL dead-reckoning (if the DVL sends it)
  ~/status     diagnostic_msgs/DiagnosticStatus           1 Hz
Services
  ~/reset_dead_reckoning   std_srvs/Trigger
"""

import threading
import time

import rclpy
import rclpy.executors
from diagnostic_msgs.msg import DiagnosticStatus, KeyValue
from geometry_msgs.msg import TwistWithCovarianceStamped
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_srvs.srv import Trigger

from marine_sensor_msgs.msg import DvlBeam, DvlData, DvlPosition

from .device import make_dvl


class DvlNode(Node):
    def __init__(self) -> None:
        super().__init__('dvl')
        p = self.declare_parameter
        # nortek_nucleus | waterlinked_tcp | waterlinked_serial | sim | sim_waterlinked
        p('protocol', 'nortek_nucleus')
        p('simulate', False)               # shortcut for protocol:=sim
        p('connection', 'tcp')             # nortek_nucleus only: tcp | serial
        p('host', '192.168.2.201')         # Nucleus IP or NORTEK-<serial>.local
        p('data_port', 9002)               # Nucleus data-only port
        p('command_port', 9000)            # Nucleus command port (password)
        p('password', 'nortek')
        p('send_start', False)             # send STOP, init_commands, START on connect
        p('init_commands', [''])           # e.g. ['SETBT,MODE="AUTO"']  (see Nucleus manual)
        p('stop_on_close', False)          # send STOP when the node exits
        p('tcp_port', 16171)               # Water Linked only
        p('port', '/dev/ttyUSB2')
        p('baudrate', 115200)
        p('verify_checksum', False)        # Water Linked serial only
        p('timeout_s', 3.0)
        p('reconnect_s', 3.0)
        p('frame_id', 'dvl_link')
        p('publish_invalid_twist', False)

        self.data_pub = self.create_publisher(DvlData, '~/data', qos_profile_sensor_data)
        self.twist_pub = self.create_publisher(
            TwistWithCovarianceStamped, '~/twist', qos_profile_sensor_data)
        self.pos_pub = self.create_publisher(DvlPosition, '~/position', qos_profile_sensor_data)
        self.status_pub = self.create_publisher(DiagnosticStatus, '~/status', 10)
        self.create_service(Trigger, '~/reset_dead_reckoning', self._on_reset)

        self._dev = None
        self._info = {}
        self._error = ''
        self._count = 0
        self._valid = 0
        self._rate = 0.0
        self._last = None
        self._running = True
        self._connected_at = 0.0
        self._reconnects = 0
        self._attempts = 0
        self.create_timer(1.0, self._publish_status)
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def _make(self):
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        proto = 'sim' if g('simulate') else g('protocol')
        return make_dvl(proto, host=g('host'), tcp_port=g('tcp_port'), port=g('port'),
                        baudrate=g('baudrate'), timeout_s=g('timeout_s'),
                        verify_checksum=g('verify_checksum'), connection=g('connection'),
                        data_port=g('data_port'), command_port=g('command_port'),
                        password=g('password'), send_start=g('send_start'),
                        init_commands=g('init_commands'), stop_on_close=g('stop_on_close'))

    def _loop(self) -> None:
        t_rate, n_rate = time.monotonic(), 0
        while self._running and rclpy.ok():
            if self._dev is None:
                try:
                    dev = self._make()
                    self._info = dev.open()
                    self._dev = dev
                    self._connected_at = time.time()
                    self._attempts = 0
                    self._error = ''
                    self.get_logger().info(f'DVL connected: {self._info}')
                except Exception as exc:  # noqa: BLE001
                    self._error = str(exc)
                    self._attempts += 1
                    self.get_logger().error(f'DVL connect failed: {exc}',
                                            throttle_duration_sec=10.0)
                    time.sleep(float(self.get_parameter('reconnect_s').value))
                    continue
            try:
                for ev in self._dev.read():
                    if ev['kind'] == 'velocity':
                        self._publish_velocity(ev)
                        self._count += 1
                        n_rate += 1
                    elif ev['kind'] == 'position':
                        self._publish_position(ev)
                    elif ev['kind'] == 'response' and not ev['success']:
                        self.get_logger().warn(f"DVL rejected {ev['response_to']}: {ev['error']}")
                self._error = ''
                now = time.monotonic()
                if now - t_rate >= 1.0:
                    self._rate = n_rate / (now - t_rate)
                    t_rate, n_rate = now, 0
            except Exception as exc:  # noqa: BLE001
                self._error = str(exc)
                self.get_logger().error(f'DVL error, reconnecting: {exc}')
                try:
                    self._dev.close()
                finally:
                    self._dev = None
                    self._reconnects += 1

    def _publish_velocity(self, e: dict) -> None:
        stamp = self.get_clock().now().to_msg()
        frame = self.get_parameter('frame_id').value
        m = DvlData()
        m.header.stamp, m.header.frame_id = stamp, frame
        m.vx, m.vy, m.vz, m.fom = (float(e[k]) for k in ('vx', 'vy', 'vz', 'fom'))
        m.covariance = [float(v) for v in e['covariance']]
        nan = float('nan')
        m.altitude = float(e['altitude'])
        m.altitude_source = e.get('altitude_source', '')
        m.velocity_valid = bool(e['velocity_valid'])
        m.status = int(e['status']) & 0xFFFFFFFF
        m.time_of_validity = float(e['time_of_validity'])
        m.sound_velocity = float(e.get('sound_velocity', nan))
        m.temperature = float(e.get('temperature', nan))
        m.pressure = float(e.get('pressure', nan))
        m.beams = [DvlBeam(id=int(b['id']), velocity=float(b['velocity']),
                           distance=float(b['distance']), rssi=float(b['rssi']),
                           nsd=float(b['nsd']), fom=float(b.get('fom', nan)),
                           valid=bool(b['valid']))
                   for b in e['beams']]
        self.data_pub.publish(m)
        self._last = e
        if e['velocity_valid']:
            self._valid += 1
        if e['velocity_valid'] or self.get_parameter('publish_invalid_twist').value:
            t = TwistWithCovarianceStamped()
            t.header = m.header
            t.twist.twist.linear.x, t.twist.twist.linear.y, t.twist.twist.linear.z = \
                e['vx'], e['vy'], e['vz']
            cov = [0.0] * 36
            c = e['covariance']
            for r in range(3):
                for col in range(3):
                    cov[r * 6 + col] = float(c[r * 3 + col])
            for i in range(3, 6):
                cov[i * 6 + i] = -1.0           # angular velocity unknown
            t.twist.covariance = cov
            self.twist_pub.publish(t)

    def _publish_position(self, e: dict) -> None:
        m = DvlPosition()
        m.header.stamp = self.get_clock().now().to_msg()
        m.header.frame_id = self.get_parameter('frame_id').value
        for k in ('x', 'y', 'z', 'std', 'roll', 'pitch', 'yaw'):
            setattr(m, k, float(e[k]))
        m.status = int(e['status']) & 0xFF
        self.pos_pub.publish(m)

    def _on_reset(self, _req, res):
        try:
            if self._dev is None:
                raise RuntimeError('DVL not connected')
            self._dev.reset_dead_reckoning()
            res.success, res.message = True, 'dead reckoning reset sent'
        except Exception as exc:  # noqa: BLE001
            res.success, res.message = False, str(exc)
        return res

    def _publish_status(self) -> None:
        st = DiagnosticStatus()
        st.name = self.get_fully_qualified_name()
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        proto = g('protocol')
        if g('simulate') or proto.startswith('sim'):
            target = 'simulator'
        elif proto == 'waterlinked_tcp':
            target = f"tcp://{g('host')}:{g('tcp_port')}"
        elif proto == 'nortek_nucleus' and g('connection') == 'tcp':
            target = f"tcp://{g('host')}:{g('data_port')}"
        else:
            target = f"{g('port')}@{g('baudrate')}"
        st.hardware_id = str(self._info.get('where', '')) if self._dev is not None else target
        if self._dev is None:
            st.level, st.message = DiagnosticStatus.ERROR, self._error or 'disconnected'
        elif self._error:
            st.level, st.message = DiagnosticStatus.WARN, self._error
        elif self._last and not self._last['velocity_valid']:
            st.level, st.message = DiagnosticStatus.WARN, 'no bottom lock'
        else:
            st.level, st.message = DiagnosticStatus.OK, 'streaming'
        connected = self._dev is not None
        conn = {'connected': str(connected).lower(),
                'connected_since': f'{self._connected_at:.0f}' if connected else '',
                'connect_attempts': self._attempts, 'reconnects': self._reconnects,
                'target': target}
        kv = {'reports': self._count, 'valid': self._valid, 'rate_hz': f'{self._rate:.1f}',
              'protocol': self._info.get('protocol', '')}
        if self._last:
            kv['altitude_m'] = f"{self._last['altitude']:.2f}"
        kv.update(conn)
        st.values = [KeyValue(key=k, value=str(v)) for k, v in kv.items()]
        self.status_pub.publish(st)

    def destroy_node(self):
        self._running = False
        if self._dev is not None:
            self._dev.close()
        self._thread.join(timeout=3.0)
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = DvlNode()
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
