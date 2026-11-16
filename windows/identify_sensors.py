#!/usr/bin/env python3
"""Find which serial port is the Ping360 and which is the Ping/Ping2, and write
them into test_bench.yaml.  Usage: identify_sensors.py <test_bench.yaml>"""
import glob, os, re, sys, time

def ports():
    by_id = sorted(glob.glob('/dev/serial/by-id/*'))
    if by_id:
        return by_id
    return sorted(glob.glob('/dev/ttyUSB*') + glob.glob('/dev/ttyACM*'))

def probe(port):
    try:
        from brping import Ping1D, Ping360
    except ImportError:
        print('  brping not installed'); return None
    # Ping1D / Ping2 answer the Ping1D-specific distance request; Ping360 does not.
    try:
        p = Ping1D(); p.connect_serial(port, 115200)
        if p.initialize() is not False and p.get_distance():
            p.iodev.close(); return 'ping1d'
        p.iodev.close()
    except Exception as e:
        print('  ', port, 'Ping1D probe:', e)
    time.sleep(0.3)
    try:
        p = Ping360(); p.connect_serial(port, 115200)
        ok = p.initialize() is not False
        info = None
        try: info = p.get_device_information()
        except Exception: pass
        p.iodev.close()
        if ok and (not info or info.get('device_type') == 2):
            return 'ping360'
    except Exception as e:
        print('  ', port, 'Ping360 probe:', e)
    return None

def set_port(text, node, port):
    pat = re.compile(r'(^/%s:\n(?:[ \t].*\n|\n)*?[ \t]+port:[ \t]*)(\S+)' % node, re.M)
    new, n = pat.subn(lambda m: m.group(1) + port, text, count=1)
    return new if n else text

def main(yaml_path):
    found = {}
    ps = ports()
    if not ps:
        print('No serial devices in WSL. Run 4_ATTACH_USB_SENSORS.bat first.'); return 1
    for port in ps:
        kind = probe(port)
        print(f'  {port} -> {kind or "unknown"}')
        if kind and kind not in found:
            found[kind] = port
    if not found:
        print('Could not identify any sensor (are they powered?)'); return 1
    text = open(yaml_path).read()
    for kind, port in found.items():
        text = set_port(text, kind, port)
    open(yaml_path, 'w', newline='').write(text.replace('\r\n', '\n').replace('\n', '\r\n'))
    print('Updated', yaml_path, found)
    return 0

if __name__ == '__main__':
    sys.exit(main(sys.argv[1]))
