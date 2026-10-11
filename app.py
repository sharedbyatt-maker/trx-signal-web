# -*- coding: utf-8 -*-
"""TRX application composition root.

The legacy engine implementation lives in app_core.py. This module wires the
shared final decision policy into BOTH live analysis and historical backtests,
then exposes the original Flask app/public API unchanged.
"""
import os
import statistics
import threading
import time
from urllib.parse import parse_qs, urlparse
from collections import Counter
from datetime import datetime

import requests
from feed_connection import feed_request_parts

# Prevent app_core from starting its background engine before we replace the
# decision paths. Tests already set TRX_NO_ENGINE=1 and remain engine-free.
_engine_disabled_by_caller = os.environ.get("TRX_NO_ENGINE") == "1"
os.environ["TRX_NO_ENGINE"] = "1"

import app_core as core
from app_core import *  # noqa: F401,F403 - preserve existing public module API
from decision import decide_signal
from drawings_persistence import install_drawings_persistence
from l1_capital import install_l1_capital


# ---------------------------------------------------------------------------
# Upstream feed resilience
# ---------------------------------------------------------------------------
# trxchart.com occasionally stalls long enough to raise ReadTimeout. The legacy
# loop treats any exception as OFFLINE immediately, which makes the dashboard
# flicker even when the previous feed snapshot is still fresh. Keep the latest
# successful tail response for a very short grace period and use it only for
# transient timeout/connection failures. The next poll still hits the upstream,
# so this never becomes a permanent cache and a real outage is still surfaced.
_original_session_get = core.session.get
_feed_cache_lock = threading.Lock()
_feed_cache = {}
_feed_health = {
    "last_issue": "", "last_advance": 0.0, "last_http_ok": 0.0,
    "last_request": 0.0, "last_latency_ms": None, "last_status_code": None,
    "request_count": 0, "recovery_count": 0, "failure_count": 0,
    "last_error": None,
}
_PROCESS_STARTED_MONO = time.monotonic()
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
    revision,profile=core.feed_profile()
    requests_to_try = [feed_request_parts(profile,recovery_limit,{'_trx_recover':time.time_ns()}),
                       feed_request_parts(profile,getattr(core,'MAX_FULL_ROWS',45200),{'_trx_full_recover':time.time_ns()})]
    for idx, (recovery_url,recovery_headers) in enumerate(requests_to_try):
        try:
            timeout = (3.0, 8.0 if idx == 0 else 18.0)
            r = _original_session_get(
                recovery_url,
                timeout=timeout,
                headers={**recovery_headers,"Cache-Control": "no-cache, no-store, max-age=0", "Pragma": "no-cache"},
                allow_redirects=False,
            )
            if r.status_code != 200 or core.feed_profile()[0]!=revision:
                continue
            newest = _newest_issue_from_response(r)
            if newest and (not previous_issue or int(newest) > int(previous_issue)):
                _accept_feed_response(r, feed_request_parts(profile,getattr(core,'TAIL_LIMIT',50))[0])
                _publish_feed_health("LIVE", f"recovered feed via {'large-tail' if idx == 0 else 'full-snapshot'}")
                print(f"[FEED] recovered: {previous_issue or 'none'} -> {newest}", flush=True)
                return r
        except (requests.Timeout, requests.ConnectionError, ValueError, TypeError) as exc:
            print(f"[FEED] recovery attempt failed: {type(exc).__name__}", flush=True)
    return None


def _feed_limit(url_s):
    try:
        raw = parse_qs(urlparse(str(url_s)).query).get("limit", [None])[0]
        return int(raw) if raw is not None else None
    except (TypeError, ValueError):
        return None


def _is_feed_url(url):
    current=urlparse(core.feed_profile()[1]['url'])
    candidate=urlparse(str(url))
    return (candidate.scheme,candidate.netloc,candidate.path)==(current.scheme,current.netloc,current.path)


def _is_live_tail_url(url_s):
    """Only small bounded polling requests get tail timeouts/cache rescue."""
    limit = _feed_limit(url_s)
    return _is_feed_url(url_s) and limit is not None and limit <= max(500, int(getattr(core, "TAIL_LIMIT", 50)))


