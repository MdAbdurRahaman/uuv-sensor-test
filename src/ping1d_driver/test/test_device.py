from ping1d_driver.device import Ping1DSettings, Ping1DSimulator


def test_simulator():
    s = Ping1DSimulator(seed=2)
    s.open()
    s.configure(Ping1DSettings(ping_interval_ms=20))
    r = s.read()
    assert 3 < r['distance_m'] < 13
    assert 0 <= r['confidence'] <= 100
    assert len(r['profile']) == Ping1DSimulator.PROFILE_LEN
    s.configure(Ping1DSettings(ping_interval_ms=20, profile=False))
    assert s.read()['profile'] == b''
