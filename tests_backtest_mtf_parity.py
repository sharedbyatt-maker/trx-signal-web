import os
import random
import time

os.environ["TRX_NO_ENGINE"] = "1"

import app
import app_core as core


def prefix_signs(values, step):
    groups = [sum(values[k:k + step]) for k in range(0, len(values) - step + 1, step)]
    fast = core.ema_series(groups, core.FAST_EMA)
    slow = core.ema_series(groups, core.SLOW_EMA)
    out = [0] * (len(values) + 1)
    for prefix_len in range(step * core.SLOW_EMA, len(values) + 1):
        idx = prefix_len // step - 1
        if fast[idx] is not None and slow[idx] is not None:
            out[prefix_len] = 1 if fast[idx] > slow[idx] else -1
    return out


def test_precomputed_mtf_is_identical_to_frozen_causal_function():
    rng = random.Random(20260920)
    values = [rng.choice((-1, 1)) for _ in range(1800)]
    five = prefix_signs(values, 5)
    fifteen = prefix_signs(values, 15)
    for i in range(1, len(values) + 1):
        expected = core.mtf_confluence(values[:i])
        assert {"x5": five[i], "x15": fifteen[i]} == expected, i


def test_full_backtest_no_longer_blocks_cold_start():
    rng = random.Random(7)
    rows = []
    for i in range(13_500):
        number = rng.randrange(10)
        rows.append({"issue": str(20260920000000000 + i), "number": number,
                     "type": "BIG" if number >= 5 else "SMALL"})
    started = time.monotonic()
    result = app.run_backtest(rows)
    elapsed = time.monotonic() - started
    assert result and result["rounds_tested"] > 10_000
    assert elapsed < 8.0, elapsed


if __name__ == "__main__":
    test_precomputed_mtf_is_identical_to_frozen_causal_function()
    test_full_backtest_no_longer_blocks_cold_start()
    print("BACKTEST MTF PARITY/LATENCY TESTS: ALL PASSED")
