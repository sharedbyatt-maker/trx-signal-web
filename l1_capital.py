# -*- coding: utf-8 -*-
"""L1 CAPITAL manual-execution observer.

Additive only: reproduces the frozen L1 signal/stake path from trx-strategy-lab
with Base=500 and payout=1.96, then sends clearly namespaced Telegram alerts.
It never places bets and never suppresses signals after TP/SL; TP/SL only change
the displayed risk status to OBSERVE ONLY.
"""
import json
import os
import threading
import time

ENGINE_NAME = "L1 CAPITAL"
VERSION = "1.1"
RSI_PERIOD = 14
OVERSOLD = 32.0
OVERBOUGHT = 68.0
PAYOUT = 1.96
WORKING_BANKROLL = 100_000
DAILY_TP = 5_000
DAILY_SL = 50_000
WITHDRAW_MILESTONE = 50_000
# Frozen production ladder [200,400,600,1200] ... scaled by Base 500 / 200.
STAKES = [
    [500, 1000, 1500, 3000],
    [6250, 12500, 25000, 50000],
    [100000, 200000, 400000, 800000],
]
# Frozen L1 rules: R02, R03, R05, R06.
RULES = (
    {"id": "R02", "when": {"rsi_bucket": "70-79", "step": 1}, "skip": 3},
    {"id": "R03", "when": {"rsi_direction": "rising", "step": 2}, "skip": 2},
    {"id": "R05", "when": {"rsi_direction": "falling", "step": 1}, "skip": 3},
    {"id": "R06", "when": {"rsi_direction": "rising", "step": 1}, "skip": 1},
)


