# -*- coding: utf-8 -*-
"""Independent frozen Robust Signal Engine.

Signal, staking and risk rules reproduce trx_trade_dd_monte_carlo_audit.py.
This module does not import or mutate the legacy engine.
"""
from __future__ import annotations

import copy
import json
import os
import statistics
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path

PAYOUT = 1.96
INITIAL_DEPOSIT = 300000

FAST_EMA = 5
SLOW_EMA = 15
RSI_PERIOD = 14
MOM_WINDOW = 10
VOL_WINDOW = 20
LONG_WINDOW = 100
SR_WINDOW = 50
SR_WEIGHT = 1.2

SCORE_THRESHOLD = 40.0
RSI_LOW = 42.0
RSI_HIGH = 58.0
VOL_MIN = 2.2
BASE_STAKE = 1000
PAROLI_WINS = 4
DAILY_TP = 10000
DAILY_SL = 8000

STATE_VERSION = 1


def ema_series(vals, period):
    out = [None] * len(vals)
    if len(vals) < period:
        return out
    e = sum(vals[:period]) / period
    out[period - 1] = e
    k = 2.0 / (period + 1)
    for i in range(period, len(vals)):
        e = vals[i] * k + e * (1 - k)
        out[i] = e
    return out


def rsi_series(nums, period=RSI_PERIOD):
    out = [None] * len(nums)
    if len(nums) < period + 1:
        return out
    g = l = 0.0
    for i in range(1, period + 1):
        d = nums[i] - nums[i - 1]
        if d > 0:
            g += d
        else:
            l -= d
    ag, al = g / period, l / period
    for i in range(period, len(nums)):
        if i > period:
            d = nums[i] - nums[i - 1]
            ag = (ag * (period - 1) + max(d, 0)) / period
            al = (al * (period - 1) + max(-d, 0)) / period
        out[i] = 100.0 if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    return out


def normalize_history(rows):
    """Copy/normalize existing completed-round rows without mutating the source."""
    out = []
    seen = set()
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        issue = str(raw.get("issue") or raw.get("issueNumber") or "")
        val = raw.get("number") if raw.get("number") is not None else raw.get("result")
        if not issue or val is None or issue in seen:
            continue
        try:
            num = int(val)
        except (TypeError, ValueError):
            continue
        if num < 0 or num > 9:
            continue
        typ = raw.get("type")
        typ = typ if typ in ("BIG", "SMALL") else ("BIG" if num >= 5 else "SMALL")
        bt = str(raw.get("block_time") or raw.get("blockTime") or raw.get("time") or "")
        date = str(raw.get("date") or (bt[:10] if len(bt) >= 10 else ""))
        if not date and len(issue) >= 8 and issue[:8].isdigit():
            date = f"{issue[:4]}-{issue[4:6]}-{issue[6:8]}"
        out.append({
            "issue": issue,
            "number": num,
            "type": typ,
            "date": date,
            "block_time": bt,
        })
        seen.add(issue)
    return out


