import os
from pathlib import Path

os.environ["TRX_NO_ENGINE"] = "1"

import app as composed
import app_core as core


def test_history_membership_is_constant_time():
    js = Path("static/js/app.js").read_text(encoding="utf-8")
    assert "let fullIssueSet = new Set()" in js
    assert "fullIssueSet.has(String(rd.issue))" in js
    assert "fullRows.some((x) => x.issue === rd.issue)" not in js
    assert "rebuildFullIssueSet()" in js


def test_higher_tf_live_indicators_are_recomputed_safely():
    js = Path("static/js/chart.js").read_text(encoding="utf-8")
    assert "function refreshHigherTfLiveIndicators(time)" in js
    assert "refreshHigherTfLiveIndicators(time)" in js
    assert "calcStoch(curBars, 14, 3, 3)" in js
    assert "seedLiveIndicators(closes" in js


def test_action_endpoints_are_not_mutable_gets():
    client = core.app.test_client()
    assert client.get("/api/telegram-test").status_code == 405
    assert client.post("/api/telegram-test").status_code == 429

    with core.LOCK:
        core.STATE["backtest"] = {"sentinel": 1}
    r = client.get("/api/backtest?refresh=1")
    assert r.status_code == 200
    assert r.get_json()["sentinel"] == 1
    assert client.post("/api/backtest/refresh").status_code == 403


def test_health_endpoint_exposes_operational_telemetry():
    client = core.app.test_client()
    r = client.get("/api/health")
    assert r.status_code in (200, 503)
    data = r.get_json()
    assert {"ok", "status", "uptime_sec", "engine", "feed", "queues", "server_time"} <= set(data)
    assert "last_latency_ms" in data["feed"]
    assert "seconds_since_request" in data["feed"]
    assert "telegram" in data["queues"]


def test_frontend_telegram_uses_guarded_post():
    js = Path("static/js/app.js").read_text(encoding="utf-8")
    assert 'fetch("/api/telegram-test", {' in js
    assert 'method: "POST"' in js
    assert '"X-Requested-With": "TRX-Terminal"' in js