def _rsi(values, period=RSI_PERIOD):
    out = [None] * len(values)
    if len(values) <= period:
        return out
    ag = al = 0.0
    for i in range(1, period + 1):
        d = values[i] - values[i - 1]
        ag += max(d, 0); al += max(-d, 0)
    ag /= period; al /= period
    out[period] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    for i in range(period + 1, len(values)):
        d = values[i] - values[i - 1]
        ag = (ag * (period - 1) + max(d, 0)) / period
        al = (al * (period - 1) + max(-d, 0)) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def _bucket(v):
    if v is None:
        return "none"
    lo = int(v // 10) * 10
    return f"{lo}-{lo+9}"


def _rule_skip(rsi, i, step):
    direction = "flat"
    if i >= 1 and rsi[i] is not None and rsi[i-1] is not None:
        direction = "rising" if rsi[i] > rsi[i-1] else ("falling" if rsi[i] < rsi[i-1] else "flat")
    ctx = {"rsi_bucket": _bucket(rsi[i]), "rsi_direction": direction, "step": step}
    for rule in RULES:
        if all(ctx.get(k) == v for k, v in rule["when"].items()):
            return rule["skip"], rule["id"]
    return 0, None


def replay_l1(rows):
    """Deterministic shadow replay over completed rows; returns current next-bet state."""
    rows = [r for r in rows if r.get("issue") and r.get("type") in ("BIG", "SMALL")]
    if len(rows) < RSI_PERIOD + 3:
        return {"ready": False, "reason": "warming up", "trades": [], "pending": None}

    walk = []
    close = 100
    for r in rows:
        close += 1 if r["type"] == "BIG" else -1
        walk.append(close)
    rsi = _rsi(walk)

    tier = 0
    active = None
    wait = None
    trades = []
    last_rule = None

    # Same causal order as frozen rule_replay.py. rows[i+1] is the target round.
    for i in range(1, len(rows) - 1):
        cur, nxt = rows[i], rows[i + 1]
        if wait and i >= wait["enter_i"]:
            active = dict(wait)
            active["issue"] = nxt["issue"]
            active.pop("enter_i", None)
            wait = None

        if active and cur["issue"] == active["issue"]:
            stake = active["stake"]
            won = cur["type"] == active["target"]
            active["bets"] += 1
            pnl = int(round(stake * PAYOUT)) - stake if won else -stake
            trades.append({
                "issue": cur["issue"], "time": cur.get("block_time", ""),
                "target": active["target"], "actual": cur["type"],
                "tier": active["tier"] + 1, "step": active["bets"],
                "stake": stake, "pnl": pnl, "won": won,
            })
            if won:
                tier = 0
                active = None
            elif active["bets"] < len(STAKES[active["tier"]]):
                next_stake = STAKES[active["tier"]][active["bets"]]
                skip, rid = _rule_skip(rsi, i, active["bets"])
                last_rule = rid
                if skip:
                    wait = {
                        "enter_i": i + skip, "target": active["target"],
                        "tier": active["tier"], "stake": next_stake,
                        "bets": active["bets"], "rule": rid,
                    }
                    active = None
                else:
                    active["stake"] = next_stake
                    active["issue"] = nxt["issue"]
            elif active["tier"] >= len(STAKES) - 1:
                tier = 0
                active = None
            else:
                # Frozen preset uses next_tier + fresh_signal.
                tier = active["tier"] + 1
                active = None
        elif active:
            try:
                if int(cur["issue"]) > int(active["issue"]):
                    active = None
            except (TypeError, ValueError):
                active = None

        if active is None and wait is None:
            rp = rsi[i - 1]
            signal = None
            if rp is not None and rp <= OVERSOLD and cur["type"] == "BIG":
                signal = "BIG"
            elif rp is not None and rp >= OVERBOUGHT and cur["type"] == "SMALL":
                signal = "SMALL"
            if signal:
                active = {
                    "issue": nxt["issue"], "target": signal, "tier": tier,
                    "stake": STAKES[tier][0], "bets": 0, "trigger_rsi": rp,
                    "rule": None,
                }

    # Evaluate the newest completed round as a signal source for the next issue.
    # The research replay normally arms a matured skip at the top of the next
    # loop iteration. Live replay has no future row yet, so perform that same
    # transition here and let the service bind it to core.STATE[next_issue].
    i = len(rows) - 1
    cur = rows[i]
    if wait and i >= wait["enter_i"]:
        active = dict(wait)
        active["issue"] = None
        active.pop("enter_i", None)
        wait = None
    if active and cur["issue"] == active["issue"]:
        stake = active["stake"]
        won = cur["type"] == active["target"]
        active["bets"] += 1
        pnl = int(round(stake * PAYOUT)) - stake if won else -stake
        trades.append({
            "issue": cur["issue"], "time": cur.get("block_time", ""),
            "target": active["target"], "actual": cur["type"],
            "tier": active["tier"] + 1, "step": active["bets"],
            "stake": stake, "pnl": pnl, "won": won,
        })
        if won:
            tier = 0; active = None
        elif active["bets"] < len(STAKES[active["tier"]]):
            next_stake = STAKES[active["tier"]][active["bets"]]
            skip, rid = _rule_skip(rsi, i, active["bets"])
            last_rule = rid
            if skip:
                wait = {"enter_i": i + skip, "target": active["target"], "tier": active["tier"],
                        "stake": next_stake, "bets": active["bets"], "rule": rid}
                active = None
            else:
                active["stake"] = next_stake
                active["issue"] = None  # service fills exact next issue from core.STATE
        elif active["tier"] >= len(STAKES) - 1:
            tier = 0; active = None
        else:
            tier = active["tier"] + 1; active = None

    if active is None and wait is None:
        rp = rsi[i - 1]
        signal = None
        if rp is not None and rp <= OVERSOLD and cur["type"] == "BIG":
            signal = "BIG"
        elif rp is not None and rp >= OVERBOUGHT and cur["type"] == "SMALL":
            signal = "SMALL"
        if signal:
            active = {"issue": None, "target": signal, "tier": tier, "stake": STAKES[tier][0],
                      "bets": 0, "trigger_rsi": rp, "rule": None}

    today = str(cur.get("block_time") or "")[:10]
    today_trades = [t for t in trades if str(t.get("time") or "")[:10] == today]
    day_pnl = sum(t["pnl"] for t in today_trades)
    total_pnl = sum(t["pnl"] for t in trades)
    risk = "TRADE ALLOWED"
    if day_pnl >= DAILY_TP:
        risk = "OBSERVE ONLY — DAILY TP REACHED"
    elif day_pnl <= -DAILY_SL:
        risk = "OBSERVE ONLY — DAILY SL REACHED"
    withdraw_units = max(0, total_pnl // WITHDRAW_MILESTONE)

    pending = None
    if active:
        pending = dict(active)
        pending["tier"] = active["tier"] + 1
        pending["step"] = active["bets"] + 1
    return {
        "ready": True, "engine": ENGINE_NAME, "version": VERSION,
        "pending": pending, "waiting_rule": dict(wait) if wait else None,
        "last_rule": last_rule, "trades": trades[-100:],
        "today": today, "today_pnl": day_pnl, "model_total_pnl": total_pnl,
        "working_bankroll": WORKING_BANKROLL, "daily_tp": DAILY_TP,
        "daily_sl": DAILY_SL, "withdraw_milestone": WITHDRAW_MILESTONE,
        "withdraw_milestones_reached": withdraw_units, "risk_status": risk,
        "last_trade": trades[-1] if trades else None,
    }


def _fmt_signal(s):
    p = s["pending"]
    rule = f" · after {p.get('rule')}" if p.get("rule") else ""
    rsi = p.get("trigger_rsi")
    rsi_line = f"Trigger RSI: {rsi:.1f}\n" if isinstance(rsi, (int, float)) else ""
    return (
        f"🟦 [{ENGINE_NAME}] — SIGNAL\n\n"
        f"🎯 Target: {p['target']}\n"
        f"🎫 Issue: {str(p.get('issue') or '')}\n"
        f"💰 BET: {int(p['stake']):,} MMK\n"
        f"📶 Level: T{p['tier']}-S{p['step']}{rule}\n"
        f"{rsi_line}\n"
        f"Model Today P/L: {int(s['today_pnl']):+,} MMK\n"
        f"Daily TP: +{DAILY_TP:,} · Daily SL: -{DAILY_SL:,}\n"
        f"Working BR: {WORKING_BANKROLL:,} MMK\n"
        f"Status: {'🟢' if s['risk_status']=='TRADE ALLOWED' else '🟨'} {s['risk_status']}\n\n"
        "Manual execution only · L1 CAPITAL never places a bet automatically."
    )


def _fmt_withdrawal_milestone(units):
    amount = int(units) * WITHDRAW_MILESTONE
    return (
        f"💰 {ENGINE_NAME} — WITHDRAWAL MILESTONE\n\n"
        f"{amount:,} MMK profit milestone reached.\n"
        "Informational only · withdraw manually."
    )


class L1CapitalService:
    def __init__(self, core, state_file=None):
        self.core = core
        self._thread = None
        self._stop = threading.Event()
        self._last_alert_key = None
        self._last_withdraw_units = 0
        self._state_file = (os.path.join(getattr(core, "BASE_DIR", "."), "l1_capital_runtime.json")
                            if state_file is None else state_file)
        self.snapshot = {"ready": False, "engine": ENGINE_NAME, "version": VERSION}
        self._load_runtime_state()

    def _load_runtime_state(self):
        if not self._state_file:
            return
        try:
            with open(self._state_file, "r", encoding="utf-8") as handle:
                saved = json.load(handle)
            key = saved.get("last_alert_key")
            if isinstance(key, list) and len(key) == 5:
                self._last_alert_key = tuple(key)
            self._last_withdraw_units = max(0, int(saved.get("last_withdraw_units") or 0))
        except (OSError, ValueError, TypeError):
            pass

    def _save_runtime_state(self):
        if not self._state_file:
            return
        tmp = self._state_file + f".tmp.{os.getpid()}.{threading.get_ident()}"
        try:
            with open(tmp, "w", encoding="utf-8") as handle:
                json.dump({
                    "last_alert_key": list(self._last_alert_key) if self._last_alert_key else None,
                    "last_withdraw_units": self._last_withdraw_units,
                }, handle)
            os.replace(tmp, self._state_file)
        except OSError:
            try:
                if os.path.exists(tmp):
                    os.unlink(tmp)
            except OSError:
                pass

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, name="l1-capital", daemon=True)
        self._thread.start()

    def _loop(self):
        while not self._stop.is_set():
            try:
                self.refresh_once()
                time.sleep(0.5)
            except Exception as exc:
                self.snapshot = {"ready": False, "engine": ENGINE_NAME, "version": VERSION,
                                 "error": f"{type(exc).__name__}: {exc}"}
                time.sleep(2.0)

    def refresh_once(self):
        """Build and publish one snapshot; split out for deterministic tests."""
        with self.core.LOCK:
            rows = list(self.core.STATE.get("full_history") or self.core.STATE.get("history") or [])
            next_issue = self.core.STATE.get("next_issue")
        if not rows:
            return self.snapshot
        snap = replay_l1(rows)
        if snap.get("pending") and next_issue:
            snap["pending"]["issue"] = str(next_issue)
        self.snapshot = snap
        p = snap.get("pending")
        if p and p.get("issue"):
            key = (str(p["issue"]), p["target"], int(p["stake"]), int(p["tier"]), int(p["step"]))
            if key != self._last_alert_key:
                self.core.tg_notify(_fmt_signal(snap))
                self._last_alert_key = key
                self._save_runtime_state()
        units = int(snap.get("withdraw_milestones_reached") or 0)
        if units > self._last_withdraw_units:
            for milestone in range(self._last_withdraw_units + 1, units + 1):
                self.core.tg_notify(_fmt_withdrawal_milestone(milestone))
            self._last_withdraw_units = units
            self._save_runtime_state()
        # A no-signal round must not erase the prior key; a future different
        # issue naturally generates a fresh alert.
        return snap


def install_l1_capital(core):
    service = L1CapitalService(core)

    @core.app.route("/api/l1-capital")
    def l1_capital_state():
        return core.jsonify(service.snapshot)

    return service