def _feature_from_prefix(history):
    """Feature for the NEXT round using only completed rows in history."""
    n = len(history)
    start_need = max(LONG_WINDOW, VOL_WINDOW, SR_WINDOW, SLOW_EMA) + 5
    if n < start_need:
        return None

    m = [1 if x["type"] == "BIG" else -1 for x in history]
    nums = [x["number"] for x in history]
    closes = []
    c = 100
    for x in history:
        c += 1 if x["type"] == "BIG" else -1
        closes.append(c)

    prev = n - 1
    walk_rsi = rsi_series(closes, RSI_PERIOD)[prev]
    digit_rsi = rsi_series(nums, RSI_PERIOD)[prev]
    ef = ema_series(m, FAST_EMA)[prev]
    es = ema_series(m, SLOW_EMA)[prev]
    if walk_rsi is None or digit_rsi is None or ef is None or es is None:
        return None

    vol_slice = nums[-VOL_WINDOW:]
    if len(vol_slice) < VOL_WINDOW:
        return None
    vol = statistics.pstdev(vol_slice)

    trend_diff = ef - es
    t_score = max(-30.0, min(30.0, trend_diff * 250))

    mom = sum(m[-MOM_WINDOW:]) / MOM_WINDOW
    m_score = max(-20.0, min(20.0, mom * 40))

    r_score = -15.0 if digit_rsi >= 70 else (15.0 if digit_rsi <= 30 else 0.0)

    st = 0
    j = prev
    while j >= 0 and m[j] == m[prev] and st < 40:
        st += 1
        j -= 1
    st_score = 0.0
    if st >= 4:
        st_score = min((st - 3) * 8, 24)
        if m[prev] == 1:
            st_score = -st_score

    big_count = sum(1 for x in history[-LONG_WINDOW:] if x["type"] == "BIG")
    small_count = LONG_WINDOW - big_count
    g_score = max(-24.0, min(24.0, -(big_count - small_count) * 0.6))

    freq = Counter(nums[-SR_WINDOW:])
    sup_t = sum(freq[d] for d in range(0, 4))
    res_t = sum(freq[d] for d in range(7, 10))
    sr_score = max(-18.0, min(18.0, (sup_t - res_t) * SR_WEIGHT))

    return {
        "walk_rsi": walk_rsi,
        "prev_type": history[prev]["type"],
        "vol": vol,
        "score": t_score + m_score + r_score + st_score + g_score + sr_score,
        "components": {
            "ema": t_score,
            "momentum": m_score,
            "digit_rsi": r_score,
            "streak": st_score,
            "gap": g_score,
            "support_resistance": sr_score,
        },
    }


def signal_for_next(rows):
    history = normalize_history(rows)
    f = _feature_from_prefix(history)
    if not f:
        return {"signal": "NO TRADE", "ready": False, "score": 0.0, "walk_rsi": None, "vol": None}

    signal = "NO TRADE"
    strat = None
    if f["vol"] >= VOL_MIN:
        if f["walk_rsi"] <= RSI_LOW and f["prev_type"] == "BIG":
            strat = "BIG"
        elif f["walk_rsi"] >= RSI_HIGH and f["prev_type"] == "SMALL":
            strat = "SMALL"

        if strat is not None and abs(f["score"]) >= SCORE_THRESHOLD:
            conf = "BIG" if f["score"] > 0 else "SMALL"
            if conf == strat:
                signal = strat

    return {
        "signal": signal,
        "ready": True,
        "score": f["score"],
        "walk_rsi": f["walk_rsi"],
        "vol": f["vol"],
        "prev_type": f["prev_type"],
        "components": f["components"],
    }


def precompute_features(history):
    """Exact batch feature implementation from the reference audit."""
    history = normalize_history(history)
    total = len(history)
    m = [1 if x["type"] == "BIG" else -1 for x in history]
    nums = [x["number"] for x in history]

    c = 100
    closes = []
    for x in history:
        c += 1 if x["type"] == "BIG" else -1
        closes.append(c)

    walk_rsi = rsi_series(closes, RSI_PERIOD)
    ef = ema_series(m, FAST_EMA)
    es = ema_series(m, SLOW_EMA)
    digit_rsi = rsi_series(nums, RSI_PERIOD)

    pref_big = [0] * (total + 1)
    for idx, x in enumerate(history):
        pref_big[idx + 1] = pref_big[idx] + (1 if x["type"] == "BIG" else 0)

    start_need = max(LONG_WINDOW, VOL_WINDOW, SR_WINDOW, SLOW_EMA) + 5
    feat = [None] * total

    for i in range(start_need, total):
        prev = i - 1
        vol_slice = nums[prev - VOL_WINDOW + 1:prev + 1]
        if len(vol_slice) < VOL_WINDOW:
            continue
        vol = statistics.pstdev(vol_slice)

        trend_diff = ef[prev] - es[prev]
        t_score = max(-30.0, min(30.0, trend_diff * 250))

        mom = sum(m[prev - MOM_WINDOW + 1:prev + 1]) / MOM_WINDOW
        m_score = max(-20.0, min(20.0, mom * 40))

        dr = digit_rsi[prev]
        r_score = -15.0 if dr >= 70 else (15.0 if dr <= 30 else 0.0)

        st = 0
        j = prev
        while j >= 0 and m[j] == m[prev] and st < 40:
            st += 1
            j -= 1

        st_score = 0.0
        if st >= 4:
            st_score = min((st - 3) * 8, 24)
            if m[prev] == 1:
                st_score = -st_score

        big_count = pref_big[prev + 1] - pref_big[prev + 1 - LONG_WINDOW]
        small_count = LONG_WINDOW - big_count
        g_score = max(-24.0, min(24.0, -(big_count - small_count) * 0.6))

        freq = Counter(nums[prev - SR_WINDOW + 1:prev + 1])
        sup_t = sum(freq[d] for d in range(0, 4))
        res_t = sum(freq[d] for d in range(7, 10))
        sr_score = max(-18.0, min(18.0, (sup_t - res_t) * SR_WEIGHT))

        feat[i] = {
            "walk_rsi": walk_rsi[prev],
            "prev_type": history[prev]["type"],
            "vol": vol,
            "score": t_score + m_score + r_score + st_score + g_score + sr_score,
        }
    return feat


