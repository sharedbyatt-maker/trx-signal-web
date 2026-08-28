# -*- coding: utf-8 -*-
"""Engine self-test — run: python tests_engine.py"""
import os

os.environ["TRX_NO_ENGINE"] = "1"   # keep the polling engine off during tests

import random

import app as eng


def test_parse_history():
    items = [
        {"issueNumber": "20260824103010281", "number": "8", "blockTime": "2026-08-24 11:10:54"},
        {"issueNumber": "20260824103010280", "number": "3", "blockTime": "2026-08-24 11:09:54"},
        {"issueNumber": "20260824103010280", "number": "9", "blockTime": "2026-08-24 11:09:54"},  # dup
        {"issueNumber": "bad", "number": None},                                                    # junk
    ]
    rows = eng.parse_history(items)
    assert len(rows) == 2, f"dedupe/junk failed: {len(rows)}"
    assert rows[0]["issue_int"] < rows[1]["issue_int"], "sort failed"
    assert rows[1]["type"] == "BIG" and rows[0]["type"] == "SMALL"
    assert rows[1]["hm"] == "11:10"
    print("  parse_history .......... OK")


def test_ema_rsi_series():
    vals = [float(i % 7) for i in range(200)]
    e5 = eng.ema_series(vals, 5)
    e15 = eng.ema_series(vals, 15)
    assert e5[4] is not None and e5[3] is None, "ema seed index wrong"
    r = eng.rsi_series(list(range(200)))
    assert all(v is None or (0.0 <= v <= 100.0) for v in r), "rsi out of bounds"
    assert r[-1] == 100.0, "all-gains RSI must be 100"
    print("  ema/rsi series ......... OK")


def test_mtf_markov():
    m = [1 if i % 3 else -1 for i in range(500)]
    mt = eng.mtf_confluence(m)
    assert set(mt.keys()) == {"x5", "x15"} and all(v in (-1, 0, 1) for v in mt.values())
    parsed = [{"type": "BIG" if random.random() < 0.5 else "SMALL"} for _ in range(60)]
    mk = eng.markov_prob(parsed)
    assert mk["n"] > 0 and 0.0 <= mk["p_big"] <= 1.0
    print("  mtf/markov ............. OK")


def test_backtest():
    random.seed(42)
    parsed = []
    issue = 20260820103010001
    bt_time = "2026-08-20 10:00:00"
    for _ in range(600):
        n = random.randint(0, 9)
        parsed.append({
            "issue": str(issue), "short_issue": str(issue)[-6:], "issue_int": issue,
            "day_int": 20260820, "number": n,
            "type": "BIG" if n >= 5 else "SMALL",
            "block_time": bt_time, "hm": "10:00",
        })
        issue += 1
    res = eng.run_backtest(parsed)
    assert res is not None and res["rounds_tested"] > 200
    assert len(res["components"]) == 6
    for c in res["components"]:
        if c["calls"]:
            assert 0.0 <= c["wr"] <= 1.0
    tb = res["buckets"]["trade"]
    if tb["calls"]:
        assert 0.0 <= tb["wr"] <= 1.0
    print(f"  backtest ............... OK ({res['rounds_tested']} rounds, "
          f"trade calls {tb['calls']}, wr {tb['wr']})")


if __name__ == "__main__":
    print("ENGINE SELFTEST")
    test_parse_history()
    test_ema_rsi_series()
    test_mtf_markov()
    test_backtest()
    print("ALL TESTS PASSED")
