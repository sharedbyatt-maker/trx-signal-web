# -*- coding: utf-8 -*-
"""Composition-layer integration for Robust Signal Engine.

Reads the legacy engine's completed history under core.LOCK, then performs all
Robust calculations outside the legacy lock. No legacy STATE fields are mutated.
"""
from __future__ import annotations

import copy
import hmac
import os
import threading
import traceback
from datetime import datetime

from robust_audit import MC_RUNS, run_full_audit
from robust_engine import (
    BASE_STAKE,
    DAILY_SL,
    DAILY_TP,
    PAROLI_WINS,
    SCORE_THRESHOLD,
    VOL_MIN,
    RobustEngine,
)

def audit_token_valid(provided):
    """Constant-time check for the optional admin audit token."""
    expected = os.environ.get("ROBUST_AUDIT_TOKEN", "").strip()
    supplied = str(provided or "").strip()
    return bool(expected and supplied) and hmac.compare_digest(supplied, expected)


def _fmt_money(value, signed=False):
    n = int(round(float(value or 0)))
    if signed:
        return f"{n:+,}"
    return f"{n:,}"


def _risk_lines(event):
    """Compact daily-risk context derived only from the event's settled state."""
    daily_profit = int(round(float(event.get("daily_profit") or 0)))
    tp_left = max(0, DAILY_TP - daily_profit)
    sl_room = max(0, daily_profit + DAILY_SL)
    return (
        f"Daily TP: +{DAILY_TP:,} MMK · Remaining: {_fmt_money(tp_left)} MMK\n"
        f"Daily SL: -{DAILY_SL:,} MMK · Loss room: {_fmt_money(sl_room)} MMK"
    )


def format_robust_telegram_event(event):
    """Pure formatter; all Robust Telegram messages share one prefix."""
    kind = event.get("kind")
    if kind == "signal":
        return (
            "[ROBUST ENGINE]\n"
            "📡 NEW SIGNAL — TRADE ARMED\n\n"
            f"Issue: {event.get('issue')}\n"
            f"Target: {event.get('target')}\n"
            f"Paroli: Step {int(event.get('paroli_step', 0)) + 1} / {PAROLI_WINS}\n"
            f"Stake: {_fmt_money(event.get('stake'))} MMK\n"
            f"Daily P/L: {_fmt_money(event.get('daily_profit'), signed=True)} MMK\n"
            f"Bankroll: {_fmt_money(event.get('bankroll'))} MMK\n\n"
            "Engine: 🟢 ACTIVE — this issue is armed\n"
            f"Entry filter: |Score| ≥ {SCORE_THRESHOLD:.0f} · Vol ≥ {VOL_MIN:.1f}\n"
            f"{_risk_lines(event)}"
        )

    if kind == "settlement":
        outcome = event.get("outcome") or ""
        icon = "✅" if outcome == "WIN" else "❌"
        text = (
            "[ROBUST ENGINE]\n"
            f"{icon} SETTLEMENT — {outcome}\n\n"
            f"Issue: {event.get('issue')}\n"
            f"Signal: {event.get('signal')}\n"
            f"Actual: {event.get('actual')}\n"
            f"Stake: {_fmt_money(event.get('stake'))} MMK\n"
            f"Trade P/L: {_fmt_money(event.get('trade_pnl'), signed=True)} MMK\n"
            f"Daily P/L: {_fmt_money(event.get('daily_profit'), signed=True)} MMK\n"
            f"Bankroll: {_fmt_money(event.get('bankroll'))} MMK\n\n"
            f"{_risk_lines(event)}"
        )
        if event.get("trading_active"):
            text += (
                "\n\n"
                "Engine: 🟢 RUNNING — no stop triggered\n"
                "Next action: Waiting for the next VALID setup\n"
                "Note: A new signal is NOT guaranteed on the next round.\n"
                f"Next Paroli: Step {int(event.get('next_paroli_step', 0)) + 1} / {PAROLI_WINS}\n"
                f"Next Eligible Stake: {_fmt_money(event.get('next_stake'))} MMK"
            )
        else:
            daily_profit = int(round(float(event.get("daily_profit") or 0)))
            bankroll = int(round(float(event.get("bankroll") or 0)))
            next_stake = int(round(float(event.get("next_stake") or BASE_STAKE)))
            if daily_profit >= DAILY_TP:
                reason = "Daily TP reached"
                reset = "No more Robust signals until the next daily reset."
            elif daily_profit <= -DAILY_SL:
                reason = "Daily SL / hard risk stop reached"
                reset = "No more Robust signals until the next daily reset."
            elif bankroll < next_stake:
                reason = "Insufficient bankroll for the next eligible stake"
                reset = "Trading stays blocked until bankroll/risk state is sufficient."
            else:
                reason = "Risk guard is blocking new trades"
                reset = "Check the following stop notification/status for the exact guard."
            text += (
                "\n\n"
                "Engine: 🔴 NOT TRADING\n"
                f"Reason: {reason}\n"
                f"{reset}"
            )
        return text

    if kind == "paroli4":
        return (
            "[ROBUST ENGINE]\n"
            "🔥 4-WIN PAROLI HIT\n\n"
            f"Issue: {event.get('issue')}\n"
            "4-win cycle completed.\n"
            f"Daily P/L: {_fmt_money(event.get('daily_profit'), signed=True)} MMK\n"
            f"Bankroll: {_fmt_money(event.get('bankroll'))} MMK\n"
            "Paroli Reset: Step 1 / 4\n"
            f"Next Eligible Base Stake: {_fmt_money(event.get('base_stake'))} MMK\n\n"
            "Engine status depends on the daily TP/SL guard shown in the following notification."
        )

    if kind == "daily_tp":
        return (
            "[ROBUST ENGINE]\n"
            "🎯 DAILY TP HIT\n\n"
            f"Daily P/L: {_fmt_money(event.get('daily_profit'), signed=True)} MMK\n"
            f"Bankroll: {_fmt_money(event.get('bankroll'))} MMK\n\n"
            "Engine: 🔴 STOPPED FOR TODAY\n"
            "Reason: Daily Take Profit reached\n"
            "New Robust signals: DISABLED\n"
            "Resume: Automatically at the next daily reset."
        )

    if kind == "daily_risk_stop":
        return (
            "[ROBUST ENGINE]\n"
            "🛑 DAILY RISK STOP\n\n"
            f"Daily P/L: {_fmt_money(event.get('daily_profit'), signed=True)} MMK\n"
            f"Bankroll: {_fmt_money(event.get('bankroll'))} MMK\n"
            f"Reason: {event.get('reason') or 'Daily SL / pre-trade hard risk guard'}\n\n"
            "Engine: 🔴 STOPPED FOR TODAY\n"
            "New Robust signals: DISABLED\n"
            "Resume: Automatically at the next daily reset."
        )

    if kind == "daily_reset":
        return (
            "[ROBUST ENGINE]\n"
            "🌅 NEW DAY RESET\n\n"
            f"Previous Date: {event.get('previous_date')}\n"
            f"New Date: {event.get('new_date')}\n"
            f"Previous Day P/L: {_fmt_money(event.get('previous_day_profit'), signed=True)} MMK\n"
            f"Bankroll: {_fmt_money(event.get('bankroll'))} MMK\n"
            "Paroli Reset: Step 1 / 4\n"
            f"Base Stake: {_fmt_money(event.get('base_stake'))} MMK\n\n"
            "Engine: 🟢 RUNNING — ready for valid setups\n"
            "New Robust signals: ENABLED"
        )
    return None


