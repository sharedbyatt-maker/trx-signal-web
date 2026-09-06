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


def test_shared_decision_policy():
    # score-qualified normal BIG trade
    d = eng.decide_signal(60, 0.10, 1, {"x5": 1, "x15": 1}, 40, 22)
    assert d["signal"] == "BIG" and d["kind"] == "trade"

    # reversal guard blocks a score-qualified trade
    d = eng.decide_signal(60, -0.10, 1, {"x5": 1, "x15": 1}, 40, 22)
    assert d["signal"] == "SKIP (REVERSAL GUARD)"
    assert d["kind"] == "reversal_guard"

    # MTF disagreement inside the +15 buffer is WATCH, not a trade
    d = eng.decide_signal(50, 0.10, 1, {"x5": -1, "x15": 1}, 40, 22)
    assert d["signal"] == "SKIP (WATCH)" and d["kind"] == "mtf_guard"

    # Very strong score is allowed through the MTF buffer, matching live policy
    d = eng.decide_signal(56, 0.10, 1, {"x5": -1, "x15": -1}, 40, 22)
    assert d["signal"] == "BIG" and d["kind"] == "trade"

    # Watch and no-signal zones
    d = eng.decide_signal(30, 0.0, 1, {"x5": 0, "x15": 0}, 40, 22)
    assert d["signal"] == "SKIP (WATCH)" and d["kind"] == "watch"
    d = eng.decide_signal(10, 0.0, 1, {"x5": 0, "x15": 0}, 40, 22)
    assert d["signal"] == "SKIP" and d["kind"] == "skip"
    print("  shared decision ........ OK")


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
    assert "guards" in res and set(res["guards"]) == {"reversal", "mtf"}
    for c in res["components"]:
        if c["calls"]:
            assert 0.0 <= c["wr"] <= 1.0
    tb = res["buckets"]["trade"]
    if tb["calls"]:
        assert 0.0 <= tb["wr"] <= 1.0
    print(f"  backtest ............... OK ({res['rounds_tested']} rounds, "
          f"trade calls {tb['calls']}, wr {tb['wr']}, guards {res['guards']})")


def test_rsi_alert_state():
    A = {"armed_up": True, "armed_down": True, "up_ts": 0.0, "down_ts": 0.0}
    F = lambda a: (a["armed_up"], a["armed_down"], a["up_ts"], a["down_ts"])

    # 1) reach 60 → exactly one enter_up
    m, *st = eng.rsi_alert_state(61.0, 60.0, 40.0, True, True, 0, 0, t0 := 100.0)
    assert len(m) == 1 and m[0][0] == "enter_up", m
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))

    # 2) oscillation around 60 (59.8/60.2/60.9) → NO more messages (armed off)
    for r in (59.8, 60.2, 60.9, 59.9, 60.4):
        m, *st = eng.rsi_alert_state(r, 60.0, 40.0, *F(A), t0 + 5)
        assert not m, f"oscillation spam at rsi={r}: {m}"
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))

    # 3) reminder only after remind_sec while staying above
    m, *st = eng.rsi_alert_state(62.0, 60.0, 40.0, *F(A), t0 + 100)  # < 300s
    assert not m
    m, *st = eng.rsi_alert_state(62.0, 60.0, 40.0, *F(A), t0 + 401)
    assert len(m) == 1 and m[0][0] == "remind_up"
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))

    # 4) shallow dip (59.0, < 2pt hysteresis) → NOT re-armed → back to 61: no msg
    m, *st = eng.rsi_alert_state(59.0, 60.0, 40.0, *F(A), t0 + 500)
    assert not m
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))
    m, *st = eng.rsi_alert_state(61.0, 60.0, 40.0, *F(A), t0 + 560)
    assert not m, "shallow dip must not re-arm"
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))

    # 5) REAL pullback (57.5 < 58) → re-armed → next reach 61 sends again
    m, *st = eng.rsi_alert_state(57.5, 60.0, 40.0, *F(A), t0 + 600)
    assert not m
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))
    m, *st = eng.rsi_alert_state(61.0, 60.0, 40.0, *F(A), t0 + 660)
    assert len(m) == 1 and m[0][0] == "enter_up", "fresh reach must notify"
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))

    # 6) down side: reach 40 → enter_down; deep bounce (42.5) re-arms; 39.5 again → enter
    m, *st = eng.rsi_alert_state(39.5, 60.0, 40.0, *F(A), t0 + 700)
    assert len(m) == 1 and m[0][0] == "enter_down"
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))
    m, *st = eng.rsi_alert_state(42.5, 60.0, 40.0, *F(A), t0 + 760)
    assert not m
    A.update(dict(zip(("armed_up", "armed_down", "up_ts", "down_ts"), st)))
    m, *st = eng.rsi_alert_state(39.5, 60.0, 40.0, *F(A), t0 + 820)
    assert len(m) == 1 and m[0][0] == "enter_down"
    print("  rsi_alert_state ........ OK")


if __name__ == "__main__":
    print("ENGINE SELFTEST")
    test_parse_history()
    test_ema_rsi_series()
    test_mtf_markov()
    test_shared_decision_policy()
    test_rsi_alert_state()
    test_backtest()
    print("ALL TESTS PASSED")