def build_signals(history, feat=None):
    history = normalize_history(history)
    feat = precompute_features(history) if feat is None else feat
    signals = [None] * len(history)
    for i, f in enumerate(feat):
        if not f or f["walk_rsi"] is None or f["vol"] < VOL_MIN:
            continue
        strat = None
        if f["walk_rsi"] <= RSI_LOW and f["prev_type"] == "BIG":
            strat = "BIG"
        elif f["walk_rsi"] >= RSI_HIGH and f["prev_type"] == "SMALL":
            strat = "SMALL"
        if strat is None or abs(f["score"]) < SCORE_THRESHOLD:
            continue
        conf = "BIG" if f["score"] > 0 else "SMALL"
        if conf == strat:
            signals[i] = strat
    return signals


def _default_state():
    return {
        "version": STATE_VERSION,
        "bankroll": INITIAL_DEPOSIT,
        "initial_capital": INITIAL_DEPOSIT,
        "peak_equity": INITIAL_DEPOSIT,
        "current_drawdown": 0,
        "max_drawdown": 0,
        "wins": 0,
        "losses": 0,
        "total_trades": 0,
        "paroli_step": 0,
        "current_stake": BASE_STAKE,
        "daily_date": None,
        "daily_profit": 0,
        "daily_stopped": False,
        "signal": "NO TRADE",
        "status": "NO TRADE",
        "score": 0.0,
        "walk_rsi": None,
        "vol": None,
        "pending": None,
        "last_processed_issue": None,
        "processed_issues": [],
        "last_result": None,
        "last_update": None,
        "last_error": None,
        "notification_event_ids": [],
    }


