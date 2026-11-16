"""ROS-free CSV session writer.

    s = LogSession('/home/me/sensor_logs', 'tank_test_1', note='gain 1')
    s.write('ping1d', {'t': 1.0, 'distance_m': 3.2})
    s.close()

Each stream gets its own CSV file; the header is taken from the first row.
A `session_info.json` file records start/stop time, note and row counts.
"""

from __future__ import annotations

import csv
import json
import os
import re
import threading
import time
from datetime import datetime


def safe_name(name: str) -> str:
    name = re.sub(r'[^A-Za-z0-9_.-]+', '_', name.strip()).strip('._')
    return name[:80]


class LogSession:
    def __init__(self, root: str, name: str = '', note: str = '',
                 flush_every_s: float = 1.0, extra_info: dict | None = None) -> None:
        stamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name = safe_name(name)
        self.name = f'{stamp}_{name}' if name else stamp
        self.directory = os.path.abspath(os.path.join(os.path.expanduser(root), self.name))
        os.makedirs(self.directory, exist_ok=False)
        self.note = note
        self.t_start = time.time()
        self.t_stop = None
        self.flush_every_s = flush_every_s
        self._lock = threading.Lock()
        self._files: dict[str, tuple] = {}
        self.rows: dict[str, int] = {}
        self._last_flush = time.monotonic()
        self.extra_info = extra_info or {}
        self._write_info()

    def write(self, stream: str, row: dict) -> None:
        with self._lock:
            if self.t_stop is not None:
                return
            if stream not in self._files:
                path = os.path.join(self.directory, f'{stream}.csv')
                fh = open(path, 'w', newline='', encoding='utf-8')
                w = csv.DictWriter(fh, fieldnames=list(row.keys()), extrasaction='ignore')
                w.writeheader()
                self._files[stream] = (fh, w)
                self.rows[stream] = 0
            fh, w = self._files[stream]
            w.writerow(row)
            self.rows[stream] += 1
            now = time.monotonic()
            if now - self._last_flush >= self.flush_every_s:
                self._last_flush = now
                for f, _ in self._files.values():
                    f.flush()

    @property
    def elapsed(self) -> float:
        return (self.t_stop or time.time()) - self.t_start

    def files(self) -> list[str]:
        return sorted(os.listdir(self.directory))

    def _write_info(self) -> None:
        info = {
            'session': self.name, 'note': self.note,
            'started': datetime.fromtimestamp(self.t_start).isoformat(timespec='seconds'),
            'stopped': datetime.fromtimestamp(self.t_stop).isoformat(timespec='seconds')
            if self.t_stop else None,
            'duration_s': round(self.elapsed, 2), 'rows': dict(self.rows),
            'format': {
                'intensities_hex / profile_hex': 'bytes as hex string, '
                'decode with bytes.fromhex() or numpy.frombuffer(bytes.fromhex(s), "u1")',
                'stamp': 'ROS header time, seconds since epoch',
            },
            **self.extra_info,
        }
        with open(os.path.join(self.directory, 'session_info.json'), 'w') as fh:
            json.dump(info, fh, indent=2)

    def close(self) -> None:
        with self._lock:
            if self.t_stop is not None:
                return
            self.t_stop = time.time()
            for fh, _ in self._files.values():
                fh.close()
            self._files.clear()
            self._write_info()


# ---------------------------------------------------------------- row builders
# Plain dict in, dict out, so they can be unit-tested without ROS.
def ping360_row(stamp: float, m, store_intensities: bool = True) -> dict:
    row = {
        'stamp': f'{stamp:.6f}', 'angle_grad': m.angle, 'angle_deg': f'{m.angle_deg:.2f}',
        'range_m': f'{m.range_m:.3f}', 'gain_setting': m.gain_setting,
        'transmit_frequency_khz': m.transmit_frequency,
        'transmit_duration_us': m.transmit_duration, 'sample_period_ticks': m.sample_period,
        'number_of_samples': m.number_of_samples, 'speed_of_sound': m.speed_of_sound,
    }
    if store_intensities:
        row['intensities_hex'] = bytes(m.intensities).hex()
    return row


def ping1d_row(stamp: float, m, store_profile: bool = True) -> dict:
    row = {
        'stamp': f'{stamp:.6f}', 'distance_m': f'{m.distance_m:.4f}',
        'confidence': m.confidence, 'transmit_duration_us': m.transmit_duration,
        'ping_number': m.ping_number, 'scan_start_m': f'{m.scan_start_m:.3f}',
        'scan_length_m': f'{m.scan_length_m:.3f}', 'gain_setting': m.gain_setting,
        'speed_of_sound': m.speed_of_sound,
    }
    if store_profile:
        row['profile_hex'] = bytes(m.profile).hex()
    return row


def dvl_row(stamp: float, m, max_beams: int = 4) -> dict:
    row = {
        'stamp': f'{stamp:.6f}', 'vx': f'{m.vx:.5f}', 'vy': f'{m.vy:.5f}',
        'vz': f'{m.vz:.5f}', 'fom': f'{m.fom:.5f}', 'altitude_m': f'{m.altitude:.3f}',
        'altitude_source': getattr(m, 'altitude_source', ''),
        'velocity_valid': int(m.velocity_valid), 'status_hex': f'{int(m.status):08x}',
        'sound_velocity': f"{getattr(m, 'sound_velocity', float('nan')):.2f}",
        'temperature_c': f"{getattr(m, 'temperature', float('nan')):.3f}",
        'pressure_bar': f"{getattr(m, 'pressure', float('nan')):.4f}",
        'time_of_validity': f'{m.time_of_validity:.6f}',
        'covariance': ';'.join(f'{c:.3e}' for c in m.covariance),
    }
    beams = list(m.beams)
    for i in range(max_beams):
        b = beams[i] if i < len(beams) else None
        row[f'b{i}_velocity'] = f'{b.velocity:.4f}' if b else ''
        row[f'b{i}_distance'] = f'{b.distance:.3f}' if b else ''
        row[f'b{i}_fom'] = f"{getattr(b, 'fom', float('nan')):.4f}" if b else ''
        row[f'b{i}_rssi'] = f'{b.rssi:.1f}' if b else ''
        row[f'b{i}_valid'] = int(b.valid) if b else ''
    return row


def dvl_position_row(stamp: float, m) -> dict:
    return {'stamp': f'{stamp:.6f}', 'x': f'{m.x:.4f}', 'y': f'{m.y:.4f}', 'z': f'{m.z:.4f}',
            'std': f'{m.std:.4f}', 'roll': f'{m.roll:.2f}', 'pitch': f'{m.pitch:.2f}',
            'yaw': f'{m.yaw:.2f}', 'status': m.status}
