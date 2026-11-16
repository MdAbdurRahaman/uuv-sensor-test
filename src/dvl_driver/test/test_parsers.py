import json

from dvl_driver.device import (DvlSimulator, _crc8, parse_waterlinked_json,
                               parse_waterlinked_serial)

VEL = {
    "time": 106.3, "vx": -3.36e-05, "vy": 5.27e-05, "vz": 2.42e-05, "fom": 0.00027,
    "covariance": [[2.6e-07, -3.7e-09, -4.8e-09], [-3.7e-09, 2.6e-07, 1.0e-09],
                   [-4.8e-09, 1.0e-09, 7.4e-08]],
    "altitude": 0.4111, "transducers": [
        {"id": 0, "velocity": 0.0006, "distance": 0.4669, "rssi": -30.3, "nsd": -88.1,
         "beam_valid": True}],
    "velocity_valid": True, "status": 0, "format": "json_v3.1", "type": "velocity",
    "time_of_validity": 1638191471563017, "time_of_transmission": 1638191471752336,
}


def test_json_velocity():
    e = parse_waterlinked_json(json.dumps(VEL))
    assert e['kind'] == 'velocity' and e['velocity_valid']
    assert abs(e['altitude'] - 0.4111) < 1e-9
    assert len(e['covariance']) == 9 and e['beams'][0]['valid']
    assert 1.6e9 < e['time_of_validity'] < 1.7e9


def test_json_position_and_garbage():
    e = parse_waterlinked_json('{"type":"position_local","x":1.5,"y":-2,"z":0.1,'
                               '"std":0.2,"roll":1,"pitch":2,"yaw":90,"status":0}')
    assert e['kind'] == 'position' and e['y'] == -2
    assert parse_waterlinked_json('not json') is None
    assert parse_waterlinked_json('{"type":"unknown"}') is None


def test_serial_wrz_wrp():
    body = ('wrz,0.120,0.001,0.002,y,1.30,0.002,'
            '1e-5;0;0;0;1e-5;0;0;0;1e-5,7000000,7100000,123.4,0')
    line = f'{body}*{_crc8(body.encode()):02x}'
    e = parse_waterlinked_serial(line, verify_checksum=True)
    assert e['kind'] == 'velocity' and e['velocity_valid'] and abs(e['vx'] - 0.12) < 1e-9
    assert parse_waterlinked_serial(body + '*00', verify_checksum=True) is None
    p = parse_waterlinked_serial('wrp,49056.809,0.41,0.15,1.75,2.0,0.2,0.1,31.9,0*c2')
    assert p['kind'] == 'position' and abs(p['yaw'] - 31.9) < 1e-9


def test_simulator():
    s = DvlSimulator(rate_hz=500, seed=3)
    s.open()
    kinds = [e['kind'] for _ in range(4) for e in s.read()]
    assert 'velocity' in kinds and 'position' in kinds
