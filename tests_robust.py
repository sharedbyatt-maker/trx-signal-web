# -*- coding: utf-8 -*-
import json
import tempfile
import time
from pathlib import Path

import robust_engine as re
import robust_integration as ri


def make_history(n=140, start=20260906000000):
    digits = [1, 8, 2, 7, 0, 9, 3, 6, 4, 5]
    rows = []
    for i in range(n):
        num = digits[i % len(digits)]
        rows.append({"issue": str(start + i), "number": num,
                     "type": "BIG" if num >= 5 else "SMALL",
                     "date": "2026-09-06", "block_time": "2026-09-06 10:00:00"})
    return rows


def force_signal(value="BIG"):
    original = re.signal_for_next
    re.signal_for_next = lambda history: {"signal": value, "ready": True, "score": 50.0,
                                          "walk_rsi": 40.0, "vol": 3.0, "components": {}}
    return original


def add_result(history, typ):
    num = 8 if typ == "BIG" else 1
    history.append({"issue": str(int(history[-1]["issue"]) + 1), "number": num, "type": typ,
                    "date": "2026-09-06", "block_time": "2026-09-06 10:00:00"})


def test_signal_batch_parity():
    h = make_history(180)
    for n in (106, 120, 150, 179):
        prefix = h[:n]
        live = re.signal_for_next(prefix)["signal"]
        dummy = {"issue": str(int(prefix[-1]["issue"]) + 1), "number": 0,
                 "type": "SMALL", "date": prefix[-1]["date"]}
        ext = prefix + [dummy]
        feat = re.precompute_features(ext)
        batch = re.build_signals(ext, feat)[-1] or "NO TRADE"
        assert live == batch


def test_paroli_loss_risk_dd_and_persistence():
    original = force_signal("BIG")
    try:
        with tempfile.TemporaryDirectory() as td:
            p = Path(td) / "state.json"
            eng = re.RobustEngine(p)
            h = make_history(110)
            eng.process_snapshot(h, str(int(h[-1]["issue"]) + 1))
            assert eng.snapshot()["pending"]["stake"] == 1000
            for expected in (2000, 4000, 8000):
                add_result(h, "BIG")
                eng.process_snapshot(h, str(int(h[-1]["issue"]) + 1))
                assert eng.snapshot()["pending"]["stake"] == expected
            add_result(h, "BIG")
            eng.process_snapshot(h, str(int(h[-1]["issue"]) + 1))
            s = eng.snapshot()
            assert s["wins"] == 4 and s["paroli_step"] == 0 and s["current_stake"] == 1000
            assert s["daily_stopped"] is True and s["pending"] is None

            p2 = Path(td) / "loss.json"
            e2 = re.RobustEngine(p2)
            h2 = make_history(110)
            e2.process_snapshot(h2, str(int(h2[-1]["issue"]) + 1))
            add_result(h2, "SMALL")
            e2.process_snapshot(h2, str(int(h2[-1]["issue"]) + 1))
            assert e2.snapshot()["paroli_step"] == 0
            assert e2.snapshot()["pending"]["stake"] == 1000

            with e2.lock:
                e2.state["daily_profit"] = -7500
                e2.state["pending"] = None
                e2._arm_next_locked(re.normalize_history(h2), str(int(h2[-1]["issue"]) + 1))
                assert e2.state["status"] == "DAILY STOP"

                e2.state["daily_profit"] = 0
                e2.state["daily_stopped"] = False
                e2.state["bankroll"] = 300000
                e2.state["peak_equity"] = 305000
                e2.state["max_drawdown"] = 0
                e2.state["pending"] = {"signal": "BIG", "stake": 1000, "paroli_step": 0,
                                       "source_issue": "x", "target_issue": "", "day": "2026-09-06"}
                e2._settle_pending_locked({"issue": "x1", "number": 1, "type": "SMALL", "date": "2026-09-06"})
                assert e2.state["current_drawdown"] == 6000 and e2.state["max_drawdown"] == 6000

            trades = eng.snapshot()["total_trades"]
            eng.process_snapshot(h, str(int(h[-1]["issue"]) + 1))
            assert eng.snapshot()["total_trades"] == trades
            json.loads(p.read_text(encoding="utf-8"))
            assert not list(p.parent.glob(f".{p.name}.tmp.*"))
            restored = re.RobustEngine(p)
            assert restored.snapshot()["bankroll"] == eng.snapshot()["bankroll"]
    finally:
        re.signal_for_next = original


def _trade_financials(snapshot):
    return {
        key: snapshot[key]
        for key in (
            "bankroll", "wins", "losses", "total_trades", "paroli_step",
            "peak_equity", "current_drawdown", "max_drawdown", "daily_profit",
        )
    }


