from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
start = s.index('_original_session_get = core.session.get')
end = s.index('\n\ncore.session.get = _resilient_session_get', start)
old = s[start:end]
new = r'''_original_session_get = core.session.get
_feed_cache_lock = threading.Lock()
_feed_cache = {}
_feed_health = {"last_issue": "", "last_advance": 0.0, "last_http_ok": 0.0}
_last_recovery_attempt = 0.0
try:
    FEED_GRACE_SEC = max(3.0, min(float(os.environ.get("TRX_FEED_GRACE_SEC", "12")), 30.0))
except (TypeError, ValueError):
    FEED_GRACE_SEC = 12.0
try:
    FEED_TAIL_READ_TIMEOUT = max(1.0, min(float(os.environ.get("TRX_TAIL_READ_TIMEOUT", "3")), 10.0))
except (TypeError, ValueError):
    FEED_TAIL_READ_TIMEOUT = 3.0
try:
    FEED_STALE_SEC = max(65.0, min(float(os.environ.get("TRX_FEED_STALE_SEC", "80")), 240.0))
except (TypeError, ValueError):
    FEED_STALE_SEC = 80.0
try:
    FEED_RECOVERY_COOLDOWN_SEC = max(10.0, min(float(os.environ.get("TRX_FEED_RECOVERY_COOLDOWN_SEC", "20")), 120.0))
except (TypeError, ValueError):
    FEED_RECOVERY_COOLDOWN_SEC = 20.0


def _newest_issue_from_response(response):
    try:
        payload = response.json()
        rows = payload if isinstance(payload, list) else (payload.get("data", []) if isinstance(payload, dict) else [])
        best = 0
        for row in rows:
            if not isinstance(row, dict):
                continue
            raw = str(row.get("issueNumber") or row.get("issue") or "")
            if raw.isdigit():
                best = max(best, int(raw))
        return str(best) if best else ""
    except (ValueError, TypeError, AttributeError):
        return ""


def _publish_feed_health(status, note=""):
    now = time.monotonic()
    with _feed_cache_lock:
        last_issue = _feed_health.get("last_issue", "")
        last_advance = _feed_health.get("last_advance", 0.0)
        last_http_ok = _feed_health.get("last_http_ok", 0.0)
    with core.LOCK:
        core.STATE["feed_health"] = {
            "status": status,
            "last_issue": last_issue,
            "seconds_since_advance": round(max(0.0, now - last_advance), 1) if last_advance else None,
            "seconds_since_http_ok": round(max(0.0, now - last_http_ok), 1) if last_http_ok else None,
            "note": note,
        }


def _accept_feed_response(response, cache_key):
    """Record a 200 feed response and return (newest_issue, did_advance, age)."""
    now = time.monotonic()
    newest = _newest_issue_from_response(response)
    with _feed_cache_lock:
        previous = _feed_health.get("last_issue", "")
        advanced = bool(newest and (not previous or int(newest) > int(previous)))
        if advanced:
            _feed_health["last_issue"] = newest
            _feed_health["last_advance"] = now
        _feed_health["last_http_ok"] = now
        _feed_cache[cache_key] = (now, response)
        advance_age = now - (_feed_health.get("last_advance") or now)
    return newest, advanced, advance_age


def _recovery_fetch(previous_issue):
    """Actively escape a stale tail/CDN cache and return a fresher response if found."""
    global _last_recovery_attempt
    now = time.monotonic()
    with _feed_cache_lock:
        if now - _last_recovery_attempt < FEED_RECOVERY_COOLDOWN_SEC:
            return None
        _last_recovery_attempt = now

    # First try a substantially different query/cache key while keeping payload bounded.
    recovery_limit = max(1000, min(int(getattr(core, "TAIL_LIMIT", 50)) * 20, 5000))
    urls = [
        f"{core.URL_DATA}?limit={recovery_limit}&_trx_recover={time.time_ns()}",
        f"{core.URL_DATA}?_trx_full_recover={time.time_ns()}",
    ]
    for idx, recovery_url in enumerate(urls):
        try:
            timeout = (3.0, 8.0 if idx == 0 else 18.0)
            r = _original_session_get(
                recovery_url,
                timeout=timeout,
                headers={"Cache-Control": "no-cache, no-store, max-age=0", "Pragma": "no-cache"},
            )
            if r.status_code != 200:
                continue
            newest = _newest_issue_from_response(r)
            if newest and (not previous_issue or int(newest) > int(previous_issue)):
                _accept_feed_response(r, core.URL_DATA + f"?limit={getattr(core, 'TAIL_LIMIT', 50)}")
                _publish_feed_health("LIVE", f"recovered feed via {'large-tail' if idx == 0 else 'full-snapshot'}")
                print(f"[FEED] recovered: {previous_issue or 'none'} -> {newest}", flush=True)
                return r
        except (requests.Timeout, requests.ConnectionError, ValueError, TypeError) as exc:
            print(f"[FEED] recovery attempt failed: {type(exc).__name__}", flush=True)
    return None


def _resilient_session_get(url, *args, **kwargs):
    """Freshness-aware upstream fetch with active stale-feed recovery."""
    url_s = str(url)
    is_feed = url_s.startswith(core.URL_DATA)
    is_tail = is_feed and "?limit=" in url_s
    actual_url = url_s

    if is_tail:
        kwargs["timeout"] = (2.5, FEED_TAIL_READ_TIMEOUT)
        sep = "&" if "?" in url_s else "?"
        actual_url = f"{url_s}{sep}_trx_nonce={time.time_ns()}"
        hdr = dict(kwargs.get("headers") or {})
        hdr.update({"Cache-Control": "no-cache, no-store, max-age=0", "Pragma": "no-cache"})
        kwargs["headers"] = hdr

    try:
        response = _original_session_get(actual_url, *args, **kwargs)
        if not is_feed or response.status_code != 200:
            return response

        if not is_tail:
            return response

        newest, advanced, advance_age = _accept_feed_response(response, url_s)
        if advanced:
            _publish_feed_health("LIVE")
            return response

        # A successful HTTP request with an unchanged issue is not proof of a healthy feed.
        # Once the expected 1-minute cadence is clearly missed, actively fetch around stale caches.
        if newest and advance_age >= FEED_STALE_SEC:
            _publish_feed_health("STALE", f"issue {newest} unchanged for {advance_age:.0f}s; recovering")
            recovered = _recovery_fetch(newest)
            if recovered is not None:
                return recovered
        else:
            _publish_feed_health("LIVE")
        return response

    except (requests.Timeout, requests.ConnectionError) as exc:
        if is_tail:
            now = time.monotonic()
            with _feed_cache_lock:
                cached = _feed_cache.get(url_s)
                last_issue = _feed_health.get("last_issue", "")
                last_advance = _feed_health.get("last_advance", 0.0)
            data_age = now - last_advance if last_advance else 10**9

            # Before reusing old data, attempt a genuinely fresh recovery request.
            recovered = _recovery_fetch(last_issue)
            if recovered is not None:
                return recovered

            # A tiny grace is acceptable only while the last real issue is still fresh.
            if cached and now - cached[0] <= FEED_GRACE_SEC and data_age < FEED_STALE_SEC:
                _publish_feed_health("DEGRADED", f"{type(exc).__name__}; retrying upstream")
                return cached[1]
            _publish_feed_health("OFFLINE", type(exc).__name__)
        raise
'''
s = s[:start] + new + s[end:]
p.write_text(s, encoding='utf-8')

# Expand regression tests for actual stale-200 recovery and timeout recovery.
p = Path('tests_feed_recovery.py')
p.write_text(r'''import os
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
''', encoding='utf-8')
