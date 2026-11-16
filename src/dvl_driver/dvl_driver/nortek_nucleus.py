"""ROS-free driver for the Nortek Nucleus1000 DVL (native binary protocol).

Format source: Nortek "Nucleus Operations and Integration" manual, ch. 8
"Binary data formats".

Packet = header (10 bytes) + data record
  header: 0xA5 sync | header size | data series id | family (0x20) |
          uint16 data size | uint16 data checksum | uint16 header checksum
  checksum: start 0xB58C, add little-endian 16-bit words, odd last byte << 8, & 0xFFFF

Records used here
  0xB4 BottomTrackData   3-beam + XYZ velocity, distances, uncertainty (FOM), T, p, c
  0xAA AltimeterData     vertical-beam distance to seabed
  0xD2 AhrsDataV2        roll / pitch / heading, rotation matrix body->NED, depth
Other records (IMU, magnetometer, water track, ...) are skipped.

Connections
  tcp:    data port 9002 (no password, max 2 clients). If `send_start` is set,
          the command port 9000 (password, default "nortek") is used to send
          init commands and START.
  serial: 115200 baud, commands and data on the same port.

The Nucleus has no dead-reckoning output in these records, so this class
integrates bottom-track velocity with the AHRS rotation to give a local
x(north)/y(east) track; `reset_dead_reckoning()` zeroes it.
"""

from __future__ import annotations

import math
import socket
import struct
import time

SYNC = 0xA5
FAMILY_NUCLEUS = 0x20
HEADER_SIZE = 10
ID_BOTTOM_TRACK = 0xB4
ID_ALTIMETER = 0xAA
ID_AHRS = 0xD2
ID_STRING = 0xA0
INVALID_VELOCITY = -32.768
INVALID_FOM = 10.0

# BottomTrackData status bits
BT_BEAM_VEL_VALID = (0, 1, 2)
BT_BEAM_DIST_VALID = (3, 4, 5)
BT_XYZ_VEL_VALID = (9, 10, 11)
BT_XYZ_FOM_VALID = (12, 13, 14)
BT_PRESSURE_VALID = 16
BT_TEMPERATURE_VALID = 17


def nucleus_checksum(data: bytes) -> int:
    cs = 0xB58C
    n = len(data)
    for i in range(0, n - 1, 2):
        cs += data[i] | (data[i + 1] << 8)
    if n % 2:
        cs += data[-1] << 8
    return cs & 0xFFFF


def build_packet(record_id: int, record: bytes) -> bytes:
    """Make a packet (used by tests and the simulator)."""
    head = struct.pack('<BBBBHH', SYNC, HEADER_SIZE, record_id, FAMILY_NUCLEUS,
                       len(record), nucleus_checksum(record))
    return head + struct.pack('<H', nucleus_checksum(head)) + record


class NucleusParser:
    """Feed raw bytes, get complete (record_id, record_bytes) tuples back.

    Non-packet bytes (e.g. ASCII command replies on serial) are skipped and
    collected in `self.text` so command responses can still be read.
    """

    def __init__(self) -> None:
        self.buf = bytearray()
        self.bad_checksums = 0
        self.text = ''

    def feed(self, chunk: bytes) -> list[tuple[int, bytes]]:
        self.buf += chunk
        out = []
        while True:
            i = self.buf.find(bytes([SYNC]))
            if i < 0:
                self._text(self.buf)
                self.buf.clear()
                break
            if i:
                self._text(self.buf[:i])
                del self.buf[:i]
            if len(self.buf) < HEADER_SIZE:
                break
            hsize = self.buf[1]
            if hsize < HEADER_SIZE or hsize > 32:
                del self.buf[:1]
                continue
            if len(self.buf) < hsize:
                break
            head = bytes(self.buf[:hsize])
            (hcs,) = struct.unpack_from('<H', head, hsize - 2)
            if nucleus_checksum(head[:hsize - 2]) != hcs:
                del self.buf[:1]
                continue
            rid, fam, dsize, dcs = struct.unpack_from('<BBHH', head, 2)
            if len(self.buf) < hsize + dsize:
                break
            data = bytes(self.buf[hsize:hsize + dsize])
            del self.buf[:hsize + dsize]
            if nucleus_checksum(data) != dcs:
                self.bad_checksums += 1
                continue
            if fam == FAMILY_NUCLEUS:
                out.append((rid, data))
        if len(self.buf) > 1 << 20:
            self.buf.clear()
        return out

    def _text(self, b) -> None:
        if b:
            self.text = (self.text + bytes(b).decode('ascii', 'ignore'))[-4096:]