def _resilient_session_get(url, *args, **kwargs):
    """Freshness-aware upstream fetch with active stale-feed recovery."""
    request_started = time.monotonic()
    url_s = str(url)
    is_feed = _is_feed_url(url_s)
    is_tail = _is_live_tail_url(url_s)
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
        if is_feed:
            with _feed_cache_lock:
                _feed_health["last_request"] = time.monotonic()
                _feed_health["last_latency_ms"] = round((time.monotonic() - request_started) * 1000, 1)
                _feed_health["last_status_code"] = int(response.status_code)
                _feed_health["request_count"] = int(_feed_health.get("request_count", 0)) + 1
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
                with _feed_cache_lock:
                    _feed_health["recovery_count"] = int(_feed_health.get("recovery_count", 0)) + 1
                return recovered
        else:
            _publish_feed_health("LIVE")
        return response

    except (requests.Timeout, requests.ConnectionError) as exc:
        if is_feed:
            with _feed_cache_lock:
                _feed_health["last_request"] = time.monotonic()
                _feed_health["last_latency_ms"] = round((time.monotonic() - request_started) * 1000, 1)
                _feed_health["failure_count"] = int(_feed_health.get("failure_count", 0)) + 1
                _feed_health["last_error"] = type(exc).__name__
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


def _record_external_feed(response):
    _accept_feed_response(response, 'trongrid-live-rounds')
    _publish_feed_health('LIVE', 'TronGrid verified live rounds; history snapshot uses primary source.')


core._record_external_feed = _record_external_feed
core._feed_probe_get = _original_session_get
core.session.get = _resilient_session_get
core.FEED_STALE_SEC = FEED_STALE_SEC


def _process_resources():
    """Small Linux diagnostics; unavailable fields stay null on other hosts."""
    resources = {"rss_mb": None, "peak_rss_mb": None, "open_fds": None}
    try:
        with open('/proc/self/status', encoding='ascii') as status:
            for line in status:
                if line.startswith(('VmRSS:', 'VmHWM:')):
                    key = 'rss_mb' if line.startswith('VmRSS:') else 'peak_rss_mb'
                    resources[key] = round(int(line.split()[1]) / 1024, 1)
        resources['open_fds'] = len(os.listdir('/proc/self/fd'))
    except (OSError, ValueError, IndexError):
        pass
    return resources


