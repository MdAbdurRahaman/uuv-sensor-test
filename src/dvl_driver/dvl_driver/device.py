"""ROS-free DVL access layer.

Supported protocols (select with the `protocol` parameter):

  nortek_nucleus      Nortek Nucleus1000, native binary over TCP or serial (nortek_nucleus.py)
  waterlinked_tcp     Water Linked DVL A50 / A125 JSON stream over TCP (default port 16171)
  waterlinked_serial  Water Linked serial protocol ("wrz" velocity / "wrp" position lines)
  sim                 built-in simulator (generates Nucleus binary packets)
  sim_waterlinked     simple simulator in the Water Linked style

Each reader returns a list of events:
  {'kind': 'velocity', vx, vy, vz, fom, covariance[9], altitude, velocity_valid,
   status, time_of_validity, beams[...]}
  {'kind': 'position', x, y, z, std, roll, pitch, yaw, status}

Adding another DVL (Nortek, Teledyne PD6, ...) = one new class with
open()/read()/reset_dead_reckoning()/close().
"""

from __future__ import annotations

import json
import math
import random
import socket
import time


# --------------------------------------------------------------------- parsers
def parse_waterlinked_json(line: str) -> dict | None:
    """Parse one JSON line from a Water Linked DVL (protocol v2.x / json_v3.x)."""
    line = line.strip()
    if not line:
        return None
    try:
        d = json.loads(line)
    except ValueError:
        return None
    t = d.get('type')
    if t == 'velocity' or (t is None and 'vx' in d):
        cov = d.get('covariance') or [[0.0] * 3] * 3
        flat = [float(v) for row in cov for v in row] if isinstance(cov[0], list) \
            else [float(v) for v in cov]
        beams = []
        for b in d.get('transducers', []) or []:
            beams.append({
                'id': int(b.get('id', 0)), 'velocity': float(b.get('velocity', 0.0)),
                'distance': float(b.get('distance', 0.0)), 'rssi': float(b.get('rssi', 0.0)),
                'nsd': float(b.get('nsd', 0.0)), 'valid': bool(b.get('beam_valid', False)),
            })
        tov = d.get('time_of_validity', 0) or 0
        return {
            'kind': 'velocity',
            'vx': float(d.get('vx', 0.0)), 'vy': float(d.get('vy', 0.0)),
            'vz': float(d.get('vz', 0.0)), 'fom': float(d.get('fom', 0.0)),
            'covariance': (flat + [0.0] * 9)[:9],
            'altitude': float(d.get('altitude', -1.0)),
            'velocity_valid': bool(d.get('velocity_valid', False)),
            'status': int(d.get('status', 0)),
            'time_of_validity': float(tov) / 1e6 if tov > 1e12 else float(tov),
            'beams': beams,
        }
    if t == 'position_local':
        return {
            'kind': 'position',
            'x': float(d.get('x', 0.0)), 'y': float(d.get('y', 0.0)),
            'z': float(d.get('z', 0.0)), 'std': float(d.get('std', 0.0)),
            'roll': float(d.get('roll', 0.0)), 'pitch': float(d.get('pitch', 0.0)),
            'yaw': float(d.get('yaw', 0.0)), 'status': int(d.get('status', 0)),
        }
    if t == 'response':
        return {'kind': 'response', 'response_to': d.get('response_to'),
                'success': bool(d.get('success')), 'error': d.get('error_message', '')}
    return None


def _crc8(data: bytes) -> int:
    crc = 0
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = ((crc << 1) ^ 0x07) & 0xFF if crc & 0x80 else (crc << 1) & 0xFF
    return crc