def test_pending_target_issue_safety():
    original = force_signal("BIG")
    try:
        with tempfile.TemporaryDirectory() as td:
            # Exact target issue settles exactly once.
            p1 = Path(td) / "exact.json"
            e1 = re.RobustEngine(p1)
            h1 = make_history(110)
            target1 = str(int(h1[-1]["issue"]) + 1)
            e1.process_snapshot(h1, target1)
            before1 = _trade_financials(e1.snapshot())
            add_result(h1, "BIG")
            e1.process_snapshot(h1, str(int(target1) + 1))
            after1 = e1.snapshot()
            assert after1["total_trades"] == before1["total_trades"] + 1
            assert after1["wins"] == before1["wins"] + 1
            assert after1["bankroll"] == before1["bankroll"] + 960

            # Duplicate delivery of the already-settled target cannot settle twice.
            exact_once = _trade_financials(after1)
            e1.process_snapshot(h1, str(int(target1) + 1))
            assert _trade_financials(e1.snapshot()) == exact_once

            # A completed row before the declared target is not the bet result.
            p2 = Path(td) / "wrong.json"
            e2 = re.RobustEngine(p2)
            h2 = make_history(110)
            wrong_issue = str(int(h2[-1]["issue"]) + 1)
            target2 = str(int(h2[-1]["issue"]) + 2)
            e2.process_snapshot(h2, target2)
            before2 = _trade_financials(e2.snapshot())
            add_result(h2, "SMALL")  # wrong_issue, target is still one issue ahead
            assert h2[-1]["issue"] == wrong_issue
            e2.process_snapshot(h2, target2)
            s2 = e2.snapshot()
            assert _trade_financials(s2) == before2
            assert s2["pending"] is not None
            assert s2["pending"]["target_issue"] == target2

            # Once the exact target arrives, that target settles normally.
            add_result(h2, "BIG")
            assert h2[-1]["issue"] == target2
            e2.process_snapshot(h2, str(int(target2) + 1))
            assert e2.snapshot()["total_trades"] == before2["total_trades"] + 1

            # If the target itself is missing and history jumps beyond it, discard
            # the pending trade and resync without inventing W/L/P&L/DD/Paroli.
            p3 = Path(td) / "gap.json"
            e3 = re.RobustEngine(p3)
            h3 = make_history(110)
            target3 = str(int(h3[-1]["issue"]) + 1)
            e3.process_snapshot(h3, target3)
            before3 = _trade_financials(e3.snapshot())
            skipped_to = str(int(target3) + 1)
            h3.append({
                "issue": skipped_to, "number": 8, "type": "BIG",
                "date": "2026-09-06", "block_time": "2026-09-06 10:00:00",
            })
            e3.process_snapshot(h3, str(int(skipped_to) + 1))
            s3 = e3.snapshot()
            assert _trade_financials(s3) == before3
            assert s3["pending"] is None
            assert s3["last_processed_issue"] == skipped_to
            assert "re-anchored without settlement" in (s3["last_error"] or "")
    finally:
        re.signal_for_next = original


def test_audit_admin_token_check():
    import os
    old = os.environ.get("ROBUST_AUDIT_TOKEN")
    try:
        os.environ.pop("ROBUST_AUDIT_TOKEN", None)
        assert ri.audit_token_valid("anything") is False
        os.environ["ROBUST_AUDIT_TOKEN"] = "secret-admin-token"
        assert ri.audit_token_valid("") is False
        assert ri.audit_token_valid("wrong") is False
        assert ri.audit_token_valid("secret-admin-token") is True
    finally:
        if old is None:
            os.environ.pop("ROBUST_AUDIT_TOKEN", None)
        else:
            os.environ["ROBUST_AUDIT_TOKEN"] = old


class FakeCore:
    def __init__(self):
        import threading
        self.LOCK = threading.Lock()
        self.STATE = {"full_history": make_history(5), "history": [], "next_issue": None}
        self.app = None


def test_snapshot_copy_and_single_audit_job():
    original = ri.run_full_audit
    try:
        with tempfile.TemporaryDirectory() as td:
            import os
            old = os.environ.get("ROBUST_STATE_FILE")
            os.environ["ROBUST_STATE_FILE"] = str(Path(td) / "state.json")
            try:
                svc = ri.RobustService(FakeCore())
                snap, _ = svc._snapshot_legacy_history()
                snap[0]["number"] = 99
                assert svc.core.STATE["full_history"][0]["number"] != 99

                def fake_audit(progress=None, runs=None):
                    time.sleep(0.15)
                    return {"monte_carlo": {"runs": runs}}
                ri.run_full_audit = fake_audit
                ok1, _ = svc.start_audit()
                ok2, _ = svc.start_audit()
                assert ok1 is True and ok2 is False
                deadline = time.time() + 2
                while svc.audit_snapshot()["running"] and time.time() < deadline:
                    time.sleep(0.02)
                assert svc.audit_snapshot()["stage"] == "complete"
            finally:
                if old is None:
                    os.environ.pop("ROBUST_STATE_FILE", None)
                else:
                    os.environ["ROBUST_STATE_FILE"] = old
    finally:
        ri.run_full_audit = original


if __name__ == "__main__":
    test_signal_batch_parity()
    test_paroli_loss_risk_dd_and_persistence()
    test_pending_target_issue_safety()
    test_audit_admin_token_check()
    test_snapshot_copy_and_single_audit_job()
    print("ROBUST TESTS: ALL PASSED")
