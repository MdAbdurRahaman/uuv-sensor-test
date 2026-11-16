"""ROS-free Ping360 access layer.

`Ping360Device` talks to real hardware through Blue Robotics' `brping` library.
`Ping360Simulator` produces synthetic scans with the same interface, so the
node, logger and dashboard can be tested with no sonar attached.

Both can be used outside ROS:

    dev = Ping360Device(connection="serial", port="/dev/ttyUSB0")
    dev.open(); dev.configure(Ping360Settings(range_m=20))
    scan = dev.ping(0)
"""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass

SAMPLE_PERIOD_TICK_S = 25e-9          # one sample-period tick = 25 ns
FIRMWARE_MIN_SAMPLE_PERIOD = 80       # ticks
FIRMWARE_MIN_TRANSMIT_DURATION = 5    # us
FIRMWARE_MAX_TRANSMIT_DURATION = 500  # us
FIRMWARE_MAX_SAMPLES = 1200
GRADIANS = 400


@dataclass
class Ping360Settings:
    range_m: float = 20.0
    gain_setting: int = 0              # 0 low, 1 normal, 2 high
    transmit_frequency: int = 750      # kHz
    number_of_samples: int = 1200
    speed_of_sound: float = 1500.0     # m/s
    transmit_duration: int = 0         # us, 0 = automatic
    mode: int = 1


def compute_timing(s: Ping360Settings) -> tuple[int, int, int]:
    """Return (number_of_samples, sample_period_ticks, transmit_duration_us)
    for the requested range, clamped to firmware limits.
    """
    n = max(200, min(int(s.number_of_samples), FIRMWARE_MAX_SAMPLES))
    period = 2.0 * s.range_m / (n * s.speed_of_sound * SAMPLE_PERIOD_TICK_S)
    period = int(round(period))
    if period < FIRMWARE_MIN_SAMPLE_PERIOD:
        period = FIRMWARE_MIN_SAMPLE_PERIOD
    period = min(period, 40000)

    if s.transmit_duration > 0:
        td = int(s.transmit_duration)
    else:
        # Same heuristic as Blue Robotics ping-viewer.
        td = int(round(8000.0 * s.range_m / s.speed_of_sound))
        td = max(td, int(math.ceil(2.5 * period * SAMPLE_PERIOD_TICK_S * 1e6)))
    td = max(FIRMWARE_MIN_TRANSMIT_DURATION, min(td, FIRMWARE_MAX_TRANSMIT_DURATION))
    return n, period, td


def range_from_timing(n: int, period_ticks: int, speed_of_sound: float) -> float:
    return n * period_ticks * SAMPLE_PERIOD_TICK_S * speed_of_sound / 2.0


def next_angle(angle: int, start: int, stop: int, step: int,
               mode: str = 'sweep', direction: int = 1) -> tuple[int, int]:
    """Advance the head angle (gradians). Returns (new_angle, new_direction).

    start == stop, or start..stop covering 399 gradians, means full 360 deg rotation.
    Otherwise the sector start -> stop (clockwise) is scanned, either restarting
    at `start` ('sweep') or reversing direction at the edges ('bounce').
    """
    start %= GRADIANS
    stop %= GRADIANS
    step = max(1, int(step))
    span = (stop - start) % GRADIANS
    if span == 0 or span >= GRADIANS - 1:
        return (angle + step) % GRADIANS, 1
    rel = (angle - start) % GRADIANS
    if rel > span:
        rel = -step if direction > 0 else span + step
    if mode == 'bounce':
        rel += step * direction
        if rel >= span:
            rel, direction = span, -1
        elif rel <= 0:
            rel, direction = 0, 1
    else:
        rel += step
        if rel > span:
            rel = 0
        direction = 1
    return (start + rel) % GRADIANS, direction