def parse_waterlinked_serial(line: str, verify_checksum: bool = False) -> dict | None:
    """Parse a Water Linked serial report: `wrz,...*cs` (velocity) or `wrp,...*cs`."""
    line = line.strip()
    if not line.startswith(('wrz', 'wrp')):
        return None
    body, _, cs = line.partition('*')
    if verify_checksum and cs:
        try:
            if _crc8(body.encode()) != int(cs[:2], 16):
                return None
        except ValueError:
            return None
    f = body.split(',')
    try:
        if f[0] == 'wrz' and len(f) >= 12:
            cov = [float(v) for v in f[7].split(';')] if f[7] else [0.0] * 9
            return {
                'kind': 'velocity', 'vx': float(f[1]), 'vy': float(f[2]), 'vz': float(f[3]),
                'velocity_valid': f[4].strip().lower() == 'y', 'altitude': float(f[5]),
                'fom': float(f[6]), 'covariance': (cov + [0.0] * 9)[:9],
                'time_of_validity': float(f[8]) / 1e6, 'status': int(f[11]), 'beams': [],
            }
        if f[0] == 'wrp' and len(f) >= 10:
            return {
                'kind': 'position', 'x': float(f[2]), 'y': float(f[3]), 'z': float(f[4]),
                'std': float(f[5]), 'roll': float(f[6]), 'pitch': float(f[7]),
                'yaw': float(f[8]), 'status': int(f[9]),
            }
    except (ValueError, IndexError):
        return None
    return None


# --------------------------------------------------------------------- readers
class _LineReader:
    def __init__(self) -> None:
        self._buf = b''

    def _feed(self, chunk: bytes) -> list[str]:
        self._buf += chunk
        if len(self._buf) > 1 << 20:              # garbage guard
            self._buf = self._buf[-4096:]
        *lines, self._buf = self._buf.split(b'\n')
        return [ln.decode('utf-8', 'replace') for ln in lines]


class WaterLinkedTcp(_LineReader):
    def __init__(self, host: str = '192.168.194.95', port: int = 16171,
                 timeout: float = 2.0) -> None:
        super().__init__()
        self.host, self.port, self.timeout = host, port, timeout
        self._sock = None

    def open(self) -> dict:
        self._sock = socket.create_connection((self.host, self.port), timeout=5.0)
        self._sock.settimeout(self.timeout)
        return {'where': f'tcp://{self.host}:{self.port}', 'protocol': 'waterlinked_tcp'}

    def read(self) -> list[dict]:
        try:
            chunk = self._sock.recv(65536)
        except socket.timeout:
            raise TimeoutError(f'no data from DVL for {self.timeout:.1f} s')
        if not chunk:
            raise ConnectionError('DVL closed the connection')
        return [e for e in map(parse_waterlinked_json, self._feed(chunk)) if e]

    def reset_dead_reckoning(self) -> None:
        self._sock.sendall(b'{"command": "reset_dead_reckoning"}\n')

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            finally:
                self._sock = None


class WaterLinkedSerial(_LineReader):
    def __init__(self, port: str = '/dev/ttyUSB2', baudrate: int = 115200,
                 timeout: float = 2.0, verify_checksum: bool = False) -> None:
        super().__init__()
        self.port, self.baudrate, self.timeout = port, baudrate, timeout
        self.verify = verify_checksum
        self._ser = None

    def open(self) -> dict:
        import serial  # python3-serial
        self._ser = serial.Serial(self.port, self.baudrate, timeout=0.2)
        return {'where': f'{self.port}@{self.baudrate}', 'protocol': 'waterlinked_serial'}

    def read(self) -> list[dict]:
        t0 = time.monotonic()
        while True:
            chunk = self._ser.read(self._ser.in_waiting or 1)
            if chunk:
                lines = self._feed(chunk)
                if lines:
                    return [e for e in (parse_waterlinked_serial(ln, self.verify)
                                        for ln in lines) if e]
            elif time.monotonic() - t0 > self.timeout:
                raise TimeoutError(f'no data from DVL for {self.timeout:.1f} s')

    def reset_dead_reckoning(self) -> None:
        self._ser.write(b'wcr\n')

    def close(self) -> None:
        if self._ser:
            try:
                self._ser.close()
            finally:
                self._ser = None