def _bits(mask: int, bits) -> bool:
    return all(mask >> b & 1 for b in bits)


def _common(rec: bytes) -> tuple[int, int, float]:
    version, offset, flags = rec[0], rec[1], rec[2]
    ts, us = struct.unpack_from('<II', rec, 4)
    return version, offset, ts + us * 1e-6


def decode_bottom_track(rec: bytes) -> dict | None:
    if len(rec) < 124:
        return None
    _, _, t = _common(rec)
    (status,) = struct.unpack_from('<I', rec, 12)
    (serial,) = struct.unpack_from('<I', rec, 16)
    sos, temp, pres = struct.unpack_from('<3f', rec, 24)
    bvel = struct.unpack_from('<3f', rec, 36)
    bdist = struct.unpack_from('<3f', rec, 48)
    bfom = struct.unpack_from('<3f', rec, 60)
    vx, vy, vz = struct.unpack_from('<3f', rec, 96)
    fx, fy, fz = struct.unpack_from('<3f', rec, 108)
    valid = _bits(status, BT_XYZ_VEL_VALID) and INVALID_VELOCITY not in (vx, vy, vz)
    fom_ok = _bits(status, BT_XYZ_FOM_VALID)
    foms = [f for f in (fx, fy, fz) if f < INVALID_FOM] if fom_ok else []
    beams = []
    for i in range(3):
        v_ok = bool(status >> BT_BEAM_VEL_VALID[i] & 1)
        d_ok = bool(status >> BT_BEAM_DIST_VALID[i] & 1)
        beams.append({'id': i, 'velocity': bvel[i] if v_ok else float('nan'),
                      'distance': bdist[i] if d_ok else float('nan'),
                      'rssi': float('nan'), 'nsd': float('nan'),
                      'fom': bfom[i] if bfom[i] < INVALID_FOM else float('nan'),
                      'valid': v_ok and d_ok})
    dists = [b['distance'] for b in beams if b['valid']]
    # slant beams are 20 deg from vertical (Nucleus1000)
    alt = (sum(dists) / len(dists)) * math.cos(math.radians(20.0)) if dists else -1.0
    cov = [0.0] * 9
    for k, f in enumerate((fx, fy, fz)):
        cov[k * 4] = f * f if fom_ok and f < INVALID_FOM else -1.0
    return {
        'kind': 'velocity', 'vx': vx, 'vy': vy, 'vz': vz,
        'fom': max(foms) if foms else float('nan'), 'covariance': cov,
        'altitude': alt, 'altitude_source': 'bottom_track',
        'velocity_valid': valid, 'status': status, 'time_of_validity': t,
        'beams': beams, 'serial': serial, 'sound_velocity': sos,
        'temperature': temp if status >> BT_TEMPERATURE_VALID & 1 else float('nan'),
        'pressure': pres if status >> BT_PRESSURE_VALID & 1 else float('nan'),
    }


def decode_altimeter(rec: bytes) -> dict | None:
    if len(rec) < 40:
        return None
    _, _, t = _common(rec)
    (status,) = struct.unpack_from('<I', rec, 12)
    (dist,) = struct.unpack_from('<f', rec, 36)
    return {'kind': 'altimeter', 'distance': dist, 'valid': bool(status & 1), 'time': t}


def decode_ahrs(rec: bytes) -> dict | None:
    _, off, t = _common(rec)
    if off < 12 or len(rec) < off + 72:
        return None
    (mode,) = struct.unpack_from('<B', rec, 24)
    (fom,) = struct.unpack_from('<f', rec, 28)
    roll, pitch, heading = struct.unpack_from('<3f', rec, off)
    quat = struct.unpack_from('<4f', rec, off + 12)
    rbn = struct.unpack_from('<9f', rec, off + 28)
    (depth,) = struct.unpack_from('<f', rec, off + 68)
    return {'kind': 'ahrs', 'roll': roll, 'pitch': pitch, 'heading': heading,
            'quaternion': quat, 'rbn': rbn, 'depth': depth, 'fom': fom,
            'mode': mode, 'time': t}


