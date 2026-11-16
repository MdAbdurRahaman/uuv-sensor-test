
import math
import struct
import time

from dvl_driver.nortek_nucleus import (ID_AHRS, ID_ALTIMETER, ID_BOTTOM_TRACK, NortekNucleus,
                                       NucleusParser, NucleusSimulator, build_ahrs_record,
                                       build_altimeter_record, build_bottom_track_record,
                                       build_packet, decode_ahrs, decode_bottom_track,
                                       nucleus_checksum)


def test_checksum_even_odd():
    assert nucleus_checksum(b'') == 0xB58C
    assert nucleus_checksum(b'\x01\x02') == (0xB58C + 0x0201) & 0xFFFF
    assert nucleus_checksum(b'\x01\x02\x03') == (0xB58C + 0x0201 + 0x0300) & 0xFFFF


def test_bottom_track_roundtrip():
    rec = build_bottom_track_record(1700000000.25, 0.5, -0.1, 0.02, [3.2, 3.3, 3.1],
                                    [0.17, 0.18, 0.16], fom=0.003, temp=12.5, pres=1.2)
    e = decode_bottom_track(rec)
    assert e['velocity_valid']
    assert abs(e['vx'] - 0.5) < 1e-6 and abs(e['vy'] + 0.1) < 1e-6
    assert abs(e['fom'] - 0.003) < 1e-6
    assert abs(e['temperature'] - 12.5) < 1e-6 and abs(e['pressure'] - 1.2) < 1e-6
    assert len(e['beams']) == 3 and all(b['valid'] for b in e['beams'])
    assert abs(e['altitude'] - 3.2 * math.cos(math.radians(20))) < 1e-3
    assert abs(e['time_of_validity'] - 1700000000.25) < 1e-3


def test_bottom_track_invalid():
    e = decode_bottom_track(build_bottom_track_record(0, 0, 0, 0, [1, 1, 1], [0, 0, 0],
                                                      valid=False))
    assert not e['velocity_valid'] and e['altitude'] == -1.0
    assert math.isnan(e['fom'])


def test_parser_handles_noise_split_and_bad_checksum():
    good = build_packet(ID_BOTTOM_TRACK, build_bottom_track_record(
        1.0, 0.1, 0.2, 0.3, [2, 2, 2], [0, 0, 0]))
    bad = bytearray(good)
    bad[-5] ^= 0xFF                                  # corrupt data -> dropped
    stream = b'OK\r\n\xa5garbage' + bytes(bad) + good + b'\xa5' + good
    p = NucleusParser()
    out = []
    for i in range(0, len(stream), 7):               # tiny chunks
        out += p.feed(stream[i:i + 7])
    assert [r for r, _ in out] == [ID_BOTTOM_TRACK, ID_BOTTOM_TRACK]
    assert p.bad_checksums == 1
    assert 'OK' in p.text


def test_ahrs_and_altimeter_feed_velocity_event():
    n = NortekNucleus(connection='tcp')
    t = time.time()
    stream = (build_packet(ID_AHRS, build_ahrs_record(t, 1.0, -2.0, 90.0)) +
              build_packet(ID_ALTIMETER, build_altimeter_record(t, 4.25)) +
              build_packet(ID_BOTTOM_TRACK, build_bottom_track_record(
                  t, 1.0, 0.0, 0.0, [5, 5, 5], [0, 0, 0])))
    ev = n.process(stream)
    vel = [e for e in ev if e['kind'] == 'velocity'][0]
    assert vel['altitude'] == 4.25 and vel['altitude_source'] == 'altimeter'
    a = decode_ahrs(build_ahrs_record(t, 1.0, -2.0, 90.0))
    assert abs(a['heading'] - 90) < 1e-4 and abs(a['roll'] - 1) < 1e-6


def test_dead_reckoning_uses_heading():
    n = NortekNucleus(connection='tcp')
    t = time.time()
    n.process(build_packet(ID_AHRS, build_ahrs_record(t, 0, 0, 90.0)))   # facing east
    pkt = build_packet(ID_BOTTOM_TRACK, build_bottom_track_record(t, 1.0, 0, 0, [5] * 3, [0] * 3))
    n.process(pkt)
    n._t_last -= 1.0                                 # pretend 1 s passed
    n._last_pos_pub = 0
    pos = [e for e in n.process(pkt) if e['kind'] == 'position'][0]
    assert abs(pos['y'] - 1.0) < 0.05 and abs(pos['x']) < 0.05   # moved east
    n.reset_dead_reckoning()
    assert n._x == n._y == 0


def test_simulator_end_to_end():
    s = NucleusSimulator(rate_hz=200, seed=1)
    s.open()
    kinds = [e['kind'] for _ in range(5) for e in s.read()]
    assert kinds.count('velocity') == 5 and 'position' in kinds
    assert s.parser.bad_checksums == 0