class RobustService:
    def __init__(self, core):
        self.core = core
        self.engine = RobustEngine()
        self._stop = threading.Event()
        self._start_lock = threading.Lock()
        self._thread = None
        self._last_legacy_marker = object()

        self._audit_lock = threading.Lock()
        self._audit_status_lock = threading.Lock()
        self._audit_status = {
            "running": False,
            "stage": "idle",
            "progress": 0,
            "started_at": None,
            "finished_at": None,
            "error": None,
            "result": None,
            "runs": MC_RUNS,
        }

    def _snapshot_legacy_history(self):
        """Thread-safe snapshot only; never hold core.LOCK during calculations."""
        with self.core.LOCK:
            history = copy.deepcopy(
                self.core.STATE.get("full_history")
                or self.core.STATE.get("history")
                or []
            )
            next_issue = self.core.STATE.get("next_issue")
        return history, next_issue

    def _forward_robust_events(self):
        # Robust Telegram notifications are intentionally disabled. Drain the
        # engine's transient notification events so they cannot accumulate, but
        # never forward them into the shared legacy Telegram sender. Robust
        # signal/risk/state logic remains completely unchanged.
        self.engine.drain_notification_events()

    def tick(self):
        history, next_issue = self._snapshot_legacy_history()
        if history:
            snapshot = self.engine.process_snapshot(history, next_issue)
        else:
            snapshot = self.engine.snapshot()
        self._forward_robust_events()
        return snapshot

    def _worker(self):
        while not self._stop.is_set():
            try:
                # The legacy engine changes last_update when it publishes a new
                # completed-round snapshot. Skip duplicate observer work between
                # updates so persistence is not rewritten every second.
                with self.core.LOCK:
                    marker = self.core.STATE.get("last_update")
                if marker != self._last_legacy_marker:
                    self.tick()
                    self._last_legacy_marker = marker
            except Exception as exc:
                # Robust failures are isolated: old engine thread keeps running.
                with self.engine.lock:
                    self.engine.state["last_error"] = f"robust worker: {exc}"
                print(f"[ROBUST] worker error: {exc}", flush=True)
            self._stop.wait(1.0)

    def start(self):
        with self._start_lock:
            if self._thread and self._thread.is_alive():
                return False
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._worker,
                name="robust-signal-engine",
                daemon=True,
            )
            self._thread.start()
            print("[ROBUST] independent engine observer started", flush=True)
            return True

    def stop(self):
        self._stop.set()

    def audit_snapshot(self):
        with self._audit_status_lock:
            return copy.deepcopy(self._audit_status)

    def _set_audit(self, **updates):
        with self._audit_status_lock:
            self._audit_status.update(updates)

    def _audit_progress(self, stage, progress):
        self._set_audit(stage=stage, progress=int(progress))

    def _audit_worker(self):
        try:
            result = run_full_audit(progress=self._audit_progress, runs=MC_RUNS)
            self._set_audit(
                running=False,
                stage="complete",
                progress=100,
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                result=result,
                error=None,
            )
        except Exception as exc:
            self._set_audit(
                running=False,
                stage="failed",
                finished_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                error=str(exc),
            )
            print(f"[ROBUST-AUDIT] failed: {exc}", flush=True)
            traceback.print_exc()
        finally:
            self._audit_lock.release()

    def start_audit(self):
        if not self._audit_lock.acquire(blocking=False):
            return False, self.audit_snapshot()

        self._set_audit(
            running=True,
            stage="starting",
            progress=0,
            started_at=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            finished_at=None,
            error=None,
            result=None,
            runs=MC_RUNS,
        )
        try:
            t = threading.Thread(
                target=self._audit_worker,
                name="robust-monte-carlo-audit",
                daemon=True,
            )
            t.start()
        except Exception:
            self._audit_lock.release()
            raise
        return True, self.audit_snapshot()