class NortekNucleus:
    """Nucleus1000 reader with the same interface as the other DVL classes."""

    def __init__(self, connection: str = 'tcp', host: str = '192.168.2.201',
                 data_port: int = 9002, command_port: int = 9000,
                 password: str = 'nortek', port: str = '/dev/ttyUSB2',
                 baudrate: int = 115200, send_start: bool = False,
                 init_commands: list[str] | None = None, stop_on_close: bool = False,
                 timeout: float = 3.0) -> None:
        self.connection = connection
        self.host, self.data_port, self.command_port = host, data_port, command_port
        self.password = password
        self.port, self.baudrate = port, baudrate
        self.send_start = send_start
        self.init_commands = [c for c in (init_commands or []) if c.strip()]
        self.stop_on_close = stop_on_close
        self.timeout = timeout
        self.parser = NucleusParser()
        self._data = None          # socket or serial
        self._cmd = None           # command socket (tcp only)
        self._ahrs = None
        self._alt = None
        self._x = self._y = self._z = 0.0
        self._t_last = None
        self._dr_dist = 0.0
        self._last_pos_pub = 0.0
        self._started = False

    # ------------------------------------------------------------ transport
    def _where(self) -> str:
        if self.connection == 'serial':
            return f'{self.port}@{self.baudrate}'
        return f'tcp://{self.host}:{self.data_port}'

    def open(self) -> dict:
        if self.connection == 'serial':
            import serial  # python3-serial
            self._data = serial.Serial(self.port, self.baudrate, timeout=0.2)
            if self.send_start:
                self._serial_cmd(['STOP'] + self.init_commands + ['START'])
        else:
            if self.send_start:
                self._tcp_login_and_start()
            self._data = socket.create_connection((self.host, self.data_port), timeout=5.0)
            self._data.settimeout(self.timeout)
        return {'where': self._where(), 'protocol': 'nortek_nucleus'}

    def _tcp_login_and_start(self) -> None:
        s = socket.create_connection((self.host, self.command_port), timeout=5.0)
        s.settimeout(2.0)
        buf = self._recv_until(s, (b'assword',), 3.0)
        if b'assword' in buf:
            s.sendall(self.password.encode() + b'\r\n')
            reply = self._recv_until(s, (b'\n',), 3.0)
            if b'nvalid' in reply or b'rror' in reply:
                s.close()
                raise RuntimeError('Nucleus rejected the command-port password')
        self._cmd = s
        for c in ['STOP'] + self.init_commands + ['START']:
            s.sendall(c.strip().encode() + b'\r\n')
            reply = self._recv_until(s, (b'OK', b'ERROR'), 3.0)
            if c != 'STOP' and b'ERROR' in reply:
                raise RuntimeError(f'Nucleus command {c!r} failed: {reply!r}')
        self._started = True

    @staticmethod
    def _recv_until(s, tokens, timeout) -> bytes:
        buf, t0 = b'', time.monotonic()
        while time.monotonic() - t0 < timeout:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                break
            if not chunk:
                break
            buf += chunk
            if any(t in buf for t in tokens):
                break
        return buf

    def _serial_cmd(self, cmds) -> None:
        for c in cmds:
            self.parser.text = ''
            self._data.write(c.strip().encode() + b'\r\n')
            t0 = time.monotonic()
            while time.monotonic() - t0 < 3.0:
                self.parser.feed(self._data.read(self._data.in_waiting or 1))
                if 'OK' in self.parser.text or 'ERROR' in self.parser.text:
                    break
            if c != 'STOP' and 'ERROR' in self.parser.text:
                raise RuntimeError(f'Nucleus command {c!r} failed: {self.parser.text[-80:]!r}')
        self._started = True

    def _recv(self) -> bytes:
        if self.connection == 'serial':
            t0 = time.monotonic()
            while True:
                chunk = self._data.read(self._data.in_waiting or 1)
                if chunk:
                    return chunk
                if time.monotonic() - t0 > self.timeout:
                    raise TimeoutError(f'no data from Nucleus for {self.timeout:.1f} s '
                                       '(is it measuring? try send_start: true)')
        try:
            chunk = self._data.recv(65536)
        except socket.timeout:
            raise TimeoutError(f'no data from Nucleus for {self.timeout:.1f} s '
                               '(is it measuring? try send_start: true)')
        if not chunk:
            raise ConnectionError('Nucleus closed the connection')
        return chunk

    # ----------------------------------------------------------------- data
    def read(self) -> list[dict]:
        return self.process(self._recv())

    def process(self, chunk: bytes) -> list[dict]:
        events = []
        for rid, rec in self.parser.feed(chunk):
            if rid == ID_AHRS:
                a = decode_ahrs(rec)
                if a:
                    self._ahrs = a
            elif rid == ID_ALTIMETER:
                a = decode_altimeter(rec)
                if a:
                    self._alt = (time.monotonic(), a)
            elif rid == ID_BOTTOM_TRACK:
                e = decode_bottom_track(rec)
                if not e:
                    continue
                if self._alt and time.monotonic() - self._alt[0] < 2.0 and self._alt[1]['valid']:
                    e['altitude'] = self._alt[1]['distance']
                    e['altitude_source'] = 'altimeter'
                events.append(e)
                pos = self._integrate(e)
                if pos:
                    events.append(pos)
        return events

    def _integrate(self, e: dict) -> dict | None:
        now = time.monotonic()
        dt = 0.0 if self._t_last is None else min(now - self._t_last, 1.0)
        self._t_last = now
        if e['velocity_valid'] and dt > 0:
            v = (e['vx'], e['vy'], e['vz'])
            if self._ahrs:
                r = self._ahrs['rbn']                  # body -> NED, row major
                n = [r[i * 3] * v[0] + r[i * 3 + 1] * v[1] + r[i * 3 + 2] * v[2]
                     for i in range(3)]
            else:
                n = list(v)
            self._x += n[0] * dt
            self._y += n[1] * dt
            self._z += n[2] * dt
            self._dr_dist += math.sqrt(sum(c * c for c in n)) * dt
        if now - self._last_pos_pub < 0.2:            # 5 Hz is plenty
            return None
        self._last_pos_pub = now
        a = self._ahrs or {}
        return {'kind': 'position', 'x': self._x, 'y': self._y, 'z': self._z,
                'std': 0.01 * self._dr_dist,           # rough: ~1 % of distance travelled
                'roll': a.get('roll', 0.0), 'pitch': a.get('pitch', 0.0),
                'yaw': a.get('heading', 0.0), 'status': 0 if a else 1}

    def reset_dead_reckoning(self) -> None:
        self._x = self._y = self._z = self._dr_dist = 0.0

    def close(self) -> None:
        if self.stop_on_close and self._started:
            try:
                if self._cmd is not None:
                    self._cmd.sendall(b'STOP\r\n')
                elif self.connection == 'serial' and self._data is not None:
                    self._data.write(b'STOP\r\n')
            except Exception:  # noqa: BLE001
                pass
        for h in (self._data, self._cmd):
            try:
                if h is not None:
                    h.close()
            except Exception:  # noqa: BLE001
                pass
        self._data = self._cmd = None


