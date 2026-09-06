import os
os.environ["TRX_NO_ENGINE"] = "1"
import requests
import app

class Resp:
    def __init__(self, issue, status=200):
        self.status_code = status
        self._issue = issue
    def json(self):
        return [{"issueNumber": str(self._issue), "number": 5, "blockTime": "2026-09-06 16:00:00"}]


def reset():
    with app._feed_cache_lock:
        app._feed_cache.clear()
        app._feed_health.update({"last_issue": "", "last_advance": 0.0, "last_http_ok": 0.0})
        app._last_recovery_attempt = 0.0


def test_stale_200_recovers_newer_issue():
    reset()
    calls = []
    seq = [Resp(100), Resp(100), Resp(101)]
    def fake(url, *a, **kw):
        calls.append(url)
        return seq.pop(0)
    app._original_session_get = fake
    app.FEED_STALE_SEC = 0.0
    app.FEED_RECOVERY_COOLDOWN_SEC = 0.0
    first = app._resilient_session_get(app.core.URL_DATA + "?limit=50")
    assert app._newest_issue_from_response(first) == "100"
    second = app._resilient_session_get(app.core.URL_DATA + "?limit=50")
    assert app._newest_issue_from_response(second) == "101"
    assert any("_trx_recover=" in x for x in calls), calls


def test_timeout_attempts_recovery_before_cache():
    reset()
    calls = []
    first = True
    def fake(url, *a, **kw):
        nonlocal first
        calls.append(url)
        if first:
            first = False
            return Resp(200)
        if "_trx_recover=" in url:
            return Resp(201)
        raise requests.ReadTimeout("boom")
    app._original_session_get = fake
    app.FEED_RECOVERY_COOLDOWN_SEC = 0.0
    assert app._newest_issue_from_response(app._resilient_session_get(app.core.URL_DATA + "?limit=50")) == "200"
    got = app._resilient_session_get(app.core.URL_DATA + "?limit=50")
    assert app._newest_issue_from_response(got) == "201"


def test_recovery_does_not_regress_issue():
    reset()
    app._original_session_get = lambda *a, **kw: Resp(299)
    with app._feed_cache_lock:
        app._feed_health["last_issue"] = "300"
        app._feed_health["last_advance"] = app.time.monotonic() - 100
    app.FEED_RECOVERY_COOLDOWN_SEC = 0.0
    assert app._recovery_fetch("300") is None

if __name__ == "__main__":
    test_stale_200_recovers_newer_issue()
    test_timeout_attempts_recovery_before_cache()
    test_recovery_does_not_regress_issue()
    print("FEED RECOVERY TESTS: ALL PASSED")
