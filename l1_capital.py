# -*- coding: utf-8 -*-
"""L1 CAPITAL manual-execution observer.

Additive only: reproduces the frozen L1 signal/stake path from trx-strategy-lab
with Base=500 and payout=1.96, then sends clearly namespaced Telegram alerts.
It never places bets and never suppresses signals after TP/SL; TP/SL only change
the displayed risk status to OBSERVE ONLY.
"""
from strategy_settings import MONEY_DEFAULTS, MoneySchedule, ladder, risk_status
import json
import os
import threading
import time

ENGINE_NAME = "L1 CAPITAL"
VERSION = "1.2"
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


def replay_l1(rows, money_changes=(), issued_stakes=None, current_money=None):
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

    schedule=MoneySchedule("l1",money_changes)
    issued_stakes=issued_stakes or {}
    tier = 0
    active = None
    wait = None
    trades = []
    last_rule = None

    # Same causal order as frozen rule_replay.py. rows[i+1] is the target round.
    for i in range(1, len(rows) - 1):
        cur, nxt = rows[i], rows[i + 1]
        stakes=schedule.ladder_at(cur["issue"])
        if wait and i >= wait["enter_i"]:
            active = dict(wait)
            active["issue"] = nxt["issue"]
            active["stake"]=stakes[active["tier"]][active["bets"]]
            active.pop("enter_i", None)
            wait = None

        if active and cur["issue"] == active["issue"]:
            stake = issued_stakes.get(str(cur["issue"]),active["stake"])
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
                next_stake = stakes[active["tier"]][active["bets"]]
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
                    "stake": stakes[tier][0], "bets": 0, "trigger_rsi": rp,
                    "rule": None,
                }

    # Evaluate the newest completed round as a signal source for the next issue.
    # The research replay normally arms a matured skip at the top of the next
    # loop iteration. Live replay has no future row yet, so perform that same
    # transition here and let the service bind it to core.STATE[next_issue].
    i = len(rows) - 1
    cur = rows[i]
    stakes=schedule.ladder_at(cur["issue"])
    money=current_money or schedule.at(cur["issue"])
    if wait and i >= wait["enter_i"]:
        active = dict(wait)
        active["issue"] = None
        active["stake"]=stakes[active["tier"]][active["bets"]]
        active.pop("enter_i", None)
        wait = None
    if active and cur["issue"] == active["issue"]:
        stake = issued_stakes.get(str(cur["issue"]),active["stake"])
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
            next_stake = stakes[active["tier"]][active["bets"]]
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
            active = {"issue": None, "target": signal, "tier": tier, "stake": stakes[tier][0],
                      "bets": 0, "trigger_rsi": rp, "rule": None}

    today = str(cur.get("block_time") or "")[:10]
    today_trades = [t for t in trades if str(t.get("time") or "")[:10] == today]
    day_pnl = sum(t["pnl"] for t in today_trades)
    day_wins = sum(1 for t in today_trades if t["won"])
    deepest = max(today_trades, key=lambda t: (t["tier"], t["step"]), default=None)
    daily_summary = {
        "bets": len(today_trades), "wins": day_wins,
        "losses": len(today_trades) - day_wins,
        "win_rate": round(100 * day_wins / len(today_trades), 1) if today_trades else 0,
        "staked": sum(t["stake"] for t in today_trades), "pnl": day_pnl,
        "max_tier": deepest["tier"] if deepest else None,
        "max_step": deepest["step"] if deepest else None,
    }
    total_pnl = sum(t["pnl"] for t in trades)
    risk = risk_status(money,day_pnl)
    withdraw_units = max(0, total_pnl // money['withdrawal'])

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
        "daily_summary": daily_summary,
        "money_settings": money, "money_ladder":ladder(money),
        "working_bankroll": money["bankroll"], "daily_tp": money["tp"],
        "daily_sl": money["sl"], "withdraw_milestone": money["withdrawal"],
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


def _fmt_result(s):
    t = s["last_trade"]
    won = bool(t.get("won"))
    title = "✅ WIN" if won else "❌ LOSS"
    pnl = int(t.get("pnl") or 0)
    next_line = "Next: WAIT — fresh L1 setup"
    p = s.get("pending")
    w = s.get("waiting_rule")
    if p:
        next_line = f"Next: {p['target']} · {int(p['stake']):,} MMK · T{p['tier']}-S{p['step']}"
    elif w:
        next_line = (f"Next: WAIT · {w.get('rule') or 'RULE'} · "
                     f"{int(w.get('stake') or 0):,} MMK · "
                     f"T{int(w.get('tier') or 0)+1}-S{int(w.get('bets') or 0)+1}")
    return (
        f"{title} [{ENGINE_NAME}] — RESULT\n\n"
        f"🎫 Issue: {t.get('issue') or ''}\n"
        f"🎯 Signal: {t.get('target') or '—'} · Actual: {t.get('actual') or '—'}\n"
        f"💰 Stake: {int(t.get('stake') or 0):,} MMK\n"
        f"📶 Level: T{int(t.get('tier') or 0)}-S{int(t.get('step') or 0)}\n"
        f"💵 P/L: {pnl:+,} MMK\n"
        f"📊 Today: {int(s.get('today_pnl') or 0):+,} MMK\n"
        f"➡️ {next_line}\n"
        f"Status: {'🟢' if s.get('risk_status')=='TRADE ALLOWED' else '🟨'} {s.get('risk_status') or '—'}"
    )


def _fmt_wait(s):
    w = s.get("waiting_rule")
    if w:
        return (
            f"⏳ [{ENGINE_NAME}] — WAIT / SKIP\n\n"
            f"Rule: {w.get('rule') or '—'}\n"
            f"Target: {w.get('target') or '—'}\n"
            f"Next Bet: {int(w.get('stake') or 0):,} MMK\n"
            f"Level: T{int(w.get('tier') or 0)+1}-S{int(w.get('bets') or 0)+1}\n"
            f"Today: {int(s.get('today_pnl') or 0):+,} MMK\n"
            f"Status: {'🟢' if s.get('risk_status')=='TRADE ALLOWED' else '🟨'} {s.get('risk_status') or '—'}\n\n"
            "NO BET · Wait for next L1 signal."
        )
    return (
        f"⏳ [{ENGINE_NAME}] — WAIT\n\n"
        f"Today: {int(s.get('today_pnl') or 0):+,} MMK\n"
        f"Status: {'🟢' if s.get('risk_status')=='TRADE ALLOWED' else '🟨'} {s.get('risk_status') or '—'}\n\n"
        "NO BET · Waiting for fresh L1 setup."
    )


def _fmt_withdrawal_milestone(units, amount=WITHDRAW_MILESTONE):
    amount = int(units) * amount
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
        self._last_result_key = None
        self._last_wait_key = None
        self._last_mode = None
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
            result_key = saved.get("last_result_key")
            if isinstance(result_key, list) and len(result_key) == 6:
                self._last_result_key = tuple(result_key)
            wait_key = saved.get("last_wait_key")
            if isinstance(wait_key, list) and len(wait_key) == 5:
                self._last_wait_key = tuple(wait_key)
            mode = saved.get("last_mode")
            if mode in ("SIGNAL", "WAIT_RULE", "WAIT"):
                self._last_mode = mode
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
                    "last_result_key": list(self._last_result_key) if self._last_result_key else None,
                    "last_wait_key": list(self._last_wait_key) if self._last_wait_key else None,
                    "last_mode": self._last_mode,
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

    def _notify(self,text,category):
        fn=self.core.tg_notify
        return fn(text,engine='l1',category=category) if getattr(fn,'supports_metadata',False) else fn(text)

    def refresh_once(self):
        """Build and publish one snapshot; split out for deterministic tests."""
        with self.core.LOCK:
            rows = list(self.core.STATE.get("full_history") or self.core.STATE.get("history") or [])
            next_issue = self.core.STATE.get("next_issue")
        if not rows:
            return self.public_snapshot()
        store=getattr(self.core,"_admin_store",None)
        changes,issued,current=store.money_snapshot("l1") if store else ((),{},None)
        snap = replay_l1(rows, money_changes=changes, issued_stakes=issued, current_money=current)
        snap["source_issue"] = str(rows[-1]["issue"])
        if snap.get("pending") and next_issue:
            snap["pending"]["issue"] = str(next_issue)
        if store and snap.get("pending") and next_issue:
            snap["pending"]["stake"]=store.lock_stake(str(next_issue),snap["pending"]["stake"])
        if store and snap.get("ready"):
            snap["risk_status"]=risk_status(store.control("l1")["settings"],snap.get("today_pnl",0),int((snap.get("pending") or {}).get("stake") or 0))
        self.snapshot = snap
        published = self.public_snapshot()
        if not published.get("ready"):
            return published
        # Lifecycle notifications are observational only. They never mutate
        # frozen L1 signal/stake/risk state and all reuse the legacy tg_notify queue.
        last_trade = snap.get("last_trade")
        if last_trade:
            result_key = (
                str(last_trade.get("issue") or ""), str(last_trade.get("target") or ""),
                int(last_trade.get("stake") or 0), int(last_trade.get("tier") or 0),
                int(last_trade.get("step") or 0), bool(last_trade.get("won")),
            )
            if result_key != self._last_result_key:
                if self._notify(_fmt_result(snap),"result"):
                    self._last_result_key = result_key
                    self._save_runtime_state()

        p = snap.get("pending")
        wait = snap.get("waiting_rule")
        if p and p.get("issue"):
            key = (str(p["issue"]), p["target"], int(p["stake"]), int(p["tier"]), int(p["step"]))
            if key != self._last_alert_key:
                if not self._notify(_fmt_signal(snap),"signal"):
                    return published
                self._last_alert_key = key
            self._last_mode = "SIGNAL"
            self._last_wait_key = None
            self._save_runtime_state()
        elif wait:
            wait_key = (
                str(wait.get("rule") or ""), str(wait.get("target") or ""),
                int(wait.get("stake") or 0), int(wait.get("tier") or 0),
                int(wait.get("bets") or 0),
            )
            if self._last_mode != "WAIT_RULE" or wait_key != self._last_wait_key:
                if not self._notify(_fmt_wait(snap),"wait"):
                    return published
                self._last_wait_key = wait_key
            self._last_mode = "WAIT_RULE"
            self._save_runtime_state()
        elif self._last_mode != "WAIT":
            if not self._notify(_fmt_wait(snap),"wait"):
                return published
            self._last_mode = "WAIT"
            self._last_wait_key = None
            self._save_runtime_state()

        units = int(snap.get("withdraw_milestones_reached") or 0)
        if units > self._last_withdraw_units:
            for milestone in range(max(self._last_withdraw_units + 1,units - 4), units + 1):
                if not self._notify(_fmt_withdrawal_milestone(milestone,snap.get("withdraw_milestone",WITHDRAW_MILESTONE)),"withdrawal"):
                    break
                self._last_withdraw_units = milestone
                self._save_runtime_state()
        # A no-signal round must not erase the prior key; a future different
        # issue naturally generates a fresh alert.
        return published

    def public_snapshot(self):
        """Recheck freshness on every API read, even if the observer thread stalls."""
        snap = dict(self.snapshot)
        with self.core.LOCK:
            state = self.core.STATE
            connected = bool(state.get("connected"))
            health = dict(state.get("feed_health") or {})
            received = state.get("last_result_received_mono")
            source_delay = state.get("feed_delay")
            rows = state.get("full_history") or state.get("history") or []
            latest_issue = str(rows[-1]["issue"]) if rows else None
        age = max(0, time.monotonic() - received) if received is not None else None
        if age is not None and source_delay is not None:
            age += max(0, source_delay)
        status = str(health.get("status") or ("LIVE" if connected else "OFFLINE"))
        if not connected:
            status = "OFFLINE"
        elif age is None or age >= getattr(self.core, "FEED_STALE_SEC", 80):
            status = "STALE"
        elif snap.get("source_issue") != latest_issue:
            status = "SYNCING"
        fresh = connected and status in ("LIVE", "DEGRADED")
        snap.update({"feed_status": status, "age_sec": round(age, 1) if age is not None else None,
                     "stale": not fresh})
        if not fresh:
            snap.update({"ready": False, "pending": None, "waiting_rule": None,
                         "reason": "FEED " + status,
                         "risk_status": "OBSERVE ONLY — FEED " + status})
        return snap


def install_l1_capital(core):
    service = L1CapitalService(core)

    @core.app.route("/api/l1-capital")
    def l1_capital_state():
        return core.jsonify(service.public_snapshot())

    return service