# ------------------------------------------------------------------ builders
# Inverse of the decoders; used by the simulator and the unit tests.
def _common_bytes(t: float, offset: int) -> bytes:
    sec = int(t)
    return struct.pack('<BBBxII', 1, offset, 1, sec, int((t - sec) * 1e6))


def build_bottom_track_record(t, vx, vy, vz, dists, beam_vels, fom=0.002, valid=True,
                              sos=1500.0, temp=20.0, pres=0.5, serial=1234) -> bytes:
    status = (1 << BT_PRESSURE_VALID) | (1 << BT_TEMPERATURE_VALID)
    if valid:
        for b in BT_BEAM_VEL_VALID + BT_BEAM_DIST_VALID + BT_XYZ_VEL_VALID + BT_XYZ_FOM_VALID:
            status |= 1 << b
        status |= 0b111 << 6                                   # beam FOM valid
    else:
        vx = vy = vz = INVALID_VELOCITY
        beam_vels = [INVALID_VELOCITY] * 3
        dists = [0.0] * 3
        fom = INVALID_FOM
    rec = bytearray(_common_bytes(t, 12))
    rec += struct.pack('<II', status, serial) + b'\0' * 4
    rec += struct.pack('<3f', sos, temp, pres)
    rec += struct.pack('<3f', *beam_vels) + struct.pack('<3f', *dists)
    rec += struct.pack('<3f', fom, fom, fom)
    rec += struct.pack('<3f', 0.01, 0.01, 0.01) + struct.pack('<3f', 0.0, 0.0, 0.0)
    rec += struct.pack('<3f', vx, vy, vz) + struct.pack('<3f', fom, fom, fom)
    rec += struct.pack('<f', 0.01) + b'\0' * 4
    return bytes(rec)


