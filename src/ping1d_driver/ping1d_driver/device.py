"""ROS-free access layer for Blue Robotics Ping (Ping1D) and Ping2 echosounders.

Ping2 speaks the same Ping1D message set, so one class covers both.
`Ping1DSimulator` has the same interface for testing without hardware.
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass


@dataclass
class Ping1DSettings:
    speed_of_sound: float = 1500.0   # m/s
    auto_mode: bool = True
    scan_start_m: float = 0.0        # used when auto_mode is False
    scan_length_m: float = 30.0      # used when auto_mode is False
    gain_setting: int = 0            # 0..6, used when auto_mode is False
    ping_interval_ms: int = 100      # device-side ping interval
    profile: bool = True             # also fetch the echo profile


class Ping1DBase:
    def __init__(self) -> None:
        self.settings = Ping1DSettings()

    def configure(self, settings: Ping1DSettings) -> None:
        self.settings = settings
        self._apply()

    def _apply(self) -> None:
        pass

    def open(self) -> dict:
        raise NotImplementedError

    def read(self) -> dict | None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class Ping1DDevice(Ping1DBase):
    def __init__(self, connection: str = 'serial', port: str = '/dev/ttyUSB0',
                 baudrate: int = 115200, host: str = '192.168.2.2',
                 udp_port: int = 9090) -> None:
        super().__init__()
        self.connection = connection
        self.port = port
        self.baudrate = baudrate
        self.host = host
        self.udp_port = udp_port
        self._dev = None

    def _where(self) -> str:
        if self.connection == 'udp':
            return f'udp://{self.host}:{self.udp_port}'
        return f'{self.port}@{self.baudrate}'

    def open(self) -> dict:
        try:
            from brping import Ping1D
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "Python package 'bluerobotics-ping' is not installed. "
                "Run: pip install --break-system-packages bluerobotics-ping") from exc
        dev = Ping1D()
        if self.connection == 'udp':
            dev.connect_udp(self.host, self.udp_port)
        else:
            dev.connect_serial(self.port, self.baudrate)
        if dev.initialize() is False:
            raise RuntimeError(f'Ping1D/Ping2 did not answer on {self._where()}')
        self._dev = dev
        info = {'where': self._where()}
        try:
            fw = dev.get_firmware_version()
            if fw:
                info['firmware'] = f"{fw['firmware_version_major']}.{fw['firmware_version_minor']}"
                info['device_type'] = fw.get('device_type')
                info['device_model'] = fw.get('device_model')
        except Exception:
            pass
        return info

    def _apply(self) -> None:
        d, s = self._dev, self.settings
        if d is None:
            return
        # verify=False: brping's verify re-reads each value and Ping2 does not answer
        # every legacy Ping1D getter (-> AttributeError '_speed_of_sound' inside brping).
        steps = [
            ('speed_of_sound', lambda: d.set_speed_of_sound(int(s.speed_of_sound * 1000), verify=False)),
            ('ping_interval', lambda: d.set_ping_interval(int(s.ping_interval_ms), verify=False)),
            ('mode_auto', lambda: d.set_mode_auto(1 if s.auto_mode else 0, verify=False)),
        ]
        if not s.auto_mode:
            steps += [
                ('range', lambda: d.set_range(int(s.scan_start_m * 1000),
                                              int(s.scan_length_m * 1000), verify=False)),
                ('gain', lambda: d.set_gain_setting(int(s.gain_setting), verify=False)),
            ]
        steps.append(('ping_enable', lambda: d.set_ping_enable(1, verify=False)))
        self.apply_warnings = []
        for name, fn in steps:
            try:
                fn()
            except Exception as exc:  # noqa: BLE001 - setting not supported by this device
                self.apply_warnings.append(f'{name}: {exc}')

    def read(self) -> dict | None:
        d = self._dev
        if d is None:
            return None
        r = None
        if self.settings.profile:
            try:
                r = d.get_profile()
            except Exception:  # noqa: BLE001 - fall back to distance only
                r = None
        if r:
            prof = bytes(r.get('profile_data', b''))
        else:
            r = d.get_distance()
            if not r:
                return None
            prof = b''
        return {
            'distance_m': r['distance'] / 1000.0,
            'confidence': int(r['confidence']),
            'transmit_duration': int(r['transmit_duration']),
            'ping_number': int(r['ping_number']),
            'scan_start_m': r['scan_start'] / 1000.0,
            'scan_length_m': r['scan_length'] / 1000.0,
            'gain_setting': int(r['gain_setting']),
            'speed_of_sound': self.settings.speed_of_sound,
            'profile': prof,
        }

    def close(self) -> None:
        dev, self._dev = self._dev, None
        try:
            if dev is not None and hasattr(dev, 'iodev'):
                dev.iodev.close()
        except Exception:
            pass


class Ping1DSimulator(Ping1DBase):
    """Slowly varying seabed with occasional low-confidence dropouts."""

    PROFILE_LEN = 200

    def __init__(self, seed: int | None = None) -> None:
        super().__init__()
        self.rng = random.Random(seed)
        self.t0 = time.monotonic()
        self.n = 0
        self._last = 0.0

    def open(self) -> dict:
        return {'where': 'simulator', 'firmware': 'sim', 'device_model': 'sim'}

    def read(self) -> dict | None:
        dt = max(0.02, self.settings.ping_interval_ms / 1000.0)
        wait = self._last + dt - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()
        t = self._last - self.t0
        self.n += 1
        depth = 8.0 + 2.5 * math.sin(t / 9.0) + 0.6 * math.sin(t / 2.3) + self.rng.gauss(0, 0.03)
        conf = 100 if self.rng.random() > 0.05 else self.rng.randint(10, 60)
        s = self.settings
        if s.auto_mode:
            start, length = 0.0, max(5.0, math.ceil(depth * 1.6))
        else:
            start, length = s.scan_start_m, s.scan_length_m
        prof = b''
        if s.profile:
            out = bytearray(self.PROFILE_LEN)
            for i in range(self.PROFILE_LEN):
                r = start + (i + 0.5) * length / self.PROFILE_LEN
                v = 120 * math.exp(-r / 0.6) + 230 * math.exp(-((r - depth) / 0.25) ** 2)
                v += 60 * math.exp(-((r - 2 * depth) / 0.4) ** 2)          # second echo
                v += self.rng.gauss(10, 5)
                out[i] = max(0, min(255, int(v)))
            prof = bytes(out)
        return {
            'distance_m': depth, 'confidence': conf, 'transmit_duration': 100,
            'ping_number': self.n, 'scan_start_m': start, 'scan_length_m': length,
            'gain_setting': s.gain_setting, 'speed_of_sound': s.speed_of_sound,
            'profile': prof,
        }