@core.app.route("/api/health")
def api_health():
    """Lightweight production telemetry: feed freshness, engine age and queue pressure."""
    now_mono = time.monotonic()
    with _feed_cache_lock:
        fh = dict(_feed_health)
    with core.LOCK:
        connected = bool(core.STATE.get("connected"))
        error = core.STATE.get("error")
        last_update = core.STATE.get("last_update")
        hist_meta = dict(core.STATE.get("hist_meta") or {})
        feed_health = core.public_feed_health(core.STATE)
        history_count = len(core.STATE.get("history") or [])
        full_history_count = len(core.STATE.get("full_history") or [])
    last_request = fh.get("last_request") or 0.0
    request_age = round(max(0.0, now_mono - last_request), 1) if last_request else None
    advance_age = feed_health.get("seconds_since_advance")
    status = str(feed_health.get("status") or ("LIVE" if connected else "STARTING"))
    engine_thread = getattr(core, "_engine_thread", None)
    tg_thread = getattr(core, "_tg_thread", None)
    engine_thread_alive = bool(engine_thread and engine_thread.is_alive())
    tg_thread_alive = bool(tg_thread and tg_thread.is_alive())
    # In test/tooling mode background threads are intentionally disabled.
    threads_expected = os.environ.get("TRX_NO_ENGINE") != "1"
    threads_ok = (engine_thread_alive and tg_thread_alive) if threads_expected else True
    healthy = bool(connected and status not in ("OFFLINE", "STALE") and threads_ok)
    payload = {
        "ok": healthy,
        "status": status,
        "uptime_sec": round(max(0.0, now_mono - _PROCESS_STARTED_MONO), 1),
        "resources": _process_resources(),
        "engine": {
            "connected": connected,
            "last_update": last_update,
            "error": error,
            "state_history_rows": history_count,
            "full_history_rows": full_history_count,
            "history_days": hist_meta.get("days"),
            "thread_alive": engine_thread_alive,
        },
        "feed": {
            "last_issue": fh.get("last_issue") or feed_health.get("last_issue"),
            "seconds_since_advance": advance_age,
            "result_age_sec": feed_health.get("result_age_sec"),
            "seconds_since_request": request_age,
            "last_latency_ms": fh.get("last_latency_ms"),
            "last_status_code": fh.get("last_status_code"),
            "request_count": int(fh.get("request_count") or 0),
            "recovery_count": int(fh.get("recovery_count") or 0),
            "failure_count": int(fh.get("failure_count") or 0),
            "last_error": fh.get("last_error"),
            "note": feed_health.get("note", ""),
        },
        "queues": {
            "telegram": core._tg_queue.qsize() if hasattr(core, "_tg_queue") else None,
            "telegram_max": getattr(core, "TG_QUEUE_MAX", None),
            "telegram_dropped": int(getattr(core, "_tg_drop_count", 0)),
            "telegram_worker_alive": tg_thread_alive,
        },
        "server_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    return core.jsonify(payload), (200 if healthy else 503)


_legacy_analyze_all_in_one = core.analyze_all_in_one


def analyze_all_in_one(history):
    """Live analysis using the shared final decision policy.

    Scoring/features stay exactly as before in app_core; only the final
    threshold + reversal + MTF decision is centralized in decide_signal().
    """
    out = _legacy_analyze_all_in_one(history)

    # Preserve pre-decision states that are not score decisions.
    if out.get("signal") in ("WAIT", "SKIP (LOW VOLATILITY)"):
        return out
    if not out.get("ready") or len(history) < core.LONG_WINDOW:
        return out

    m = [1 if x["type"] == "BIG" else -1 for x in history]
    ema_f = core.ema(m, core.FAST_EMA)
    ema_s = core.ema(m, core.SLOW_EMA)
    if ema_f is None or ema_s is None or not m:
        return out

    trend_diff = ema_f - ema_s
    mtf = out.get("mtf") or core.mtf_confluence(m)
    decision = decide_signal(
        out.get("score", 0.0),
        trend_diff,
        m[-1],
        mtf,
        core.SCORE_TRADE,
        core.SCORE_WATCH,
    )

    # Existing live decision logic used the same policy. Replacing signal here
    # makes the shared function authoritative without changing score semantics.
    out = dict(out)
    old_signal = out.get("signal")
    out["signal"] = decision["signal"]
    out["decision_kind"] = decision["kind"]
    out["decision_mtf_ok"] = decision["mtf_ok"]

    # Keep the rich Burmese reason generated by the existing analyzer when its
    # result agrees. This should be the normal case; fallback text makes any
    # future divergence visible instead of silently hiding it.
    if old_signal != decision["signal"]:
        out["reason"] = (
            f"Shared decision override: {old_signal} → {decision['signal']} | "
            f"{out.get('reason', '')}"
        )
    return out


def run_backtest(parsed):
    """Causal replay using the SAME decide_signal() function as live mode."""
    start_need = max(
        core.LONG_WINDOW,
        core.VOL_WINDOW,
        core.SR_WINDOW,
        core.RSI_PERIOD + 1,
        core.MOM_WINDOW,
        core.SLOW_EMA,
    ) + 2
    if len(parsed) < start_need + 50:
        return None

    m = [1 if x["type"] == "BIG" else -1 for x in parsed]
    nums = [x["number"] for x in parsed]
    typ = [x["type"] for x in parsed]
    ef = core.ema_series(m, core.FAST_EMA)
    es = core.ema_series(m, core.SLOW_EMA)
    rs = core.rolling_rsi_series(nums)

    pref = [0] * (len(typ) + 1)
    for i, v in enumerate(typ):
        pref[i + 1] = pref[i] + (1 if v == "BIG" else 0)

    # Exact causal equivalent of mtf_confluence(m[:i]) for every prefix, but
    # computed once in O(n). The previous per-row slicing + full EMA replay was
    # O(n²) and could block the live polling thread for minutes on cold start.
    def mtf_prefix_signs(step):
        groups = [sum(m[k:k + step]) for k in range(0, len(m) - step + 1, step)]
        fast = core.ema_series(groups, core.FAST_EMA)
        slow = core.ema_series(groups, core.SLOW_EMA)
        signs = [0] * (len(m) + 1)
        for prefix_len in range(step * core.SLOW_EMA, len(m) + 1):
            group_index = prefix_len // step - 1
            f = fast[group_index]
            s = slow[group_index]
            if f is not None and s is not None:
                signs[prefix_len] = 1 if f > s else -1
        return signs

    mtf5 = mtf_prefix_signs(5)
    mtf15 = mtf_prefix_signs(15)

    comps = {k: [0, 0] for k in ("EMA", "MOM", "RSI", "FADE", "GAP", "S/R")}
    buckets = {"trade": [0, 0], "watch": [0, 0]}
    guards = {"reversal": 0, "mtf": 0}
    tested = 0

    for i in range(start_need, len(m)):
        # Everything below uses rows < i only. Row i is the target/actual.
        vol = statistics.pstdev(nums[i - core.VOL_WINDOW:i])
        if vol < core.VOL_MIN:
            continue

        td = ef[i - 1] - es[i - 1]
        t_score = max(-30.0, min(30.0, td * 250))

        mom = sum(m[i - core.MOM_WINDOW:i]) / core.MOM_WINDOW
        m_score = max(-20.0, min(20.0, mom * 40))

        r = rs[i - 1]
        r_score = -15.0 if r >= 70 else (15.0 if r <= 30 else 0.0)

        st = 0
        j = i - 1
        while j >= 0 and m[j] == m[i - 1] and st < 40:
            st += 1
            j -= 1
        st_score = 0.0
        if st >= 4:
            st_score = min((st - 3) * 8, 24)
            if m[i - 1] == 1:
                st_score = -st_score

        big = pref[i] - pref[i - core.LONG_WINDOW]
        small = core.LONG_WINDOW - big
        g_score = max(-24.0, min(24.0, -(big - small) * 0.6))

        freq = Counter(nums[i - core.SR_WINDOW:i])
        sup_t = sum(freq[d] for d in range(0, 4))
        res_t = sum(freq[d] for d in range(7, 10))
        sr_score = max(-18.0, min(18.0, (sup_t - res_t) * core.SR_WEIGHT))

        score = t_score + m_score + r_score + st_score + g_score + sr_score
        actual = 1 if typ[i] == "BIG" else -1
        tested += 1

        for name, sc in (
            ("EMA", t_score),
            ("MOM", m_score),
            ("RSI", r_score),
            ("FADE", st_score),
            ("GAP", g_score),
            ("S/R", sr_score),
        ):
            if sc != 0:
                comps[name][0] += 1
                if (1 if sc > 0 else -1) == actual:
                    comps[name][1] += 1

        # Causal MTF state: m[:i] ends at i-1, exactly the latest round known
        # when predicting target round i.
        mtf = {"x5": mtf5[i], "x15": mtf15[i]}
        decision = decide_signal(
            round(score, 1),
            td,
            m[i - 1],
            mtf,
            core.SCORE_TRADE,
            core.SCORE_WATCH,
        )

        if decision["kind"] == "reversal_guard":
            guards["reversal"] += 1
        elif decision["kind"] == "mtf_guard":
            guards["mtf"] += 1

        if decision["signal"] in ("BIG", "SMALL"):
            pred = 1 if decision["signal"] == "BIG" else -1
            buckets["trade"][0] += 1
            if pred == actual:
                buckets["trade"][1] += 1
        elif decision["signal"] == "SKIP (WATCH)":
            buckets["watch"][0] += 1

    def wr(c):
        return round(c[1] / c[0], 4) if c[0] else None

    return {
        "rounds_tested": tested,
        "components": [
            {"name": k, "calls": comps[k][0], "wins": comps[k][1], "wr": wr(comps[k])}
            for k in ("EMA", "MOM", "RSI", "FADE", "GAP", "S/R")
        ],
        "buckets": {
            "trade": {
                "calls": buckets["trade"][0],
                "wins": buckets["trade"][1],
                "wr": wr(buckets["trade"]),
            },
            "watch": {
                "calls": buckets["watch"][0],
                "wins": buckets["watch"][1],
                "wr": wr(buckets["watch"]),
            },
        },
        "guards": guards,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


# Make these authoritative inside app_core too. engine_loop() resolves globals
# from app_core.__dict__, so both live execution and daily calibration use them.
core.decide_signal = decide_signal
core.analyze_all_in_one = analyze_all_in_one
core.run_backtest = run_backtest

# Explicit aliases for imports/tests/users of this composition module.
app = core.app
STATE = core.STATE
start_engine = core.start_engine

# Phase 8: token-protected, additive server persistence for manual chart drawings.
# This does not mutate legacy/L1/feed state.
drawings_store = install_drawings_persistence(core.app)
# Frozen L1 CAPITAL observer: Telegram/manual execution only; no bet placement.
l1_capital_service = install_l1_capital(core)

from admin_dashboard import install_admin

def _admin_clear_caches():
    with _feed_cache_lock:
        _feed_cache.clear()
    with core.LOCK:
        core._rsi_ext_cache = {'ts': 0.0, 'data': None}

admin_store = install_admin(core, api_health, l1_capital_service, _admin_clear_caches)


# Restore caller intent and start only after all decision paths/routes are wired.
if _engine_disabled_by_caller:
    os.environ["TRX_NO_ENGINE"] = "1"
else:
    os.environ.pop("TRX_NO_ENGINE", None)
    core.start_engine()
    l1_capital_service.start()
    admin_store.history_sync.start()


if __name__ == "__main__":
    core.start_engine()
    l1_capital_service.start()
    admin_store.history_sync.start()
    print("=" * 52, flush=True)
    print("📈 FOREX-STYLE CONFLUENCE ENGINE — SHARED DECISION POLICY", flush=True)
    print("   Live + Backtest → decision.decide_signal()", flush=True)
    print("   L1 CAPITAL → frozen manual-execution Telegram observer", flush=True)
    print("   Open: http://127.0.0.1:5000", flush=True)
    print("=" * 52, flush=True)
    port = int(os.environ.get("PORT", 10000))
    core.app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
