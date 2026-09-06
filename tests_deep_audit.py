# -*- coding: utf-8 -*-
"""Regression tests for whole-site deep-audit safety fixes."""
import csv
import os
import tempfile
from pathlib import Path

os.environ["TRX_NO_ENGINE"] = "1"

import app as eng
import app_core as core


def test_newest_raw_slice_and_parse_validation():
    desc = [{"issueNumber": str(i), "number": 5} for i in range(10, 0, -1)]
    asc = list(reversed(desc))
    assert [x["issueNumber"] for x in core.newest_raw_slice(desc, 3)] == ["10", "9", "8"]
    assert [x["issueNumber"] for x in core.newest_raw_slice(asc, 3)] == ["8", "9", "10"]
    rows = core.parse_history([
        {"issueNumber": "2026090601", "number": 8, "blockTime": "2026-09-06 10:00:00"},
        {"issueNumber": "bad", "number": 5, "blockTime": "2026-09-06 10:01:00"},
        {"issueNumber": "2026090602", "number": 99, "blockTime": "2026-09-06 10:02:00"},
        {"issueNumber": "2026090603", "number": -1, "blockTime": "2026-09-06 10:03:00"},
    ])
    assert len(rows) == 1 and rows[0]["issue"] == "2026090601"


def test_issue_relation_and_pending_gap_is_inert():
    assert core.issue_relation("102", "102") == "exact"
    assert core.issue_relation("101", "102") == "before"
    assert core.issue_relation("103", "102") == "after"
    assert core.issue_relation("x", "102") == "mismatch"

    saved = (core.pending, core.units, core.lose_streak, core.cooldown, dict(core.stats))
    try:
        core.pending = {"issue": "20260906102", "signal": "BIG", "score": 50}
        core.units = 3
        core.lose_streak = 1
        core.cooldown = 0
        core.stats.clear()
        core.stats.update({"w": 4, "l": 2})
        before = (core.units, core.lose_streak, dict(core.stats))
        core.resolve_pending({"issue": "20260906103", "type": "SMALL", "short_issue": "061103", "number": 2})
        assert core.pending is None
        assert (core.units, core.lose_streak, dict(core.stats)) == before
    finally:
        core.pending, core.units, core.lose_streak, core.cooldown, old_stats = saved
        core.stats.clear()
        core.stats.update(old_stats)


def test_strat_gap_is_inert():
    saved_pending = core.strat_pending
    saved_state = dict(core.strat_state)
    try:
        core.strat_state.update({"tier": 1, "step": 2, "signals": 7, "busts": 1, "pending": {"issue": "102"}})
        core.strat_pending = {"issue": "102", "target": "BIG", "tier": 1, "step": 2, "stake": 10000}
        financial = (
            core.strat_state["tier"], core.strat_state["step"],
            core.strat_state["signals"], core.strat_state["busts"],
        )
        assert core.reconcile_strat_pending_issue({"issue": "103"}) is False
        assert core.strat_pending is None
        assert core.strat_state["pending"] is None
        assert (
            core.strat_state["tier"], core.strat_state["step"],
            core.strat_state["signals"], core.strat_state["busts"],
        ) == financial
    finally:
        core.strat_pending = saved_pending
        core.strat_state.clear()
        core.strat_state.update(saved_state)


def test_empty_csv_gets_header():
    old_log, old_hist = core.LOG_FILE, core.HIST_FILE
    try:
        with tempfile.TemporaryDirectory() as td:
            core.LOG_FILE = str(Path(td) / "trade.csv")
            core.HIST_FILE = str(Path(td) / "hist.csv")
            Path(core.LOG_FILE).touch()
            Path(core.HIST_FILE).touch()
            core.log_signal(["2026-09-06 10:00:00", "1", "BIG", 50, "BIG", "WIN"])
            core.append_signal_history({
                "time": "10:00:00", "issue": "1", "signal": "BIG", "score": 50,
                "result_number": 8, "result_type": "BIG", "outcome": "WIN",
            })
            with open(core.LOG_FILE, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
                assert len(rows) == 1 and rows[0]["issue"] == "1"
            with open(core.HIST_FILE, newline="", encoding="utf-8") as f:
                rows = list(csv.DictReader(f))
                assert len(rows) == 1 and rows[0]["issue"] == "1"
    finally:
        core.LOG_FILE, core.HIST_FILE = old_log, old_hist


def test_rsi_extremes_accepts_wrapped_payload():
    old_get = core.session.get

    class Resp:
        status_code = 200

        def json(self):
            base = 20260906000000000
            return {"data": [
                {
                    "issueNumber": str(base + i), "number": i % 10,
                    "blockTime": f"2026-09-06 10:{i % 60:02d}:00",
                }
                for i in range(200)
            ]}

    try:
        core.session.get = lambda *args, **kwargs: Resp()
        data = core.compute_rsi_extremes(30)
        assert data is not None and data["rounds"] == 200
        assert 0 <= data["min"] <= 100 and 0 <= data["max"] <= 100
    finally:
        core.session.get = old_get


def test_low_latency_defaults():
    assert 0.25 <= core.POLL_SEC <= 1.0, core.POLL_SEC
    assert 20 <= core.TAIL_LIMIT <= 100, core.TAIL_LIMIT



def test_flask_routes_smoke():
    client = eng.app.test_client()
    for path in (
        "/", "/api/state", "/api/history", "/api/latest", "/api/backtest",
        "/api/robust-engine/status", "/api/robust-engine/signal",
        "/api/robust-engine/stats", "/api/robust-engine/audit",
    ):
        response = client.get(path)
        assert response.status_code == 200, (path, response.status_code)
    response = client.post("/api/robust-engine/audit")
    assert response.status_code in (401, 503)


if __name__ == "__main__":
    test_newest_raw_slice_and_parse_validation()
    test_issue_relation_and_pending_gap_is_inert()
    test_strat_gap_is_inert()
    test_empty_csv_gets_header()
    test_rsi_extremes_accepts_wrapped_payload()
    test_low_latency_defaults()
    test_flask_routes_smoke()
    print("DEEP AUDIT TESTS: ALL PASSED")