def _issue_date(issue):
    s = str(issue or "")
    if len(s) >= 8 and s[:8].isdigit():
        try:
            return datetime.strptime(s[:8], "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            return None
    return None


class RobustEngine:
    """Thread-safe live state machine for the independent Robust Engine."""

    def __init__(self, state_path=None):
        base = Path(__file__).resolve().parent
        self.state_path = Path(state_path or os.environ.get("ROBUST_STATE_FILE") or (base / "robust_state.json"))
        self.lock = threading.RLock()
        self.state = _default_state()
        self._notification_events = []
        self._load()

    def _load(self):
        with self.lock:
            try:
                with self.state_path.open("r", encoding="utf-8") as f:
                    raw = json.load(f)
                if isinstance(raw, dict):
                    clean = _default_state()
                    clean.update(raw)
                    clean["version"] = STATE_VERSION
                    clean["processed_issues"] = list(clean.get("processed_issues") or [])[-500:]
                    clean["notification_event_ids"] = list(clean.get("notification_event_ids") or [])[-2000:]
                    self.state = clean
            except FileNotFoundError:
                pass
            except (OSError, ValueError, TypeError) as exc:
                self.state = _default_state()
                self.state["last_error"] = f"state load failed: {exc}"

    def _atomic_save_locked(self):
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_path.with_name(
            f".{self.state_path.name}.tmp.{os.getpid()}.{threading.get_ident()}"
        )
        try:
            with tmp.open("w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2, sort_keys=True)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self.state_path)
            try:
                dir_fd = os.open(str(self.state_path.parent), os.O_RDONLY)
                try:
                    os.fsync(dir_fd)
                finally:
                    os.close(dir_fd)
            except (OSError, AttributeError):
                pass
        finally:
            try:
                if tmp.exists():
                    tmp.unlink()
            except OSError:
                pass

    def snapshot(self):
        with self.lock:
            out = copy.deepcopy(self.state)
            trades = out["total_trades"]
            out["win_rate"] = round(out["wins"] / trades * 100.0, 2) if trades else 0.0
            out["daily_tp"] = DAILY_TP
            out["daily_sl"] = DAILY_SL
            out["base_stake"] = BASE_STAKE
            out["paroli_target"] = PAROLI_WINS
            out["payout"] = PAYOUT
            out["reference_capital"] = INITIAL_DEPOSIT
            return out

    def drain_notification_events(self):
        """Return newly-created Robust events; delivery is owned by integration."""
        with self.lock:
            events = copy.deepcopy(self._notification_events)
            self._notification_events.clear()
            return events

    def _emit_event_locked(self, event_id, kind, **data):
        """Persist event identity before exposing it for non-blocking delivery."""
        if not event_id:
            return False
        ids = list(self.state.get("notification_event_ids") or [])
        if event_id in ids:
            return False
        ids.append(event_id)
        self.state["notification_event_ids"] = ids[-2000:]
        self._notification_events.append({"id": event_id, "kind": kind, **copy.deepcopy(data)})
        return True

    def _emit_daily_stop_locked(self, reason):
        day = str(self.state.get("daily_date") or "unknown")
        kind = "daily_tp" if reason == "Daily TP" else "daily_risk_stop"
        self._emit_event_locked(
            f"daily_stop:{day}",
            kind,
            date=self.state.get("daily_date"),
            reason=reason,
            daily_profit=self.state["daily_profit"],
            bankroll=self.state["bankroll"],
        )

    def _ensure_day_locked(self, day):
        if not day:
            return
        if self.state["daily_date"] != day:
            previous_date = self.state.get("daily_date")
            previous_profit = self.state.get("daily_profit", 0)
            self.state["daily_date"] = day
            self.state["daily_profit"] = 0
            self.state["daily_stopped"] = False
            self.state["paroli_step"] = 0
            self.state["current_stake"] = BASE_STAKE
            if previous_date:
                self._emit_event_locked(
                    f"daily_reset:{day}",
                    "daily_reset",
                    previous_date=previous_date,
                    new_date=day,
                    previous_day_profit=previous_profit,
                    bankroll=self.state["bankroll"],
                    paroli_step=0,
                    base_stake=BASE_STAKE,
                )

    def _settle_pending_locked(self, row):
        p = self.state.get("pending")
        if not p:
            return False

        # A pending live bet may only be resolved by its exact target issue.
        # Empty target_issue is retained for backward-compatible restored state.
        target_issue = str(p.get("target_issue") or "")
        if target_issue and str(row.get("issue") or "") != target_issue:
            return False

        won = row["type"] == p["signal"]
        stake = int(p["stake"])
        pnl = (int(round(stake * PAYOUT)) - stake) if won else -stake
        self.state["bankroll"] += pnl
        self.state["daily_profit"] += pnl
        self.state["total_trades"] += 1

        completed_paroli_step = None
        if won:
            self.state["wins"] += 1
            step = int(p.get("paroli_step", self.state["paroli_step"])) + 1
            completed_paroli_step = step
            self.state["paroli_step"] = 0 if step >= PAROLI_WINS else step
        else:
            self.state["losses"] += 1
            self.state["paroli_step"] = 0

        equity = self.state["bankroll"]
        self.state["peak_equity"] = max(self.state["peak_equity"], equity)
        dd = self.state["peak_equity"] - equity
        self.state["current_drawdown"] = dd
        self.state["max_drawdown"] = max(self.state["max_drawdown"], dd)
        self.state["last_result"] = {
            "issue": row["issue"],
            "signal": p["signal"],
            "actual": row["type"],
            "stake": stake,
            "outcome": "WIN" if won else "LOSS",
            "pnl": pnl,
        }
        self.state["pending"] = None
        self.state["current_stake"] = BASE_STAKE * (2 ** self.state["paroli_step"])
        just_stopped = False
        stop_reason = None
        if self.state["daily_profit"] >= DAILY_TP:
            just_stopped = not self.state["daily_stopped"]
            self.state["daily_stopped"] = True
            stop_reason = "Daily TP"
        elif self.state["daily_profit"] <= -DAILY_SL:
            just_stopped = not self.state["daily_stopped"]
            self.state["daily_stopped"] = True
            stop_reason = "Daily SL / pre-trade hard risk guard"

        next_stake = BASE_STAKE * (2 ** self.state["paroli_step"])
        trading_active = not self.state["daily_stopped"] and self.state["bankroll"] >= next_stake
        self._emit_event_locked(
            f"settlement:{row['issue']}",
            "settlement",
            issue=row["issue"],
            signal=p["signal"],
            actual=row["type"],
            outcome="WIN" if won else "LOSS",
            stake=stake,
            trade_pnl=pnl,
            daily_profit=self.state["daily_profit"],
            bankroll=self.state["bankroll"],
            next_paroli_step=self.state["paroli_step"],
            next_stake=next_stake,
            trading_active=trading_active,
        )
        if won and completed_paroli_step is not None and completed_paroli_step >= PAROLI_WINS:
            self._emit_event_locked(
                f"paroli4:{row['issue']}",
                "paroli4",
                issue=row["issue"],
                daily_profit=self.state["daily_profit"],
                bankroll=self.state["bankroll"],
                base_stake=BASE_STAKE,
            )
        if just_stopped and stop_reason:
            self._emit_daily_stop_locked(stop_reason)
        return True

    def _arm_next_locked(self, history_prefix, next_issue=None):
        result = signal_for_next(history_prefix)
        self.state["signal"] = result["signal"]
        self.state["score"] = result.get("score", 0.0)
        self.state["walk_rsi"] = result.get("walk_rsi")
        self.state["vol"] = result.get("vol")

        target_day = _issue_date(next_issue) or history_prefix[-1].get("date")
        self._ensure_day_locked(target_day)

        if result["signal"] not in ("BIG", "SMALL"):
            self.state["status"] = "NO TRADE"
            self.state["current_stake"] = BASE_STAKE * (2 ** self.state["paroli_step"])
            return

        if self.state["daily_stopped"]:
            self.state["status"] = "DAILY STOP"
            return

        stake = BASE_STAKE * (2 ** self.state["paroli_step"])
        self.state["current_stake"] = stake

        if self.state["daily_profit"] - stake < -DAILY_SL:
            was_stopped = self.state["daily_stopped"]
            self.state["daily_stopped"] = True
            self.state["status"] = "DAILY STOP"
            if not was_stopped:
                self._emit_daily_stop_locked("Daily SL / pre-trade hard risk guard")
            return

        if self.state["bankroll"] < stake:
            self.state["status"] = "INSUFFICIENT BANKROLL"
            return

        self.state["pending"] = {
            "source_issue": history_prefix[-1]["issue"],
            "target_issue": str(next_issue or ""),
            "signal": result["signal"],
            "stake": stake,
            "paroli_step": self.state["paroli_step"],
            "day": target_day,
        }
        self.state["status"] = "ACTIVE"
        target_issue = str(next_issue or "")
        if target_issue:
            self._emit_event_locked(
                f"signal:{target_issue}",
                "signal",
                issue=target_issue,
                target=result["signal"],
                paroli_step=self.state["paroli_step"],
                stake=stake,
                daily_profit=self.state["daily_profit"],
                bankroll=self.state["bankroll"],
            )

    def process_snapshot(self, rows, next_issue=None):
        """Process completed rows once, then arm a causal signal for the next round."""
        history = normalize_history(rows)
        if not history:
            return self.snapshot()

        with self.lock:
            processed = set(self.state.get("processed_issues") or [])
            last = self.state.get("last_processed_issue")

            # First deployment: do not backfill fictional live trades. Start from now.
            if not last:
                latest = history[-1]
                self._ensure_day_locked(latest.get("date"))
                self.state["last_processed_issue"] = latest["issue"]
                self.state["processed_issues"] = [latest["issue"]]
                self._arm_next_locked(history, next_issue)
                self.state["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._atomic_save_locked()
                return self.snapshot()

            idx_by_issue = {row["issue"]: i for i, row in enumerate(history)}
            if last not in idx_by_issue:
                # The shared in-memory window moved past our cursor. The missing
                # rounds are unknowable, so discard any pending bet and re-anchor
                # without changing bankroll/W-L/Paroli/DD or daily accounting.
                latest = history[-1]
                self.state["pending"] = None
                self.state["signal"] = "NO TRADE"
                self.state["status"] = "NO TRADE"
                self.state["last_processed_issue"] = latest["issue"]
                self.state["processed_issues"] = (self.state.get("processed_issues") or [])[-499:] + [latest["issue"]]
                self.state["last_error"] = "history cursor gap; re-anchored without settlement"
                self.state["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._atomic_save_locked()
                return self.snapshot()

            start = idx_by_issue[last] + 1
            changed = False
            for i in range(start, len(history)):
                row = history[i]
                if row["issue"] in processed:
                    continue

                pending = self.state.get("pending")
                target_issue = str((pending or {}).get("target_issue") or "")
                row_issue = str(row["issue"])

                if pending and target_issue and row_issue != target_issue:
                    # If the target is still ahead in this snapshot (or the numeric
                    # issue is still before it), keep waiting without touching trade
                    # accounting. A row beyond a missing target is an unknown gap:
                    # discard the pending bet and re-anchor without a fake outcome.
                    target_later = any(
                        str(history[j]["issue"]) == target_issue
                        for j in range(i + 1, len(history))
                    )
                    row_before_target = False
                    try:
                        row_before_target = int(row_issue) < int(target_issue)
                    except (TypeError, ValueError):
                        pass

                    if target_later or row_before_target:
                        self.state["last_processed_issue"] = row_issue
                        processed.add(row_issue)
                        changed = True
                        continue

                    # Missing/skipped target: no bankroll/W-L/Paroli/DD mutation.
                    latest = history[-1]
                    self.state["pending"] = None
                    self.state["signal"] = "NO TRADE"
                    self.state["status"] = "NO TRADE"
                    self.state["last_processed_issue"] = latest["issue"]
                    for skipped in history[start:]:
                        processed.add(skipped["issue"])
                    self.state["processed_issues"] = list(processed)[-500:]
                    self.state["last_error"] = (
                        f"pending target {target_issue} missing before {row_issue}; "
                        "re-anchored without settlement"
                    )
                    self.state["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    self._atomic_save_locked()
                    return self.snapshot()

                # Exact target (or backward-compatible targetless pending) settles.
                # Target-day reset is intentionally after target verification so a
                # wrong/unknown row cannot alter Paroli or daily risk state.
                self._ensure_day_locked(row.get("date"))
                self._settle_pending_locked(row)

                self.state["last_processed_issue"] = row_issue
                processed.add(row_issue)
                changed = True

                # For an observed backlog, the immediate next known row is the target.
                predicted_next = history[i + 1]["issue"] if i + 1 < len(history) else next_issue
                self._arm_next_locked(history[:i + 1], predicted_next)

            if not changed:
                # Refresh the current next-round signal if there is no pending trade.
                # This is read-only with respect to completed issue accounting.
                if not self.state.get("pending"):
                    self._arm_next_locked(history, next_issue)

            self.state["processed_issues"] = list(processed)[-500:]
            self.state["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._atomic_save_locked()
            return self.snapshot()