class DvlSimulator:
    """Vehicle doing a slow lawn-mower pattern over a sloping seabed at ~8 Hz."""

    def __init__(self, rate_hz: float = 8.0, seed: int | None = None) -> None:
        self.rate_hz = rate_hz
        self.rng = random.Random(seed)
        self.t0 = time.monotonic()
        self._last = 0.0
        self._x = self._y = self._yaw = 0.0
        self._n = 0

    def open(self) -> dict:
        return {'where': 'simulator', 'protocol': 'sim'}

    def read(self) -> list[dict]:
        dt = 1.0 / self.rate_hz
        wait = self._last + dt - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        now = time.monotonic()
        step = dt if not self._last else now - self._last
        self._last = now
        t = now - self.t0
        self._n += 1
        g = self.rng.gauss
        leg = int(t // 30) % 2
        yaw_target = 0.0 if leg == 0 else math.pi
        self._yaw += (yaw_target - self._yaw) * 0.05
        speed = 0.5
        vx, vy, vz = speed + g(0, 0.01), 0.05 * math.sin(t / 3) + g(0, 0.01), g(0, 0.005)
        self._x += (vx * math.cos(self._yaw) - vy * math.sin(self._yaw)) * step
        self._y += (vx * math.sin(self._yaw) + vy * math.cos(self._yaw)) * step
        alt = 3.0 + 0.8 * math.sin(self._x / 6.0) + g(0, 0.02)
        valid = self.rng.random() > 0.03
        beams = []
        for i in range(4):
            beams.append({'id': i, 'velocity': vx * 0.5 + g(0, 0.01),
                          'distance': alt / math.cos(math.radians(22.5)) + g(0, 0.02),
                          'rssi': -35 + g(0, 2), 'nsd': -100 + g(0, 2), 'valid': valid})
        ev = [{
            'kind': 'velocity', 'vx': vx, 'vy': vy, 'vz': vz, 'fom': 0.002 + abs(g(0, 0.001)),
            'covariance': [1e-5, 0, 0, 0, 1e-5, 0, 0, 0, 1e-5], 'altitude': alt,
            'velocity_valid': valid, 'status': 0, 'time_of_validity': time.time(),
            'beams': beams,
        }]
        if self._n % 2 == 0:
            ev.append({'kind': 'position', 'x': self._x, 'y': self._y, 'z': 0.0,
                       'std': 0.01 * t ** 0.5, 'roll': g(0, 0.3), 'pitch': g(0, 0.3),
                       'yaw': math.degrees(self._yaw), 'status': 0})
        return ev

    def reset_dead_reckoning(self) -> None:
        self._x = self._y = 0.0

    def close(self) -> None:
        pass


def make_dvl(protocol: str, **kw):
    if protocol == 'sim':
        from .nortek_nucleus import NucleusSimulator
        return NucleusSimulator()
    if protocol == 'sim_waterlinked':
        return DvlSimulator()
    if protocol == 'nortek_nucleus':
        from .nortek_nucleus import NortekNucleus
        return NortekNucleus(
            connection=kw.get('connection', 'tcp'), host=kw.get('host', '192.168.2.201'),
            data_port=int(kw.get('data_port', 9002)),
            command_port=int(kw.get('command_port', 9000)),
            password=kw.get('password', 'nortek'), port=kw.get('port', '/dev/ttyUSB2'),
            baudrate=int(kw.get('baudrate', 115200)),
            send_start=bool(kw.get('send_start', False)),
            init_commands=list(kw.get('init_commands') or []),
            stop_on_close=bool(kw.get('stop_on_close', False)),
            timeout=float(kw.get('timeout_s', 3.0)))
    if protocol == 'waterlinked_tcp':
        return WaterLinkedTcp(host=kw.get('host', '192.168.194.95'),
                              port=int(kw.get('tcp_port', 16171)),
                              timeout=float(kw.get('timeout_s', 2.0)))
    if protocol == 'waterlinked_serial':
        return WaterLinkedSerial(port=kw.get('port', '/dev/ttyUSB2'),
                                 baudrate=int(kw.get('baudrate', 115200)),
                                 timeout=float(kw.get('timeout_s', 2.0)),
                                 verify_checksum=bool(kw.get('verify_checksum', False)))
    raise ValueError(f'unknown DVL protocol: {protocol!r}')
