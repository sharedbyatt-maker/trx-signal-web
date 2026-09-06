from pathlib import Path

p = Path('app.py')
s = p.read_text(encoding='utf-8')
old = '''_feed_cache = {}
try:
    FEED_GRACE_SEC = max(3.0, min(float(os.environ.get("TRX_FEED_GRACE_SEC", "15")), 60.0))
except (TypeError, ValueError):
    FEED_GRACE_SEC = 15.0
try:
    FEED_TAIL_READ_TIMEOUT = max(1.0, min(float(os.environ.get("TRX_TAIL_READ_TIMEOUT", "3")), 10.0))
except (TypeError, ValueError):
    FEED_TAIL_READ_TIMEOUT = 3.0


def _resilient_session_get(url, *args, **kwargs):
    """Short-grace fallback for transient live-feed failures only."""
    url_s = str(url)
    is_feed = url_s.startswith(core.URL_DATA)
    is_tail = is_feed and "?limit=" in url_s

    # Tail polling is latency-sensitive. Use a short connect/read timeout rather
    # than blocking the single engine thread for six seconds on a bad socket.
    if is_tail:
        kwargs["timeout"] = (2.5, FEED_TAIL_READ_TIMEOUT)

    try:
        response = _original_session_get(url, *args, **kwargs)
        if is_feed and response.status_code == 200:
            with _feed_cache_lock:
                _feed_cache[url_s] = (time.monotonic(), response)
        return response
    except (requests.Timeout, requests.ConnectionError) as exc:
        if is_tail:
            now = time.monotonic()
            with _feed_cache_lock:
                cached = _feed_cache.get(url_s)
            if cached and now - cached[0] <= FEED_GRACE_SEC:
                # Keep the last valid snapshot during a short network wobble.
                # Duplicate rows are already ignored by app_core's seen_issues.
                print(
                    f"[FEED] transient {type(exc).__name__}; using "
                    f"{now - cached[0]:.1f}s-old last-good tail snapshot",
                    flush=True,
                )
                return cached[1]
        raise
'''
new = '''_feed_cache = {}
_feed_health = {"last_issue": "", "last_advance": 0.0, "last_http_ok": 0.0}
try:
    FEED_GRACE_SEC = max(3.0, min(float(os.environ.get("TRX_FEED_GRACE_SEC", "15")), 60.0))
except (TypeError, ValueError):
    FEED_GRACE_SEC = 15.0
try:
    FEED_TAIL_READ_TIMEOUT = max(1.0, min(float(os.environ.get("TRX_TAIL_READ_TIMEOUT", "3")), 10.0))
except (TypeError, ValueError):
    FEED_TAIL_READ_TIMEOUT = 3.0
try:
    FEED_STALE_SEC = max(70.0, min(float(os.environ.get("TRX_FEED_STALE_SEC", "95")), 300.0))
except (TypeError, ValueError):
    FEED_STALE_SEC = 95.0


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


def _resilient_session_get(url, *args, **kwargs):
    """Freshness-aware upstream fetch with cache-busting and short failure grace."""
    url_s = str(url)
    is_feed = url_s.startswith(core.URL_DATA)
    is_tail = is_feed and "?limit=" in url_s
    actual_url = url_s

    if is_tail:
        kwargs["timeout"] = (2.5, FEED_TAIL_READ_TIMEOUT)
        # Avoid intermediary/CDN stale-200 responses on an otherwise healthy socket.
        sep = "&" if "?" in url_s else "?"
        actual_url = f"{url_s}{sep}_trx_nonce={time.time_ns()}"

    try:
        response = _original_session_get(actual_url, *args, **kwargs)
        if is_feed and response.status_code == 200:
            now = time.monotonic()
            newest = _newest_issue_from_response(response) if is_tail else ""
            with _feed_cache_lock:
                if is_tail:
                    previous = _feed_health.get("last_issue", "")
                    if newest and (not previous or int(newest) > int(previous)):
                        _feed_health["last_issue"] = newest
                        _feed_health["last_advance"] = now
                    _feed_health["last_http_ok"] = now
                    _feed_cache[url_s] = (now, response)
                    advance_age = now - (_feed_health.get("last_advance") or now)
                else:
                    advance_age = 0.0
            if is_tail and newest and advance_age > FEED_STALE_SEC:
                _publish_feed_health("STALE", f"upstream HTTP 200 but issue unchanged for {advance_age:.0f}s")
            elif is_tail:
                _publish_feed_health("LIVE")
        return response
    except (requests.Timeout, requests.ConnectionError) as exc:
        if is_tail:
            now = time.monotonic()
            with _feed_cache_lock:
                cached = _feed_cache.get(url_s)
                last_advance = _feed_health.get("last_advance", 0.0)
            # Grace is allowed only while the data itself is still recent.
            data_age = now - last_advance if last_advance else 10**9
            if cached and now - cached[0] <= FEED_GRACE_SEC and data_age <= FEED_STALE_SEC:
                _publish_feed_health("DEGRADED", f"{type(exc).__name__}; retrying upstream")
                print(f"[FEED] transient {type(exc).__name__}; short grace fallback", flush=True)
                return cached[1]
            _publish_feed_health("OFFLINE", type(exc).__name__)
        raise
'''
if old not in s:
    raise SystemExit('app.py target block not found')
s = s.replace(old, new)
p.write_text(s, encoding='utf-8')

p = Path('static/js/app.js')
s = p.read_text(encoding='utf-8')
old = '''function render(s, merged) {
  setConn(!!s.connected, s.connected ? "LIVE" : (s.error ? "OFFLINE: " + s.error : "OFFLINE"));
'''
new = '''function render(s, merged) {
  const fh = s.feed_health || {};
  const fstat = fh.status || (s.connected ? "LIVE" : "OFFLINE");
  if (!s.connected || fstat === "OFFLINE") {
    setConn(false, s.error ? "OFFLINE: " + s.error : "OFFLINE");
  } else if (fstat === "STALE") {
    setConn(false, `STALE FEED${fh.seconds_since_advance != null ? " · " + Math.round(fh.seconds_since_advance) + "s" : ""}`);
  } else if (fstat === "DEGRADED") {
    setConn(true, "DEGRADED · retrying feed");
  } else {
    setConn(true, "LIVE");
  }
'''
if old not in s:
    raise SystemExit('app.js render target not found')
s = s.replace(old, new)
old2 = '''function setConn(ok, txt) {
  $("dot").className = "dot " + (ok ? "on" : "off");
  $("conn-txt").textContent = ok ? "LIVE" : (txt && txt.length > 50 ? txt.slice(0, 47) + "…" : (txt || "OFFLINE"));
}
'''
new2 = '''function setConn(ok, txt) {
  $("dot").className = "dot " + (ok ? "on" : "off");
  const label = txt || (ok ? "LIVE" : "OFFLINE");
  $("conn-txt").textContent = label.length > 70 ? label.slice(0, 67) + "…" : label;
}
'''
if old2 not in s:
    raise SystemExit('app.js setConn target not found')
s = s.replace(old2, new2)
p.write_text(s, encoding='utf-8')
