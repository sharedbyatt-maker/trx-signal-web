from drawings_persistence import _sanitize_drawings


def test_fibonacci_mode_survives_server_roundtrip():
    for mode in ('up', 'down', 'manual'):
        drawing = {'type': 'fib', 'id': 'fib-mode', 'fibMode': mode,
                   'points': [{'p': 100, 't': 1}, {'p': 120, 't': 2}]}
        assert _sanitize_drawings([drawing])[0]['fibMode'] == mode
    drawing['fibMode'] = 'invalid'
    assert _sanitize_drawings([drawing])[0]['fibMode'] == 'manual'
