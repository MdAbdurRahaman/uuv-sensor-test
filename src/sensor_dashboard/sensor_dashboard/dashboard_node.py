"""Browser dashboard node for the marine sensor test bench.

Open http://<robot-ip>:8765 after launching. Shows live Ping360 / Ping1D / DVL
data and node health, changes sensor parameters, and starts/stops the
sensor_logger node. Works with any subset of sensors running.
"""

import base64
import os
import threading
import time

import rclpy
import rclpy.executors
from diagnostic_msgs.msg import DiagnosticStatus
from rcl_interfaces.msg import Parameter, ParameterType, ParameterValue
from rcl_interfaces.srv import GetParameters, SetParameters
from rclpy.callback_groups import ReentrantCallbackGroup
from rclpy.node import Node
from rclpy.qos import qos_profile_sensor_data
from std_srvs.srv import Trigger

from marine_sensor_msgs.msg import DvlData, DvlPosition, LoggerStatus, Ping1DData, Ping360Scan
from marine_sensor_msgs.srv import StartLog

from .web_server import Hub, make_server

LEVELS = {0: 'ok', 1: 'warn', 2: 'error', 3: 'stale'}


def _stamp(m) -> float:
    return m.header.stamp.sec + m.header.stamp.nanosec * 1e-9


def _f(x, nd=None):
    """JSON-safe float: NaN/inf -> None (JSON has no NaN)."""
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    if x != x or x in (float('inf'), float('-inf')):
        return None
    return round(x, nd) if nd is not None else x