class Ping360Base:
    def __init__(self) -> None:
        self.settings = Ping360Settings()
        self.n = 1200
        self.period = 80
        self.td = 20

    def configure(self, settings: Ping360Settings) -> None:
        self.settings = settings
        self.n, self.period, self.td = compute_timing(settings)
        self._apply()

    def _apply(self) -> None:  # pragma: no cover - overridden
        pass

    def _result(self, angle: int, data: bytes, **over) -> dict:
        s = self.settings
        return {
            'angle': int(angle) % GRADIANS,
            'mode': over.get('mode', s.mode),
            'gain_setting': over.get('gain_setting', s.gain_setting),
            'transmit_duration': over.get('transmit_duration', self.td),
            'sample_period': over.get('sample_period', self.period),
            'transmit_frequency': over.get('transmit_frequency', s.transmit_frequency),
            'number_of_samples': over.get('number_of_samples', self.n),
            'speed_of_sound': s.speed_of_sound,
            'range_m': range_from_timing(
                over.get('number_of_samples', self.n),
                over.get('sample_period', self.period), s.speed_of_sound),
            'data': bytes(data),
        }

    def open(self) -> dict:
        raise NotImplementedError

    def ping(self, angle: int) -> dict | None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class Ping360Device(Ping360Base):
    """Real Ping360 over serial (USB/RS-485) or UDP (Ethernet version / BlueOS)."""

    def __init__(self, connection: str = 'serial', port: str = '/dev/ttyUSB0',
                 baudrate: int = 115200, host: str = '192.168.2.2',
                 udp_port: int = 12345) -> None:
        super().__init__()
        self.connection = connection
        self.port = port
        self.baudrate = baudrate
        self.host = host
        self.udp_port = udp_port
        self._dev = None

    def open(self) -> dict:
        try:
            from brping import Ping360
        except ImportError as exc:  # pragma: no cover - hardware path
            raise RuntimeError(
                "Python package 'bluerobotics-ping' is not installed. "
                "Run: pip install --break-system-packages bluerobotics-ping") from exc
        dev = Ping360()
        if self.connection == 'udp':
            dev.connect_udp(self.host, self.udp_port)
            ok = dev.initialize() is not False
        else:
            dev.connect_serial(self.port, self.baudrate)
            ok = dev.initialize() is not False
            if not ok and self.baudrate != 115200:
                # Ping360 auto-detects the baud rate; fall back if the adapter can't do the fast one
                try:
                    dev.iodev.close()
                except Exception:  # noqa: BLE001
                    pass
                dev = Ping360()
                dev.connect_serial(self.port, 115200)
                ok = dev.initialize() is not False
                if ok:
                    self.baudrate = 115200
        if not ok:
            raise RuntimeError(f'Ping360 did not answer on {self._where()}')
        self._dev = dev
        info = {'where': self._where()}
        try:
            v = dev.get_device_information()
            if v:
                info['firmware'] = '{}.{}.{}'.format(
                    v.get('firmware_version_major'), v.get('firmware_version_minor'),
                    v.get('firmware_version_patch'))
        except Exception:
            pass
        return info

    def _where(self) -> str:
        if self.connection == 'udp':
            return f'udp://{self.host}:{self.udp_port}'
        return f'{self.port}@{self.baudrate}'

    def _apply(self) -> None:
        if self._dev is None:
            return
        s = self.settings
        d = self._dev
        # brping caches these and sends them with every transducer command.
        d.set_mode(s.mode)
        d.set_gain_setting(s.gain_setting)
        d.set_transmit_frequency(s.transmit_frequency)
        d.set_number_of_samples(self.n)
        d.set_sample_period(self.period)
        d.set_transmit_duration(self.td)

    def ping(self, angle: int) -> dict | None:
        if self._dev is None:
            return None
        msg = self._dev.transmitAngle(int(angle) % GRADIANS)
        if msg is None:
            return None
        return self._result(
            msg.angle, msg.data,
            mode=msg.mode, gain_setting=msg.gain_setting,
            transmit_duration=msg.transmit_duration, sample_period=msg.sample_period,
            transmit_frequency=msg.transmit_frequency,
            number_of_samples=msg.number_of_samples)

    def close(self) -> None:
        dev, self._dev = self._dev, None
        try:
            if dev is not None and hasattr(dev, 'iodev'):
                dev.iodev.close()
        except Exception:
            pass


class Ping360Simulator(Ping360Base):
    """Synthetic tank: circular wall, a couple of targets and speckle noise."""

    def __init__(self, rate_hz: float = 40.0, seed: int | None = None) -> None:
        super().__init__()
        self.rate_hz = rate_hz
        self.rng = random.Random(seed)
        self._last = 0.0

    def open(self) -> dict:
        return {'where': 'simulator', 'firmware': 'sim'}

    def ping(self, angle: int) -> dict | None:
        # Real hardware takes ~25 ms per ping; mimic it so timing is realistic.
        dt = 1.0 / self.rate_hz
        wait = self._last + dt - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        self._last = time.monotonic()

        n = self.n
        rng_m = range_from_timing(n, self.period, self.settings.speed_of_sound)
        a = (angle % GRADIANS) * 2 * math.pi / GRADIANS
        wall = 0.7 * rng_m * (1 + 0.15 * math.sin(3 * a))
        targets = [(0.35 * rng_m, 0.6, 0.05), (0.55 * rng_m, 3.6, 0.08)]
        gain = (0.6, 1.0, 1.5)[max(0, min(2, self.settings.gain_setting))]
        out = bytearray(n)
        for i in range(n):
            r = (i + 0.5) * rng_m / n
            v = 40 * math.exp(-r / (0.08 * rng_m + 1e-6))          # near-field ringing
            v += 200 * math.exp(-((r - wall) / (0.015 * rng_m + 0.05)) ** 2)
            for tr, ta, tw in targets:
                da = math.atan2(math.sin(a - ta), math.cos(a - ta))
                if abs(da) < tw * 3:
                    v += 230 * math.exp(-(da / tw) ** 2) * math.exp(
                        -((r - tr) / (0.01 * rng_m + 0.05)) ** 2)
            v = v * gain + self.rng.gauss(8, 6)
            out[i] = max(0, min(255, int(v)))
        return self._result(angle, bytes(out))
