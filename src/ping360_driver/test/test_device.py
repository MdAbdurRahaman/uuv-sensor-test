from ping360_driver.device import (Ping360Settings, Ping360Simulator, compute_timing,
                                   next_angle, range_from_timing)


def test_timing_matches_range():
    for rng in (2.0, 10.0, 20.0, 50.0):
        n, period, td = compute_timing(Ping360Settings(range_m=rng))
        assert 80 <= period
        assert 5 <= td <= 500
        assert abs(range_from_timing(n, period, 1500.0) - rng) / rng < 0.02


def test_short_range_clamps_sample_period():
    n, period, _ = compute_timing(Ping360Settings(range_m=0.5))
    assert period == 80


def test_full_rotation_wraps():
    assert next_angle(399, 0, 399, 1) == (0, 1)
    assert next_angle(398, 0, 399, 5) == (3, 1)


def test_sector_sweep_and_bounce():
    a, d = 95, 1
    seen = []
    for _ in range(20):
        a, d = next_angle(a, 90, 110, 5, 'sweep', d)
        seen.append(a)
    assert min(seen) == 90 and max(seen) == 110
    a, d = 100, 1
    seen = []
    for _ in range(20):
        a, d = next_angle(a, 90, 110, 5, 'bounce', d)
        seen.append(a)
    assert set(seen) <= {90, 95, 100, 105, 110} and 90 in seen and 110 in seen


def test_sector_across_zero():
    a, d, seen = 395, 1, set()
    for _ in range(30):
        a, d = next_angle(a, 380, 20, 5, 'sweep', d)
        seen.add(a)
    assert all(a >= 380 or a <= 20 for a in seen)


def test_simulator_output():
    s = Ping360Simulator(rate_hz=1000, seed=1)
    s.open()
    s.configure(Ping360Settings(range_m=10, number_of_samples=400))
    r = s.ping(50)
    assert r['angle'] == 50 and len(r['data']) == 400
    assert abs(r['range_m'] - 10) < 0.3
