from datetime import datetime, timedelta
from pathlib import Path

from flask import Flask, jsonify, render_template, request

ROOT = Path(__file__).resolve().parents[1]
app = Flask(
    __name__,
    template_folder=str(ROOT / "templates"),
    static_folder=str(ROOT / "static"),
    static_url_path="/static",
)

START = datetime(2026, 9, 13, 8, 0, 0)
NUMBERS = [8, 7, 3, 2, 9, 1, 6, 4, 5, 0, 8, 8, 7, 2, 1, 6, 9, 4, 3, 5]


def history_rows(count=360):
    out = []
    for i in range(count):
        issue = str(20260913000000000 + i + 1)
        number = NUMBERS[i % len(NUMBERS)]
        dt = START + timedelta(minutes=i)
        out.append(
            {
                "issue": issue,
                "short_issue": issue[-6:],
                "number": number,
                "type": "BIG" if number >= 5 else "SMALL",
                "block_time": dt.strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return out


ROWS = history_rows()


def state_payload():
    tail = ROWS[-120:]
    big = sum(1 for x in tail[-100:] if x["type"] == "BIG")
    small = 100 - big
    return {
        "connected": True,
        "last_update": "2026-09-13 14:00:00",
        "next_issue": str(int(ROWS[-1]["issue"]) + 1),
        "history": tail,
        "feed_health": {"status": "LIVE", "seconds_since_advance": 1},
        "config": {"long_window": 100},
        "analysis": {
            "ready": True,
            "big": big,
            "small": small,
            "gap": big - small,
            "score": 12.5,
            "reason": "Deterministic E2E fixture",
            "mtf": {"x5": 1, "x15": 1},
            "parts": [
                {"name": "EMA", "value": 12},
                {"name": "RSI", "value": -5},
            ],
        },
        "markov": {"p_big": 0.53, "n": 100},
        "strat": {"tier": 0, "step": 0, "busts": 0, "pending": None},
        "strat_pending": None,
        "strat_last": None,
        "tg_last": None,
    }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/history")
def api_history():
    since = request.args.get("since")
    rows = ROWS
    incremental = bool(since)
    if since:
        rows = [x for x in ROWS if x["issue"] > since]
    return jsonify(
        {
            "history": [[x["issue"], x["number"], x["block_time"]] for x in rows],
            "incremental": incremental,
            "last_time": ROWS[-1]["block_time"],
            "meta": {"count": len(ROWS), "days": 1},
        }
    )


@app.get("/api/state")
def api_state():
    return jsonify(state_payload())


@app.get("/api/latest")
def api_latest():
    x = ROWS[-1]
    return jsonify({"round": {"issue": x["issue"], "number": x["number"], "block_time": x["block_time"]}})


@app.get("/api/rsi-extremes")
def api_rsi_extremes():
    return jsonify(
        {
            "days": 30,
            "rounds": len(ROWS),
            "min": 24.2,
            "max": 76.8,
            "min_at": "2026-09-13 09:12:00",
            "max_at": "2026-09-13 12:43:00",
            "min_issue": ROWS[72]["issue"][-6:],
            "max_issue": ROWS[283]["issue"][-6:],
        }
    )


@app.get("/api/12step/daily-report")
def api_daily12():
    return jsonify(
        {
            "report": {
                "date": "2026-09-13",
                "signals": 3,
                "bet_wins": 2,
                "bet_losses": 1,
                "bet_win_rate": 66.7,
                "episode_win_rate": 66.7,
                "roi_pct": 4.2,
                "net_pnl": 420,
                "total_staked": 10000,
                "total_returned": 10420,
                "avg_stake": 3333,
                "open_episodes": 0,
                "episodes_resolved": 3,
                "episode_wins": 2,
                "tier_failed": 0,
                "busts": 0,
                "max_stake": 400,
                "max_tier": 1,
                "max_step": 2,
                "avg_pnl_per_episode": 140,
                "break_even_win_rate": 51.0,
                "edge_vs_break_even": 15.7,
                "avg_pnl_per_bet": 140,
                "updated_at": "2026-09-13 14:00:00",
                "recent_events": [],
                "engine": {"tier": 1, "step": 1, "pending": None, "next_eligible_stake": 200},
            },
            "history": [],
        }
    )


@app.get("/api/l1-capital")
def api_l1_capital():
    return jsonify(
        {
            "ready": True,
            "engine": "L1 CAPITAL",
            "version": "1.1",
            "pending": {
                "target": "BIG",
                "issue": str(int(ROWS[-1]["issue"]) + 1),
                "stake": 6250,
                "tier": 2,
                "step": 1,
                "rule": None,
            },
            "waiting_rule": None,
            "today_pnl": 7730,
            "risk_status": "OBSERVE ONLY — DAILY TP REACHED",
            "working_bankroll": 100000,
            "daily_tp": 5000,
            "daily_sl": 50000,
            "today": "2026-09-20",
            "withdraw_milestone": 50000,
            "withdraw_milestones_reached": 1,
            "model_total_pnl": 92600,
            "last_trade": {
                "time": "2026-09-20 14:04:00",
                "issue": "20260920103019998",
                "target": "BIG",
                "actual": "BIG",
                "stake": 3000,
                "tier": 1,
                "step": 4,
                "won": True,
                "pnl": 2880,
            },
            "trades": [
                {"time": "2026-09-19 23:59:00", "stake": 500, "tier": 1, "step": 1, "won": True},
                {"time": "2026-09-20 14:00:00", "stake": 500, "tier": 1, "step": 1, "won": False},
                {"time": "2026-09-20 14:01:00", "stake": 1000, "tier": 1, "step": 2, "won": True},
                {"time": "2026-09-20 14:02:00", "stake": 6250, "tier": 2, "step": 1, "won": False},
                {"time": "2026-09-20 14:03:00", "stake": 12500, "tier": 2, "step": 2, "won": True},
                {"time": "2026-09-20 14:04:00", "stake": 3000, "tier": 1, "step": 4, "won": True},
            ],
        }
    )


@app.route("/api/<path:_path>", methods=["GET", "POST", "PUT"])
def generic_api(_path):
    return jsonify({"ok": True})


# Exercise the real admin auth/settings API against deterministic fixture engines.
import sys
import tempfile
import threading
from types import SimpleNamespace
sys.path.insert(0, str(ROOT))
from admin_dashboard import install_admin, AdminStore
from werkzeug.security import generate_password_hash
_admin_core = SimpleNamespace(app=app, LOCK=threading.RLock(), STATE={'strat_log': []}, signal_history=[],
                              load_tg_config=lambda: ('fixture', 'fixture'),
                              _engine_thread=SimpleNamespace(is_alive=lambda: True),
                              _send_telegram=lambda text, cfg: 'sent', api_strat_daily_report=api_daily12)
_admin_health = lambda: jsonify(ok=True, status='LIVE', engine={'connected':True,'full_history_rows':43200,'thread_alive':True},
                               feed={'last_issue':ROWS[-1]['issue'],'result_age_sec':2}, queues={'telegram_worker_alive':True},uptime_sec=120)
install_admin(_admin_core, _admin_health, SimpleNamespace(public_snapshot=lambda: api_l1_capital().get_json()),
              lambda: None, password_hash=generate_password_hash('fixture-admin-password'),
              store=AdminStore(Path(tempfile.mkdtemp())/'admin.sqlite3'))

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=4173, debug=False, use_reloader=False)