def _downsample(data: bytes, n_max: int) -> bytes:
    n = len(data)
    if n <= n_max or n_max <= 0:
        return bytes(data)
    k = -(-n // n_max)                       # ceil
    # keep the max of each bin so thin echoes do not disappear
    return bytes(max(data[i:i + k]) for i in range(0, n, k))


class DashboardNode(Node):
    def __init__(self) -> None:
        super().__init__('sensor_dashboard')
        p = self.declare_parameter
        p('host', '0.0.0.0')
        p('port', 8765)
        p('web_dir', '')
        p('log_dir', '~/sensor_logs')        # same folder as sensor_logger, for downloads
        p('ping360_topic', '/ping360/scan')
        p('ping1d_topic', '/ping1d/data')
        p('dvl_topic', '/dvl/data')
        p('dvl_position_topic', '/dvl/position')
        p('logger_node', '/sensor_logger')
        p('ping360_node', '/ping360')
        p('ping1d_node', '/ping1d')
        p('dvl_node', '/dvl')
        p('ping360_display_samples', 600)
        p('ping1d_max_rate_hz', 20.0)
        p('dvl_max_rate_hz', 20.0)
        g = lambda n: self.get_parameter(n).value  # noqa: E731

        self.hub = Hub()
        self.cbg = ReentrantCallbackGroup()
        self._last_pub = {}
        self._rx = {}                         # channel -> (count, last_time)

        sd = qos_profile_sensor_data
        self.create_subscription(Ping360Scan, g('ping360_topic'), self._on_ping360, sd)
        self.create_subscription(Ping1DData, g('ping1d_topic'), self._on_ping1d, sd)
        self.create_subscription(DvlData, g('dvl_topic'), self._on_dvl, sd)
        self.create_subscription(DvlPosition, g('dvl_position_topic'), self._on_dvl_pos, sd)
        for key in ('ping360', 'ping1d', 'dvl'):
            topic = g(f'{key}_node').rstrip('/') + '/status'
            self.create_subscription(DiagnosticStatus, topic,
                                     lambda m, k=key: self._on_status(k, m), 10)
        self.create_subscription(LoggerStatus, g('logger_node').rstrip('/') + '/status',
                                 self._on_logger, 10)

        self._svc_clients = {}
        self.create_timer(1.0, self._heartbeat)

        web_dir = g('web_dir')
        if not web_dir:
            try:
                from ament_index_python.packages import get_package_share_directory
                web_dir = os.path.join(get_package_share_directory('sensor_dashboard'), 'web')
            except Exception:  # noqa: BLE001
                web_dir = os.path.join(os.path.dirname(__file__), '..', 'web')
        self.server = make_server(g('host'), int(g('port')), web_dir, self.hub,
                                  g('log_dir'), self._on_command)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.get_logger().info(f"dashboard on http://{g('host')}:{g('port')}  (web: {web_dir})")

    # -------------------------------------------------------------- helpers
    def _throttle(self, ch: str, max_hz: float) -> bool:
        now = time.monotonic()
        if max_hz > 0 and now - self._last_pub.get(ch, 0.0) < 1.0 / max_hz:
            return False
        self._last_pub[ch] = now
        return True

    def _count(self, ch: str) -> None:
        c, _ = self._rx.get(ch, (0, 0.0))
        self._rx[ch] = (c + 1, time.time())

    # -------------------------------------------------------- subscriptions
    def _on_ping360(self, m: Ping360Scan) -> None:
        self._count('ping360')
        data = _downsample(bytes(m.intensities),
                           int(self.get_parameter('ping360_display_samples').value))
        self.hub.publish('ping360', {
            'stamp': _stamp(m), 'angle': m.angle, 'range_m': m.range_m,
            'gain': m.gain_setting, 'freq': m.transmit_frequency,
            'tx_us': m.transmit_duration, 'n': m.number_of_samples,
            'sos': m.speed_of_sound, 'data': base64.b64encode(data).decode(),
        }, keep=False)

    def _on_ping1d(self, m: Ping1DData) -> None:
        self._count('ping1d')
        if not self._throttle('ping1d', float(self.get_parameter('ping1d_max_rate_hz').value)):
            return
        self.hub.publish('ping1d', {
            'stamp': _stamp(m), 'distance_m': m.distance_m, 'confidence': m.confidence,
            'ping_number': m.ping_number, 'scan_start_m': m.scan_start_m,
            'scan_length_m': m.scan_length_m, 'gain': m.gain_setting,
            'tx_us': m.transmit_duration, 'sos': m.speed_of_sound,
            'profile': base64.b64encode(bytes(m.profile)).decode(),
        })

    def _on_dvl(self, m: DvlData) -> None:
        self._count('dvl')
        if not self._throttle('dvl', float(self.get_parameter('dvl_max_rate_hz').value)):
            return
        self.hub.publish('dvl', {
            'stamp': _stamp(m), 'vx': _f(m.vx), 'vy': _f(m.vy), 'vz': _f(m.vz),
            'fom': _f(m.fom), 'altitude': _f(m.altitude), 'alt_src': m.altitude_source,
            'valid': m.velocity_valid, 'status': int(m.status),
            'sos': _f(m.sound_velocity), 'temp': _f(m.temperature), 'pres': _f(m.pressure),
            'beams': [{'id': b.id, 'v': _f(b.velocity), 'd': _f(b.distance),
                       'fom': _f(b.fom), 'rssi': _f(b.rssi), 'valid': b.valid}
                      for b in m.beams],
        })

    def _on_dvl_pos(self, m: DvlPosition) -> None:
        self._count('dvl_position')
        self.hub.publish('dvl_position', {
            'stamp': _stamp(m), 'x': _f(m.x), 'y': _f(m.y), 'z': _f(m.z), 'std': _f(m.std),
            'roll': _f(m.roll), 'pitch': _f(m.pitch), 'yaw': _f(m.yaw), 'status': m.status,
        })

    def _on_status(self, key: str, m: DiagnosticStatus) -> None:
        self.hub.publish(f'status_{key}', {
            'level': LEVELS.get(int.from_bytes(m.level, 'little')
                                if isinstance(m.level, bytes) else int(m.level), 'error'),
            'message': m.message, 'hardware_id': m.hardware_id, 'node': m.name,
            'values': {kv.key: kv.value for kv in m.values},
        })

    def _on_logger(self, m: LoggerStatus) -> None:
        self.hub.publish('logger', {
            'active': m.active, 'session': m.session_name, 'directory': m.directory,
            'elapsed_s': m.elapsed_s, 'bag': m.bag_recording,
            'rows': dict(zip(m.streams, [int(r) for r in m.rows])),
        })

    def _heartbeat(self) -> None:
        self.hub.publish('rx', {k: {'count': c, 'last': t} for k, (c, t) in self._rx.items()})

    # -------------------------------------------------------------- services
    def _client(self, srv_type, name):
        key = (srv_type, name)
        if key not in self._svc_clients:
            self._svc_clients[key] = self.create_client(srv_type, name, callback_group=self.cbg)
        return self._svc_clients[key]

    def _call(self, srv_type, name, req, timeout=5.0):
        cli = self._client(srv_type, name)
        if not cli.wait_for_service(timeout_sec=1.0):
            raise RuntimeError(f'service {name} not available - is the node running?')
        done = threading.Event()
        fut = cli.call_async(req)
        fut.add_done_callback(lambda _f: done.set())
        if not done.wait(timeout):
            raise RuntimeError(f'service {name} timed out')
        return fut.result()

    def _on_command(self, req: dict) -> dict:
        g = lambda n: self.get_parameter(n).value  # noqa: E731
        a = req.get('action')
        if a == 'log_start':
            r = StartLog.Request(session_name=str(req.get('name', '')),
                                 note=str(req.get('note', '')))
            res = self._call(StartLog, g('logger_node').rstrip('/') + '/start', r)
            return {'ok': res.success, 'message': res.message, 'directory': res.directory}
        if a == 'log_stop':
            res = self._call(Trigger, g('logger_node').rstrip('/') + '/stop', Trigger.Request())
            return {'ok': res.success, 'message': res.message}
        if a == 'dvl_reset':
            res = self._call(Trigger, g('dvl_node').rstrip('/') + '/reset_dead_reckoning',
                             Trigger.Request())
            return {'ok': res.success, 'message': res.message}
        if a == 'set_param':
            node = g(f"{req['sensor']}_node").rstrip('/')
            prm = Parameter(name=req['name'], value=_to_value(req['value'], req.get('type')))
            res = self._call(SetParameters, node + '/set_parameters',
                             SetParameters.Request(parameters=[prm]))
            r = res.results[0]
            return {'ok': r.successful, 'message': r.reason or f"{req['name']} set"}
        if a == 'get_params':
            node = g(f"{req['sensor']}_node").rstrip('/')
            names = list(req['names'])
            res = self._call(GetParameters, node + '/get_parameters',
                             GetParameters.Request(names=names), timeout=3.0)
            return {'ok': True, 'values': {n: _from_value(v) for n, v in zip(names, res.values)}}
        return {'ok': False, 'message': f'unknown action {a!r}'}

    def destroy_node(self):
        self.server.shutdown()
        return super().destroy_node()


def _to_value(v, typ=None) -> ParameterValue:
    pv = ParameterValue()
    if typ == 'bool' or isinstance(v, bool):
        pv.type, pv.bool_value = ParameterType.PARAMETER_BOOL, bool(v)
    elif typ == 'integer' or (typ is None and isinstance(v, int)):
        pv.type, pv.integer_value = ParameterType.PARAMETER_INTEGER, int(v)
    elif typ == 'double' or (typ is None and isinstance(v, float)):
        pv.type, pv.double_value = ParameterType.PARAMETER_DOUBLE, float(v)
    else:
        pv.type, pv.string_value = ParameterType.PARAMETER_STRING, str(v)
    return pv


def _from_value(pv: ParameterValue):
    return {
        ParameterType.PARAMETER_BOOL: pv.bool_value,
        ParameterType.PARAMETER_INTEGER: pv.integer_value,
        ParameterType.PARAMETER_DOUBLE: pv.double_value,
        ParameterType.PARAMETER_STRING: pv.string_value,
    }.get(pv.type)


def main(args=None):
    rclpy.init(args=args)
    node = DashboardNode()
    ex = rclpy.executors.MultiThreadedExecutor(num_threads=4)
    ex.add_node(node)
    try:
        ex.spin()
    except (KeyboardInterrupt, rclpy.executors.ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()