def build_altimeter_record(t, dist, valid=True) -> bytes:
    rec = bytearray(_common_bytes(t, 12))
    rec += struct.pack('<II', 0b11 if valid else 0, 1234) + b'\0' * 4
    rec += struct.pack('<3f', 1500.0, 20.0, 0.5) + struct.pack('<f', dist)
    return bytes(rec)


def build_ahrs_record(t, roll, pitch, heading, depth=0.5) -> bytes:
    off = 36
    rec = bytearray(_common_bytes(t, off))
    rec += b'\0' * 4 + struct.pack('<I', 1234) + b'\0' * 4      # 12..23
    rec += struct.pack('<B3x', 2) + struct.pack('<ff', 0.5, 0.5)  # 24..35
    h = math.radians(heading)
    rbn = (math.cos(h), -math.sin(h), 0.0, math.sin(h), math.cos(h), 0.0, 0.0, 0.0, 1.0)
    q = (math.cos(h / 2), 0.0, 0.0, math.sin(h / 2))
    rec += struct.pack('<3f', roll, pitch, heading) + struct.pack('<4f', *q)
    rec += struct.pack('<9f', *rbn) + struct.pack('<ff', 0.0, depth)
    return bytes(rec)


class NucleusSimulator(NortekNucleus):
    """Generates real Nucleus binary packets (incl. checksums) and runs them
    through the same parser as the hardware path. ~8 Hz bottom track."""

    def __init__(self, rate_hz: float = 8.0, seed: int | None = None) -> None:
        super().__init__(connection='sim')
        import random
        self.rng = random.Random(seed)
        self.rate_hz = rate_hz
        self.t0 = time.monotonic()
        self._next = 0.0
        self._heading = 0.0

    def open(self) -> dict:
        return {'where': 'simulator (Nucleus binary)', 'protocol': 'nortek_nucleus'}

    def _recv(self) -> bytes:
        wait = self._next - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._next = time.monotonic() + 1.0 / self.rate_hz
        t = time.monotonic() - self.t0
        g = self.rng.gauss
        target = 0.0 if int(t // 30) % 2 == 0 else 180.0
        self._heading += ((target - self._heading + 180) % 360 - 180) * 0.05
        alt = 3.0 + 0.8 * math.sin(t / 6.0) + g(0, 0.02)
        valid = self.rng.random() > 0.03
        vx, vy, vz = 0.5 + g(0, 0.01), 0.05 * math.sin(t / 3) + g(0, 0.01), g(0, 0.005)
        slant = alt / math.cos(math.radians(20.0))
        wall = time.time()
        out = build_packet(ID_AHRS, build_ahrs_record(wall, g(0, 0.3), g(0, 0.3),
                                                      self._heading % 360))
        out += build_packet(ID_ALTIMETER, build_altimeter_record(wall, alt))
        out += build_packet(ID_BOTTOM_TRACK, build_bottom_track_record(
            wall, vx, vy, vz, [slant + g(0, 0.02) for _ in range(3)],
            [vx * 0.34 + g(0, 0.01) for _ in range(3)], valid=valid,
            temp=18.5 + 0.1 * math.sin(t / 50), pres=0.3 + 0.01 * math.sin(t / 7)))
        return out
