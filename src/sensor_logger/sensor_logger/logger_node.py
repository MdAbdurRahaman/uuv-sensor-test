"""Reusable logging node for the marine sensor drivers.

Subscribes to the driver topics and writes one CSV per stream into
<log_dir>/<YYYYmmdd_HHMMSS>_<session_name>/ while a session is active.
Optionally runs `ros2 bag record` for the same topics in parallel.

Services
  ~/start   marine_sensor_msgs/StartLog
  ~/stop    std_srvs/Trigger
Publishes
  ~/status  marine_sensor_msgs/LoggerStatus (1 Hz)

Set a topic parameter to '' to ignore that sensor.
"""

import os
import signal
import subprocess
import threading

import rclpy
import rclpy.executors
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_srvs.srv import Trigger

from marine_sensor_msgs.msg import (DvlData, DvlPosition, LoggerStatus, Ping1DData,
                                    Ping360Scan)
from marine_sensor_msgs.srv import StartLog

from .session import LogSession, dvl_position_row, dvl_row, ping1d_row, ping360_row


def _stamp(msg) -> float:
    return msg.header.stamp.sec + msg.header.stamp.nanosec * 1e-9


class SensorLogger(Node):
    def __init__(self) -> None:
        super().__init__('sensor_logger')
        p = self.declare_parameter
        p('log_dir', '~/sensor_logs')
        p('autostart', False)
        p('autostart_name', 'auto')
        p('record_bag', False)
        p('bag_storage', 'mcap')            # mcap | sqlite3
        p('store_ping360_intensities', True)
        p('store_ping1d_profile', True)
        p('ping360_topic', '/ping360/scan')
        p('ping1d_topic', '/ping1d/data')
        p('dvl_topic', '/dvl/data')
        p('dvl_position_topic', '/dvl/position')
        p('extra_bag_topics', [''])         # more topics for the bag only

        self._session = None
        self._bag = None
        self._lock = threading.Lock()
        self._topics = []
        g = lambda n: self.get_parameter(n).value  # noqa: E731

        def sub(param, mtype, stream, builder):
            topic = g(param)
            if not topic:
                return
            self._topics.append(topic)

            def cb(msg):
                s = self._session
                if s is not None:
                    s.write(stream, builder(_stamp(msg), msg))
            self.create_subscription(mtype, topic, cb, qos_profile_sensor_data)

        sub('ping360_topic', Ping360Scan, 'ping360',
            lambda t, m: ping360_row(t, m, g('store_ping360_intensities')))
        sub('ping1d_topic', Ping1DData, 'ping1d',
            lambda t, m: ping1d_row(t, m, g('store_ping1d_profile')))
        sub('dvl_topic', DvlData, 'dvl', dvl_row)
        sub('dvl_position_topic', DvlPosition, 'dvl_position', dvl_position_row)

        self.create_service(StartLog, '~/start', self._on_start)
        self.create_service(Trigger, '~/stop', self._on_stop)
        self.status_pub = self.create_publisher(LoggerStatus, '~/status', 10)
        self.create_timer(1.0, self._publish_status)

        if g('autostart'):
            ok, msg, _ = self.start(g('autostart_name'), 'autostart')
            self.get_logger().info(msg)

    # ----------------------------------------------------------------- control
    def start(self, name: str, note: str = ''):
        with self._lock:
            if self._session is not None:
                return False, f'already logging to {self._session.directory}', \
                    self._session.directory
            try:
                s = LogSession(self.get_parameter('log_dir').value, name, note,
                               extra_info={'topics': list(self._topics)})
            except OSError as exc:
                return False, f'cannot create log folder: {exc}', ''
            self._session = s
            if self.get_parameter('record_bag').value:
                self._start_bag(s.directory)
            self.get_logger().info(f'logging started: {s.directory}')
            return True, f'logging to {s.directory}', s.directory

    def stop(self):
        with self._lock:
            s, self._session = self._session, None
            if s is None:
                return False, 'not logging'
            s.close()
            self._stop_bag()
            summary = ', '.join(f'{k}={v}' for k, v in s.rows.items()) or 'no data'
            self.get_logger().info(f'logging stopped: {s.directory} ({summary})')
            self._last_dir = s.directory
            return True, f'saved {s.directory} ({summary})'

    def _start_bag(self, directory: str) -> None:
        topics = list(self._topics) + [t for t in self.get_parameter('extra_bag_topics').value
                                       if t]
        topics += ['/ping360/status', '/ping1d/status', '/dvl/status', '/ping1d/range',
                   '/dvl/twist']
        cmd = ['ros2', 'bag', 'record', '-o', os.path.join(directory, 'bag'),
               '-s', self.get_parameter('bag_storage').value] + sorted(set(topics))
        try:
            self._bag = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                         stderr=subprocess.DEVNULL, start_new_session=True)
        except OSError as exc:
            self.get_logger().error(f'could not start ros2 bag: {exc}')
            self._bag = None

    def _stop_bag(self) -> None:
        b, self._bag = self._bag, None
        if b is None:
            return
        try:
            os.killpg(b.pid, signal.SIGINT)
            b.wait(timeout=10)
        except Exception:  # noqa: BLE001
            b.kill()

    # --------------------------------------------------------------- services
    def _on_start(self, req, res):
        res.success, res.message, res.directory = self.start(req.session_name, req.note)
        return res

    def _on_stop(self, _req, res):
        res.success, res.message = self.stop()
        return res

    def _publish_status(self) -> None:
        m = LoggerStatus()
        m.header.stamp = self.get_clock().now().to_msg()
        s = self._session
        m.active = s is not None
        m.bag_recording = self._bag is not None and self._bag.poll() is None
        if s is not None:
            m.session_name = s.name
            m.directory = s.directory
            m.elapsed_s = float(s.elapsed)
            m.streams = list(s.rows.keys())
            m.rows = [int(v) for v in s.rows.values()]
        else:
            m.directory = getattr(self, '_last_dir', '')
        self.status_pub.publish(m)

    def destroy_node(self):
        if self._session is not None:
            self.stop()
        return super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = SensorLogger()
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
