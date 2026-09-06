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
from robust_engine import RobustEngine

def audit_token_valid(provided):
    """Constant-time check for the optional admin audit token."""
    expected = os.environ.get("ROBUST_AUDIT_TOKEN", "").strip()
    supplied = str(provided or "").strip()
    return bool(expected and supplied) and hmac.compare_digest(supplied, expected)


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

    def tick(self):
        history, next_issue = self._snapshot_legacy_history()
        if history:
            return self.engine.process_snapshot(history, next_issue)
        return self.engine.snapshot()

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
