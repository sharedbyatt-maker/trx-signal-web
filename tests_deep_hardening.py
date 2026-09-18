import os
import queue
import threading
from pathlib import Path

os.environ["TRX_NO_ENGINE"] = "1"

import app as composed
import app_core as core


def test_telegram_queue_is_bounded():
    assert core._tg_queue.maxsize == core.TG_QUEUE_MAX
    assert 64 <= core.TG_QUEUE_MAX <= 4096


def test_tg_notify_does_not_block_when_queue_is_full(monkeypatch):
    q = queue.Queue(maxsize=1)
    q.put("existing")
    monkeypatch.setattr(core, "_tg_queue", q)
    before = core._tg_drop_count
    assert core.tg_notify("new") is False
    assert core._tg_drop_count == before + 1
    assert q.get_nowait() == "existing"


def test_malformed_feed_payload_cannot_invent_issue():
    class Fake:
        def json(self):
            return {"data": [None, {}, {"issueNumber": "abc"}, {"issue": "", "number": 9}]}
    assert composed._newest_issue_from_response(Fake()) == ""


def test_out_of_order_feed_selects_newest_numeric_issue():
    class Fake:
        def json(self):
            return {"data": [
                {"issueNumber": "20260918003"},
                {"issueNumber": "20260918001"},
                {"issueNumber": "20260918002"},
            ]}
    assert composed._newest_issue_from_response(Fake()) == "20260918003"


def test_health_includes_deep_hardening_telemetry():
    client = core.app.test_client()
    r = client.get("/api/health")
    assert r.status_code in (200, 503)
    data = r.get_json()
    assert "thread_alive" in data["engine"]
    assert {"failure_count", "last_error"} <= set(data["feed"])
    assert {"telegram", "telegram_max", "telegram_dropped", "telegram_worker_alive"} <= set(data["queues"])


def test_rsi_extremes_has_singleflight_guard():
    src = Path("app_core.py").read_text(encoding="utf-8")
    assert "_rsi_ext_compute_lock.acquire(blocking=False)" in src
    assert '"retry_after": 5' in src
    assert "_rsi_ext_compute_lock.release()" in src


def test_engine_threads_are_named_and_observable():
    src = Path("app_core.py").read_text(encoding="utf-8")
    assert 'name="legacy-engine"' in src
    assert 'name="telegram-worker"' in src
    assert "_engine_thread" in src and "_tg_thread" in src