def install_robust_routes(core):
    """Register additive APIs on the existing Flask app."""
    from flask import jsonify, request

    service = RobustService(core)
    app = core.app

    @app.get("/api/robust-engine/status")
    def robust_status():
        return jsonify(service.engine.snapshot())

    @app.get("/api/robust-engine/signal")
    def robust_signal():
        s = service.engine.snapshot()
        return jsonify({
            "signal": s["signal"],
            "status": s["status"],
            "score": s["score"],
            "walk_rsi": s["walk_rsi"],
            "vol": s["vol"],
            "current_stake": s["current_stake"],
            "paroli_step": s["paroli_step"],
            "pending": s["pending"],
            "last_processed_issue": s["last_processed_issue"],
            "last_update": s["last_update"],
        })

    @app.get("/api/robust-engine/stats")
    def robust_stats():
        s = service.engine.snapshot()
        return jsonify({
            "bankroll": s["bankroll"],
            "reference_capital": s["reference_capital"],
            "daily_profit": s["daily_profit"],
            "daily_tp": s["daily_tp"],
            "daily_sl": s["daily_sl"],
            "wins": s["wins"],
            "losses": s["losses"],
            "total_trades": s["total_trades"],
            "win_rate": s["win_rate"],
            "peak_equity": s["peak_equity"],
            "current_drawdown": s["current_drawdown"],
            "max_drawdown": s["max_drawdown"],
            "daily_date": s["daily_date"],
            "daily_stopped": s["daily_stopped"],
            "status": s["status"],
        })

    @app.get("/api/robust-engine/audit")
    def robust_audit_status():
        return jsonify(service.audit_snapshot())

    @app.post("/api/robust-engine/audit")
    def robust_audit_start():
        configured = os.environ.get("ROBUST_AUDIT_TOKEN", "").strip()
        if not configured:
            return jsonify({"error": "Robust audit admin token is not configured"}), 503

        supplied = request.headers.get("X-Robust-Audit-Token", "").strip()
        if not supplied:
            auth = request.headers.get("Authorization", "").strip()
            if auth.lower().startswith("bearer "):
                supplied = auth[7:].strip()

        if not audit_token_valid(supplied):
            return jsonify({"error": "Unauthorized"}), 401

        started, status = service.start_audit()
        return jsonify(status), (202 if started else 409)

    @app.after_request
    def robust_assets(response):
        """Add Robust UI assets without rewriting the existing dashboard template."""
        try:
            if response.mimetype == "text/html" and not response.direct_passthrough:
                html = response.get_data(as_text=True)
                if "robust-engine-ui-assets" not in html:
                    html = html.replace(
                        "</head>",
                        '<link id="robust-engine-ui-assets" rel="stylesheet" '
                        'href="/static/css/robust.css?v=1">\n</head>',
                        1,
                    )
                    html = html.replace(
                        "</body>",
                        '<script src="/static/js/robust.js?v=1"></script>\n</body>',
                        1,
                    )
                    response.set_data(html)
        except Exception as exc:
            # UI injection failure must never break an existing response.
            print(f"[ROBUST] asset injection skipped: {exc}", flush=True)
        return response

    return service
