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
from collections import Counter
from datetime import datetime

import requests

# Prevent app_core from starting its background engine before we replace the
# decision paths. Tests already set TRX_NO_ENGINE=1 and remain engine-free.
_engine_disabled_by_caller = os.environ.get("TRX_NO_ENGINE") == "1"
os.environ["TRX_NO_ENGINE"] = "1"

import app_core as core
from app_core import *  # noqa: F401,F403 - preserve existing public module API
from decision import decide_signal
from robust_integration import install_robust_routes


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


core.session.get = _resilient_session_get


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
    rs = core.rsi_series(nums)

    pref = [0] * (len(typ) + 1)
    for i, v in enumerate(typ):
        pref[i + 1] = pref[i] + (1 if v == "BIG" else 0)

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
        mtf = core.mtf_confluence(m[:i])
        decision = decide_signal(
            score,
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

# Additive Robust subsystem. It registers separate APIs/UI assets and observes
# a thread-safe copy of legacy completed history without mutating legacy state.
robust_service = install_robust_routes(core)

# Restore caller intent and start only after all decision paths/routes are wired.
if _engine_disabled_by_caller:
    os.environ["TRX_NO_ENGINE"] = "1"
else:
    os.environ.pop("TRX_NO_ENGINE", None)
    core.start_engine()
    robust_service.start()


if __name__ == "__main__":
    core.start_engine()
    robust_service.start()
    print("=" * 52, flush=True)
    print("📈 FOREX-STYLE CONFLUENCE ENGINE — SHARED DECISION POLICY", flush=True)
    print("   Live + Backtest → decision.decide_signal()", flush=True)
    print("   Robust Engine → independent frozen causal strategy", flush=True)
    print("   Open: http://127.0.0.1:5000", flush=True)
    print("=" * 52, flush=True)
    port = int(os.environ.get("PORT", 10000))
    core.app.run(host="0.0.0.0", port=port, debug=False, threaded=True)
