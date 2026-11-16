#!/usr/bin/env python3
"""Offline report for one sensor_logger session (no ROS needed).

    python3 tools/plot_session.py ~/sensor_logs/20261115_152845_tank_test

Writes <session>/report.png with: Ping360 sonar image (last full turn),
Ping1D distance + echogram, DVL velocities and dead-reckoning track.
Needs numpy and matplotlib (sudo apt install python3-numpy python3-matplotlib).
"""

import csv
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

S1, S2, S3 = '#2a78d6', '#eb6834', '#1baf7a'


def read(path):
    if not os.path.isfile(path):
        return []
    with open(path, newline='') as fh:
        return list(csv.DictReader(fh))


def col(rows, k, cast=float):
    return np.array([cast(r[k]) if r[k] != '' else np.nan for r in rows])


def main(session):
    p360 = read(os.path.join(session, 'ping360.csv'))
    p1d = read(os.path.join(session, 'ping1d.csv'))
    dvl = read(os.path.join(session, 'dvl.csv'))
    pos = read(os.path.join(session, 'dvl_position.csv'))

    fig = plt.figure(figsize=(14, 9), constrained_layout=True)
    gs = fig.add_gridspec(3, 2)
    fig.suptitle(os.path.basename(os.path.normpath(session)))

    ax = fig.add_subplot(gs[:2, 0], projection='polar')
    if p360 and 'intensities_hex' in p360[0]:
        last = {}
        for r in p360:                                # keep newest ping per angle
            last[int(r['angle_grad'])] = r
        n = max(len(r['intensities_hex']) // 2 for r in last.values())
        img = np.zeros((400, n), dtype=np.uint8)
        for a, r in last.items():
            v = np.frombuffer(bytes.fromhex(r['intensities_hex']), dtype=np.uint8)
            img[a, :len(v)] = v
        rng = float(p360[-1]['range_m'])
        theta = np.linspace(0, 2 * np.pi, 401)
        rad = np.linspace(0, rng, n + 1)
        ax.pcolormesh(theta, rad, img.T, cmap='Blues_r', shading='flat')
        ax.set_theta_zero_location('N')
        ax.set_theta_direction(-1)
        ax.set_title(f'Ping360 - {len(p360)} pings, range {rng:.1f} m')
    else:
        ax.set_title('Ping360 - no data')

    ax = fig.add_subplot(gs[0, 1])
    if p1d:
        t = col(p1d, 'stamp')
        t -= t[0]
        ax.plot(t, col(p1d, 'distance_m'), color=S1, lw=1.5)
        ax.invert_yaxis()
        ax.set_ylabel('distance (m)')
        ax.set_title(f'Ping1D - {len(p1d)} readings, '
                     f"mean confidence {col(p1d, 'confidence').mean():.0f} %")
    ax.grid(alpha=.3)

    ax = fig.add_subplot(gs[1, 1])
    if p1d and p1d[0].get('profile_hex'):
        profs = [np.frombuffer(bytes.fromhex(r['profile_hex']), dtype=np.uint8) for r in p1d]
        depth = max(float(r['scan_start_m']) + float(r['scan_length_m']) for r in p1d)
        grid = np.zeros((200, len(profs)), dtype=np.uint8)
        ys = np.linspace(0, depth, 200)
        for i, (r, pr) in enumerate(zip(p1d, profs)):
            s0, ln = float(r['scan_start_m']), float(r['scan_length_m'])
            idx = ((ys - s0) / ln * len(pr)).astype(int)
            ok = (idx >= 0) & (idx < len(pr))
            grid[ok, i] = pr[idx[ok]]
        ax.imshow(grid, aspect='auto', cmap='Blues_r', extent=[0, t[-1], depth, 0])
        ax.set_ylabel('depth (m)')
        ax.set_title('Ping1D echogram')

    ax = fig.add_subplot(gs[2, 0])
    if dvl:
        t = col(dvl, 'stamp')
        t -= t[0]
        ok = col(dvl, 'velocity_valid') > 0
        for k, c in (('vx', S1), ('vy', S2), ('vz', S3)):
            v = col(dvl, k)
            v[~ok] = np.nan
            ax.plot(t, v, color=c, lw=1.5, label=k)
        ax.legend(loc='center right', frameon=False, ncol=3)
        ax.set_ylabel('m/s')
        ax.set_xlabel('time (s)')
        ax.set_title(f'DVL - {len(dvl)} reports, {100 * ok.mean():.0f} % with bottom lock')
    ax.grid(alpha=.3)

    ax = fig.add_subplot(gs[2, 1])
    if pos:
        ax.plot(col(pos, 'y'), col(pos, 'x'), color=S1, lw=1.5)
        ax.set_aspect('equal', 'datalim')
        ax.set_xlabel('y / east (m)')
        ax.set_ylabel('x / north (m)')
        ax.set_title('DVL dead reckoning')
    ax.grid(alpha=.3)

    out = os.path.join(session, 'report.png')
    fig.savefig(out, dpi=110)
    print('wrote', out)


if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    main(os.path.expanduser(sys.argv[1]))
