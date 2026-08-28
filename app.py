# -*- coding: utf-8 -*-
"""TRX Confluence Signal Engine — Web Dashboard (Flask + Background Engine)"""
import csv
import gzip
import json
import os
import queue
import statistics
import threading
import time
from collections import Counter, deque
from datetime import datetime, timedelta

import requests
from flask import Flask, jsonify, render_template, request

if sys_stdout := __import__("sys").stdout:
    if hasattr(sys_stdout, "reconfigure"):
        sys_stdout.reconfigure(encoding="utf-8", errors="replace")

# ================= DATA SOURCE =================
URL_DATA = "https://trxchart.com/api/trx-data"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
POLL_SEC = 2        # tail-mode (?limit=500 ≈ 80KB) — fast candle updates

# ================= INDICATOR SETTINGS =================
FAST_EMA = 5
SLOW_EMA = 15
RSI_PERIOD = 14
MOM_WINDOW = 10
VOL_WINDOW = 20
VOL_MIN = 2.2
LONG_WINDOW = 100
SR_WINDOW = 50
SR_WEIGHT = 1.2

# ================= CONFLUENCE THRESHOLDS =================
SCORE_TRADE = 40
SCORE_WATCH = 22

# ================= RISK MANAGEMENT =================
START_BANKROLL = 50000
RISK_PCT = 0.02
STOP_LOSS_UNITS = 6
TAKE_PROFIT_UNITS = 8
MAX_LOSE_STREAK = 4
COOLDOWN_ROUNDS = 3
FEED_DELAY_STANDBY_SEC = 300      # feed ဒီထက် နောက်ကျရင် auto no-trade
STAKE_TIER_HIGH_SCORE = 60        # |score| ≥ 60 → stake ×1.25
ROLLING_MIN_FOR_CONF = 10         # rolling win-rate ယုံကြည်မှု တွက်ဖို့ အနိမ့်ဆုံး အရေအတွက်

BET_SIZE = round(START_BANKROLL * RISK_PCT)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
LOG_FILE = os.path.join(BASE_DIR, "signals_log.csv")
HIST_FILE = os.path.join(BASE_DIR, "signals_history.csv")
HISTORY_KEEP = 400
LOG_KEEP = 200
SIGNALS_KEEP = 300

# ================= FULL CHART HISTORY (10 DAYS) =================
FULL_HISTORY_DAYS = 10          # chart အတွက် သိမ်းဆည်းမယ့် ရက်အရေအတွက်
MAX_FULL_ROWS = 30000           # memory safety cap

session = requests.Session()
session.headers.update(HEADERS)
LOCK = threading.Lock()

# ================= TELEGRAM NOTIFICATIONS =================
# telegram.json → {"token": "<BotFather token>", "chat_id": "<your chat id>"}
TG_CONFIG_FILE = os.path.join(BASE_DIR, "telegram.json")
TG_RSI_UP = 60.0        # chart RSI pane — 60 ကျော်ရင် Noti
TG_RSI_DOWN = 40.0      # 40 အောက်ဆင်းရင် Noti
TG_MIN_GAP_SEC = 60     # anti-spam: Noti ကြားခံ gap
TG_REMIND_SEC = 300     # zone ထဲ ဆက်ရှိနေရင် 5 မိနစ်တစ်ခါ reminder

_tg_queue = queue.Queue()


def load_tg_config():
    """telegram.json ဦးစားပေး — မရှိရင် TG_TOKEN / TG_CHAT env vars (cloud hosting)
       rsi_up / rsi_down / remind_sec keys နဲ့ ချိန်လို့ရ။"""
    token = chat = ""
    up, down, remind = TG_RSI_UP, TG_RSI_DOWN, TG_REMIND_SEC
    try:
        with open(TG_CONFIG_FILE, encoding="utf-8") as f:
            c = json.load(f)
        token = str(c.get("token") or "").strip()
        chat = str(c.get("chat_id") or "").strip()
        try:
            up = float(c.get("rsi_up", TG_RSI_UP))
            down = float(c.get("rsi_down", TG_RSI_DOWN))
            remind = float(c.get("remind_sec", TG_REMIND_SEC))
        except (TypeError, ValueError):
            pass
    except (OSError, ValueError):
        pass
    if not (token and chat and "PUT_YOUR" not in token and "PUT_YOUR" not in chat):
        token = os.environ.get("TG_TOKEN", "").strip()
        chat = os.environ.get("TG_CHAT", "").strip()
    if token and chat:
        return (token, chat, up, down, remind)
    return None


def _tg_worker():
    while True:
        text = _tg_queue.get()
        if text is None:
            break
        cfg = load_tg_config()   # re-read every send → live-editable
        if not cfg:
            result = "skip — config မဖြည့်ရသေးပါ"
        else:
            token, chat = cfg[0], cfg[1]
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat, "text": text}, timeout=10)
                result = "sent" if r.status_code == 200 else f"HTTP {r.status_code}: {r.text[:80]}"
            except requests.RequestException as e:
                result = f"error: {e}"
        print(f"[TG] {result}: {text.splitlines()[0]}", flush=True)
        with LOCK:
            STATE["tg_last"] = {
                "time": datetime.now().strftime("%H:%M:%S"),
                "msg": text.splitlines()[0],
                "result": result,
            }


def tg_notify(text):
    _tg_queue.put(text)

STATE = {
    "connected": False,
    "error": None,
    "last_update": None,
    "history": [],
    "full_history": [],
    "hist_meta": {},
    "analysis": None,
    "next_issue": None,
    "pending": None,
    "risk_block": None,
    "stats": {"w": 0, "l": 0},
    "units": 0,
    "lose_streak": 0,
    "cooldown": 0,
    "rolling": {"n": 0, "w": 0},
    "log": [],
    "equity": [],
    "markov": None,
    "feed_delay": None,
    "backtest": None,
    "tg_last": None,
    "bet_size": BET_SIZE,
    "session_start": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "config": {
        "fast_ema": FAST_EMA,
        "slow_ema": SLOW_EMA,
        "rsi_period": RSI_PERIOD,
        "mom_window": MOM_WINDOW,
        "vol_window": VOL_WINDOW,
        "vol_min": VOL_MIN,
        "long_window": LONG_WINDOW,
        "sr_window": SR_WINDOW,
        "score_trade": SCORE_TRADE,
        "score_watch": SCORE_WATCH,
        "stop_loss": STOP_LOSS_UNITS,
        "take_profit": TAKE_PROFIT_UNITS,
        "max_lose_streak": MAX_LOSE_STREAK,
        "cooldown_rounds": COOLDOWN_ROUNDS,
        "risk_pct": RISK_PCT,
        "bankroll": START_BANKROLL,
    },
}

last_issue = None
pending = None
stats = {"w": 0, "l": 0}
recent_results = deque(maxlen=20)
units = 0
lose_streak = 0
cooldown = 0
signal_history = []   # preloaded from CSV below (after function definitions)
unresolved_signal = None
_bt_day = None
tg_zone = None        # None | "up" | "down" — RSI zone tracking (restart-safe)
_tg_last_ts = 0.0

app = Flask(__name__)
app.config["SEND_FILE_MAX_AGE_DEFAULT"] = 0  # no static caching — always fresh JS/CSS


def log_signal(row):
    try:
        # rotation: keep the file bounded (header + last LOG_KEEP rows)
        if os.path.exists(LOG_FILE) and os.path.getsize(LOG_FILE) > 0:
            with open(LOG_FILE, "rb") as f:
                if sum(1 for _ in f) >= LOG_KEEP * 2:
                    with open(LOG_FILE, newline="", encoding="utf-8") as rf:
                        lines = rf.readlines()
                    with open(LOG_FILE, "w", newline="", encoding="utf-8") as wf:
                        wf.writelines(lines[:1] + lines[-LOG_KEEP:])
        new_file = not os.path.exists(LOG_FILE)
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["timestamp", "issue", "signal", "score", "result", "win"])
            w.writerow(row)
    except OSError as e:
        print(f"Log write error: {e}", flush=True)


def append_signal_history(entry):
    new_file = not os.path.exists(HIST_FILE)
    try:
        rotate = False
        if not new_file and os.path.getsize(HIST_FILE) > 0:
            with open(HIST_FILE, "rb") as f:
                rotate = sum(1 for _ in f) >= SIGNALS_KEEP * 2
        if rotate:
            rows = load_signal_history()
            with open(HIST_FILE, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                w.writerow(["time", "issue", "signal", "score",
                            "result_number", "result_type", "outcome"])
                for r in rows:
                    w.writerow([r["time"], r["issue"], r["signal"], r["score"],
                                r.get("result_number") or "", r.get("result_type") or "",
                                r.get("outcome") or ""])
        with open(HIST_FILE, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            if new_file:
                w.writerow(["time", "issue", "signal", "score",
                            "result_number", "result_type", "outcome"])
            w.writerow([entry["time"], entry["issue"], entry["signal"], entry["score"],
                        entry.get("result_number", ""), entry.get("result_type", ""),
                        entry.get("outcome", "")])
    except OSError as e:
        print(f"History write error: {e}", flush=True)


def load_signal_history():
    if not os.path.exists(HIST_FILE):
        return []
    rows = []
    try:
        with open(HIST_FILE, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                try:
                    rows.append({
                        "time": r.get("time", ""),
                        "issue": r.get("issue", ""),
                        "short_issue": (r.get("issue") or "")[-6:],
                        "signal": r.get("signal", "SKIP"),
                        "score": float(r["score"]) if r.get("score") not in (None, "") else 0.0,
                        "result_number": r.get("result_number") or None,
                        "result_type": r.get("result_type") or None,
                        "outcome": r.get("outcome") or "PENDING",
                    })
                except (ValueError, TypeError):
                    continue
    except OSError as e:
        print(f"History read error: {e}", flush=True)
    return rows[-SIGNALS_KEEP:]


def load_trade_log():
    if not os.path.exists(LOG_FILE):
        return []
    entries = []
    try:
        with open(LOG_FILE, newline="", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                ts = r.get("timestamp", "")
                try:
                    t = datetime.strptime(ts, "%Y-%m-%d %H:%M:%S").strftime("%H:%M:%S")
                except ValueError:
                    t = ts[-8:] if len(ts) >= 8 else ts
                entries.append({
                    "time": t,
                    "issue": (r.get("issue") or "")[-6:],
                    "full_issue": r.get("issue") or "",
                    "signal": r.get("signal", ""),
                    "score": r.get("score", ""),
                    "result_number": None,
                    "result": r.get("result", ""),
                    "outcome": r.get("win", ""),
                })
    except OSError as e:
        print(f"Trade log read error: {e}", flush=True)
    return entries[-LOG_KEEP:]


def parse_history(data_list):
    parsed = []
    seen = set()
    for item in data_list:
        if not isinstance(item, dict):
            continue
        raw_issue = str(item.get("issueNumber") or item.get("issue") or "")
        num_val = item.get("number") if item.get("number") is not None else item.get("result")
        block_time = str(item.get("blockTime") or item.get("time") or "")
        if raw_issue and num_val is not None and raw_issue not in seen:
            try:
                num = int(num_val)
                seen.add(raw_issue)
                day_digits = raw_issue[:8]
                parsed.append({
                    "issue": raw_issue,
                    "short_issue": raw_issue[-6:] if len(raw_issue) >= 6 else raw_issue,
                    "issue_int": int(raw_issue) if raw_issue.isdigit() else 0,
                    "day_int": int(day_digits) if day_digits.isdigit() else 0,
                    "number": num,
                    "type": "BIG" if num >= 5 else "SMALL",
                    "block_time": block_time,
                    "hm": block_time[11:16] if len(block_time) >= 16 else "",
                })
            except ValueError:
                continue
    parsed.sort(key=lambda x: x["issue_int"])
    return parsed


def trim_full_history(rows, days=FULL_HISTORY_DAYS):
    """Keep only the last `days` days (issue prefix yyyymmdd = round date)."""
    if not rows:
        return []
    last_day = rows[-1].get("day_int") or 0
    if last_day <= 0:
        return rows[-MAX_FULL_ROWS:]
    try:
        y, mo, d = last_day // 10000, (last_day // 100) % 100, last_day % 100
        cutoff_day = int((datetime(y, mo, d) - timedelta(days=days - 1)).strftime("%Y%m%d"))
        out = [r for r in rows if (r.get("day_int") or 0) >= cutoff_day]
    except ValueError:
        out = rows[-MAX_FULL_ROWS:]
    return out[-MAX_FULL_ROWS:]


# ================= ANALYTICS HELPERS (shared, causal — no look-ahead) =================
def ema_series(vals, period):
    """EMA over full series; value at index i depends only on vals[<=i]."""
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


def mtf_confluence(m):
    """Multi-timeframe trend sign on ×5 / ×15 grouped walks."""
    def sign(step):
        if len(m) < step * SLOW_EMA:
            return 0
        g = [sum(m[k:k + step]) for k in range(0, len(m) - step + 1, step)]
        f = ema(g, FAST_EMA)
        s = ema(g, SLOW_EMA)
        if f is None or s is None:
            return 0
        return 1 if f > s else -1
    return {"x5": sign(5), "x15": sign(15)}


def markov_prob(parsed):
    """Empirical P(next=BIG | last-2 outcome pattern) from history."""
    if len(parsed) < 30:
        return {"pattern": None, "p_big": None, "n": 0}
    t = [x["type"] for x in parsed]
    counts = {}
    for i in range(2, len(t)):
        key = (t[i - 2], t[i - 1])
        c = counts.setdefault(key, [0, 0])
        c[0 if t[i] == "BIG" else 1] += 1
    key = (t[-2], t[-1])
    big, sm = counts.get(key, (0, 0))
    n = big + sm
    return {
        "pattern": f"{key[0][0]}{key[1][0]}",
        "p_big": round(big / n, 3) if n else None,
        "n": n,
    }


def run_backtest(parsed):
    """Replay the exact live scoring formula across history (causally).
       Returns per-layer hit-rates + score-bucket accuracy → weight calibration."""
    start_need = max(LONG_WINDOW, VOL_WINDOW, SR_WINDOW, RSI_PERIOD + 1,
                     MOM_WINDOW, SLOW_EMA) + 2
    if len(parsed) < start_need + 50:
        return None
    m = [1 if x["type"] == "BIG" else -1 for x in parsed]
    nums = [x["number"] for x in parsed]
    typ = [x["type"] for x in parsed]
    ef = ema_series(m, FAST_EMA)
    es = ema_series(m, SLOW_EMA)
    rs = rsi_series(nums)
    pref = [0] * (len(typ) + 1)
    for i, v in enumerate(typ):
        pref[i + 1] = pref[i] + (1 if v == "BIG" else 0)

    comps = {k: [0, 0] for k in ("EMA", "MOM", "RSI", "FADE", "GAP", "S/R")}
    buckets = {"trade": [0, 0], "watch": [0, 0]}
    tested = 0

    for i in range(start_need, len(m)):
        vol = statistics.pstdev(nums[i - VOL_WINDOW:i])
        if vol < VOL_MIN:                       # live engine stands aside too
            continue
        td = ef[i - 1] - es[i - 1]
        t_score = max(-30.0, min(30.0, td * 250))
        mom = sum(m[i - MOM_WINDOW:i]) / MOM_WINDOW
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
        big = pref[i] - pref[i - LONG_WINDOW]
        small = LONG_WINDOW - big
        g_score = max(-24.0, min(24.0, -(big - small) * 0.6))
        freq = Counter(nums[i - SR_WINDOW:i])
        sup_t = sum(freq[d] for d in range(0, 4))
        res_t = sum(freq[d] for d in range(7, 10))
        sr_score = max(-18.0, min(18.0, (sup_t - res_t) * SR_WEIGHT))
        score = t_score + m_score + r_score + st_score + g_score + sr_score

        actual = 1 if typ[i] == "BIG" else -1
        tested += 1
        for name, sc in (("EMA", t_score), ("MOM", m_score), ("RSI", r_score),
                         ("FADE", st_score), ("GAP", g_score), ("S/R", sr_score)):
            if sc != 0:
                comps[name][0] += 1
                if (1 if sc > 0 else -1) == actual:
                    comps[name][1] += 1
        a = abs(score)
        if a >= SCORE_TRADE:
            pred = 1 if score > 0 else -1
            buckets["trade"][0] += 1
            if pred == actual:
                buckets["trade"][1] += 1
        elif a >= SCORE_WATCH:
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
            "trade": {"calls": buckets["trade"][0], "wins": buckets["trade"][1],
                      "wr": wr(buckets["trade"])},
            "watch": {"calls": buckets["watch"][0], "wins": buckets["watch"][1],
                      "wr": wr(buckets["watch"])},
        },
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }


def ema(series, period):
    if len(series) < period:
        return None
    k = 2.0 / (period + 1)
    e = sum(series[:period]) / period
    for v in series[period:]:
        e = v * k + e * (1 - k)
    return e


def rsi(nums, period=RSI_PERIOD):
    if len(nums) < period + 1:
        return 50.0
    gains = losses = 0.0
    for i in range(-period, 0):
        d = nums[i] - nums[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    if losses == 0:
        return 100.0
    rs = (gains / period) / (losses / period)
    return 100.0 - 100.0 / (1.0 + rs)


def streak_len(series):
    if not series:
        return 0
    s = 0
    for v in reversed(series):
        if v == series[-1]:
            s += 1
        else:
            break
    return s


def analyze_all_in_one(history):
    base = {"big": 0, "small": 0, "gap": 0, "score": 0.0, "parts": [],
            "rsi": None, "vol": None, "streak": 0, "ready": False}
    if len(history) < LONG_WINDOW:
        return {**base, "signal": "WAIT",
                "reason": f"Data စုဆောင်းနေဆဲ ({len(history)}/{LONG_WINDOW})"}

    m = [1 if x["type"] == "BIG" else -1 for x in history]
    nums = [x["number"] for x in history]

    window = history[-LONG_WINDOW:]
    counts = Counter(x["type"] for x in window)
    long_big, long_small = counts["BIG"], counts["SMALL"]
    gap = abs(long_big - long_small)

    parts_struct = []

    def add_part(name, value, note=""):
        parts_struct.append({"name": name, "value": round(value, 1), "note": note})

    def fmt(v):
        return f"{v:+.0f}"

    vol = statistics.pstdev(nums[-VOL_WINDOW:])
    r_now = rsi(nums)
    st_now = streak_len(m)
    out = {**base, "big": long_big, "small": long_small, "gap": gap,
           "rsi": round(r_now, 1), "vol": round(vol, 2), "streak": st_now}

    if vol < VOL_MIN:
        add_part("VOL", 0, f"STDEV {vol:.2f} < {VOL_MIN}")
        return {**out, "signal": "SKIP (LOW VOLATILITY)",
                "reason": f"📉 Volatility နိမ့် (STDEV {vol:.2f}) — Sideway/Chop ဖြစ်နေ၍ Trade မလုပ်ပါ",
                "parts": parts_struct, "ready": True}

    score = 0.0
    parts = []

    ema_f = ema(m, FAST_EMA)
    ema_s = ema(m, SLOW_EMA)
    trend_diff = ema_f - ema_s
    t_score = max(-30.0, min(30.0, trend_diff * 250))
    score += t_score
    side = "UP(BIG)" if trend_diff > 0 else "DOWN(SMALL)"
    parts.append(f"EMA {fmt(t_score)}({side})")
    add_part("EMA", t_score, side)

    mom = sum(m[-MOM_WINDOW:]) / MOM_WINDOW
    m_score = max(-20.0, min(20.0, mom * 40))
    score += m_score
    parts.append(f"MOM {fmt(m_score)}")
    add_part("MOM", m_score, f"x{MOM_WINDOW}")

    r = rsi(nums)
    r_score = 0.0
    if r >= 70:
        r_score = -15.0
        parts.append(f"RSI {r:.0f}(OB)")
    elif r <= 30:
        r_score = +15.0
        parts.append(f"RSI {r:.0f}(OS)")
    else:
        parts.append(f"RSI {r:.0f}")
    score += r_score
    tag = "OB" if r >= 70 else ("OS" if r <= 30 else "")
    add_part("RSI", r_score, f"{r:.0f}{(' ' + tag) if tag else ''}")

    st = streak_len(m)
    if st >= 4:
        st_score = min((st - 3) * 8, 24)
        st_score = -st_score if m[-1] == 1 else st_score
        score += st_score
        parts.append(f"FADE x{st} {fmt(st_score)}")
        add_part("FADE", st_score, f"x{st}")

    g_score = max(-24.0, min(24.0, -(long_big - long_small) * 0.6))
    score += g_score
    parts.append(f"GAP {fmt(g_score)}")
    add_part("GAP", g_score, f"B{long_big}/S{long_small}")

    # ---- LAYER F: SUPPORT / RESISTANCE (weight ±18) ----
    # 0-3 = Support zone, 7-9 = Resistance zone
    # Touch များလေ Level အားကောင်းလေ -> Bounce မြင့်လေ
    freq = Counter(nums[-SR_WINDOW:])
    support_touches = sum(freq[d] for d in range(0, 4))
    resistance_touches = sum(freq[d] for d in range(7, 10))
    sr_score = max(-18.0, min(18.0, (support_touches - resistance_touches) * SR_WEIGHT))
    score += sr_score
    parts.append(f"S/R {fmt(sr_score)}(S{support_touches}/R{resistance_touches})")
    add_part("S/R", sr_score, f"S{support_touches}/R{resistance_touches}")

    out["score"] = round(score, 1)
    out["parts"] = parts_struct
    out["ready"] = True
    out["mtf"] = mtf_confluence(m)
    reason_detail = " | ".join(parts)
    want = 1 if score > 0 else -1
    mtf_ok = (out["mtf"]["x5"] in (0, want)) and (out["mtf"]["x15"] in (0, want))

    if abs(score) >= SCORE_TRADE:
        signal = "BIG" if score > 0 else "SMALL"
        if trend_diff * m[-1] < -0.004:
            return {**out, "signal": "SKIP (REVERSAL GUARD)",
                    "reason": f"⚠️ Trend({side}) ထဲမှာ ဆန့်ကျင်ဘက် ကွဲထွက်နေ၍ ရပ်တန့် | {reason_detail}"}
        if not mtf_ok and abs(score) < SCORE_TRADE + 15:
            return {**out, "signal": "SKIP (WATCH)",
                    "reason": (f"👀 MTF မကိုက် (×5 {'▲' if out['mtf']['x5'] > 0 else '▼'} · "
                               f"×15 {'▲' if out['mtf']['x15'] > 0 else '▼'}) — Watch | {reason_detail}")}
        return {**out, "signal": signal,
                "reason": f"🎯 CONFLUENCE {score:+.0f} | {reason_detail}"}

    if abs(score) >= SCORE_WATCH:
        return {**out, "signal": "SKIP (WATCH)",
                "reason": f"👀 Watch Zone ({score:+.0f}) — Confluence မလုံလောက် | {reason_detail}"}

    return {**out, "signal": "SKIP",
            "reason": f"⏸️ Signal မရှိ ({score:+.0f}) | {reason_detail}"}


def risk_check():
    if cooldown > 0:
        return f"❄️ Cooldown ({cooldown} ပွဲကျန်)"
    if lose_streak >= MAX_LOSE_STREAK:
        return f"⛔ Lose-Streak {lose_streak} — ရပ်ပါ"
    if units <= -STOP_LOSS_UNITS:
        return f"🛑 STOP-LOSS ထိ ({units:+d} unit) — ဒီနေ့ ရပ်ပါ"
    if units >= TAKE_PROFIT_UNITS:
        return f"🏁 TAKE-PROFIT ပြီး ({units:+d} unit) — အမြတ်ယူပြီးရပ်"
    return None


def resolve_pending(latest):
    global pending, units, lose_streak, cooldown
    if pending and pending["issue"] == latest["issue"]:
        win = latest["type"] == pending["signal"]
        if win:
            stats["w"] += 1
            units += 1
            lose_streak = 0
            recent_results.append(1)
        else:
            stats["l"] += 1
            units -= 1
            lose_streak += 1
            cooldown = COOLDOWN_ROUNDS
            recent_results.append(0)
        entry = {
            "time": datetime.now().strftime("%H:%M:%S"),
            "issue": latest["short_issue"],
            "full_issue": latest["issue"],
            "signal": pending["signal"],
            "score": pending.get("score", ""),
            "result_number": latest["number"],
            "result": latest["type"],
            "outcome": "WIN" if win else "LOSS",
        }
        log_signal([datetime.now().strftime("%Y-%m-%d %H:%M:%S"), latest["issue"],
                    pending["signal"], pending.get("score", ""), latest["type"],
                    "WIN" if win else "LOSS"])
        with LOCK:
            STATE["log"].append(entry)
            if len(STATE["log"]) > LOG_KEEP:
                STATE["log"][:] = STATE["log"][-LOG_KEEP:]
            STATE["equity"].append({"t": entry["time"], "u": units})
            if len(STATE["equity"]) > 600:
                del STATE["equity"][:len(STATE["equity"]) - 600]
        print(f"\n💰 [{latest['short_issue']}] {'✅ WIN' if win else '❌ LOSS'} "
              f"({entry['signal']} vs actual {latest['type']})", flush=True)
        pending = None
    elif cooldown > 0:
        cooldown -= 1


def engine_loop():
    global last_issue, pending, units, lose_streak, cooldown, unresolved_signal
    global tg_zone, _tg_last_ts
    # ---- tail-mode polling state (local to engine thread) ----
    all_rows = []          # persistent parsed rows (newest at end)
    seen_issues = set()
    have_full = False      # boot-time full snapshot done?
    err_streak = 0
    while True:
        try:
            url = URL_DATA if not have_full else URL_DATA + "?limit=500"
            res = session.get(
                url, timeout=15,
                headers={"Cache-Control": "no-cache", "Pragma": "no-cache"})
            if res.status_code == 200:
                data = res.json()
                data_list = data if isinstance(data, list) else data.get("data", [])
                parsed = parse_history(data_list)

                if parsed:
                    if have_full:
                        # merge only genuinely-new tail rounds (ascending order)
                        fresh = [r for r in parsed if r["issue"] not in seen_issues]
                        for r in fresh:
                            seen_issues.add(r["issue"])
                            if not all_rows or r["issue_int"] > all_rows[-1]["issue_int"]:
                                all_rows.append(r)
                        if len(seen_issues) > 300000:
                            seen_issues = set(r["issue"] for r in all_rows)
                    else:
                        all_rows = parsed
                        seen_issues = set(r["issue"] for r in parsed)
                        have_full = True
                        print(f"[ENGINE] full snapshot: {len(all_rows)} rounds "
                              f"(tail mode: {POLL_SEC}s · ?limit=500)", flush=True)
                    if len(all_rows) > MAX_FULL_ROWS:
                        all_rows = all_rows[-MAX_FULL_ROWS:]
                    err_streak = 0
                    parsed_history = all_rows

                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    latest = parsed_history[-1]
                    if latest["issue"] != last_issue:
                        resolve_pending(latest)

                        # ---- resolve previous signal entry with actual result ----
                        if unresolved_signal and unresolved_signal["issue"] == latest["issue"]:
                            traded = unresolved_signal["signal"] in ("BIG", "SMALL")
                            win = latest["type"] == unresolved_signal["signal"] if traded else None
                            unresolved_signal["result_number"] = latest["number"]
                            unresolved_signal["result_type"] = latest["type"]
                            unresolved_signal["outcome"] = (
                                "WIN" if win else "LOSS") if traded else "NO TRADE"
                            append_signal_history(unresolved_signal)
                            unresolved_signal = None

                        last_issue = latest["issue"]
                        next_issue = str(latest["issue_int"] + 1) if latest["issue_int"] > 0 else "NEXT"

                        analysis = analyze_all_in_one(parsed_history)

                        # ---- Telegram: RSI zone alerts (enter + reminder) ----
                        # zone-based → restart-safe: zone ထဲ ပြန်ရောက်ရင် ချက်ချင်း အသိပေးပြီး
                        # zone ထဲ ဆက်နေရင် remind_sec တစ်ခါ reminder ပို့
                        r_now = analysis.get("rsi")
                        if r_now is not None:
                            cfg = load_tg_config()
                            up_lv = cfg[2] if cfg else TG_RSI_UP
                            dn_lv = cfg[3] if cfg else TG_RSI_DOWN
                            try:
                                remind_sec = float(cfg[4]) if len(cfg) > 4 and cfg[4] else TG_REMIND_SEC
                            except (TypeError, ValueError):
                                remind_sec = TG_REMIND_SEC
                            ts = time.time()
                            zone = ("up" if r_now >= up_lv
                                    else "down" if r_now <= dn_lv else None)
                            if zone and zone != tg_zone:
                                # zone ထဲ ရောက်ခါစ (cross + restart-baseline နှစ်မျိုးလုံး)
                                arrow = "⬆️" if zone == "up" else "⬇️"
                                tg_notify(
                                    f"{arrow} RSI {up_lv if zone == 'up' else dn_lv:.0f} "
                                    f"{'ကျော်သွားပါသည်' if zone == 'up' else 'အောက် ဆင်းသွားပါသည်'}\n"
                                    f"RSI လက်ရှိ: {r_now:.1f}\n"
                                    f"Issue …{latest['short_issue']} · {latest['block_time']}")
                                _tg_last_ts = ts
                            elif zone and zone == tg_zone and ts - _tg_last_ts >= remind_sec:
                                # zone ထဲ ဆက်ရှိနေဆဲ — reminder
                                tg_notify(
                                    f"🔁 RSI {up_lv if zone == 'up' else dn_lv:.0f} "
                                    f"{'အပေါ်' if zone == 'up' else 'အောက်'} ရှိနေဆဲ ({r_now:.1f})\n"
                                    f"Issue …{latest['short_issue']}")
                                _tg_last_ts = ts
                            tg_zone = zone

                        # ---- record this round's signal for next issue ----
                        new_entry = {
                            "time": datetime.now().strftime("%H:%M:%S"),
                            "issue": next_issue,
                            "short_issue": next_issue[-6:] if len(next_issue) >= 6 else next_issue,
                            "signal": analysis["signal"],
                            "score": analysis.get("score", 0.0),
                            "result_number": None,
                            "result_type": None,
                            "outcome": "PENDING",
                        }
                        signal_history.append(new_entry)
                        if len(signal_history) > SIGNALS_KEEP:
                            del signal_history[:len(signal_history) - SIGNALS_KEEP]
                        unresolved_signal = new_entry

                        block = risk_check()
                        # feed-delay auto-standby: stale state → no new bets
                        try:
                            bt_dt = datetime.strptime(latest["block_time"], "%Y-%m-%d %H:%M:%S")
                            feed_delay = max(0, int((datetime.now() - bt_dt).total_seconds()))
                        except (ValueError, TypeError):
                            feed_delay = None
                        if block is None and feed_delay is not None and feed_delay > FEED_DELAY_STANDBY_SEC:
                            block = f"⏳ Feed Delayed {feed_delay // 60}m {feed_delay % 60}s — Auto-Standby"
                        entry = None
                        if not block and analysis["signal"] in ("BIG", "SMALL"):
                            # score-tiered + rolling-confidence staking
                            tier = 1.25 if abs(analysis.get("score", 0)) >= STAKE_TIER_HIGH_SCORE else 1.0
                            conf = 1.0
                            if len(recent_results) >= ROLLING_MIN_FOR_CONF:
                                p = sum(recent_results) / len(recent_results)
                                conf = (0.75 if p < 0.45
                                        else 1.25 if (p > 0.55 and len(recent_results) >= 20) else 1.0)
                            stake = int(round(BET_SIZE * tier * conf))
                            entry = {"issue": next_issue,
                                     "short_issue": next_issue[-6:] if len(next_issue) >= 6 else next_issue,
                                     "signal": analysis["signal"],
                                     "score": analysis.get("score", 0),
                                     "stake": stake}
                            pending = entry

                        with LOCK:
                            full_hist = trim_full_history(parsed_history)
                            hist_meta = {
                                "days": FULL_HISTORY_DAYS,
                                "count": len(full_hist),
                                "from": full_hist[0]["issue"] if full_hist else None,
                                "to": full_hist[-1]["issue"] if full_hist else None,
                            }
                            STATE.update({
                                "connected": True,
                                "error": None,
                                "last_update": now,
                                "history": parsed_history[-HISTORY_KEEP:],
                                "full_history": full_hist,
                                "hist_meta": hist_meta,
                                "analysis": analysis,
                                "next_issue": next_issue,
                                "pending": dict(pending) if pending else None,
                                "risk_block": block,
                                "units": units,
                                "lose_streak": lose_streak,
                                "cooldown": cooldown,
                                "stats": dict(stats),
                                "rolling": {"n": len(recent_results), "w": sum(recent_results)},
                                "feed_delay": feed_delay,
                                "markov": markov_prob(parsed_history),
                            })
                        # ---- backtest: once on first data, then daily re-calibration ----
                        if STATE.get("backtest") is None or _bt_day != latest["day_int"]:
                            _bt_day = latest["day_int"]
                            bt_result = run_backtest(parsed_history)
                            with LOCK:
                                STATE["backtest"] = bt_result
                            if bt_result:
                                print(f"[BT] calibrated on {bt_result['rounds_tested']} rounds · "
                                      f"trade-wr {bt_result['buckets']['trade']['wr']}", flush=True)
                        print(f"[{now}] Issue {latest['short_issue']} -> {latest['number']} "
                              f"({analysis['signal']} {analysis['score']:+.0f})", flush=True)
            else:
                err_streak += 1
                if have_full and err_streak >= 5:
                    have_full = False   # tail fetch ထပ်ခါထပ်ခါ fail → full snapshot ပြန်ယူ
                with LOCK:
                    STATE["connected"] = False
                    STATE["error"] = f"HTTP {res.status_code}"
        except Exception as e:
            err_streak += 1
            if have_full and err_streak >= 5:
                have_full = False
            with LOCK:
                STATE["connected"] = False
                STATE["error"] = f"{type(e).__name__}: {e}"
            print(f"Connection Exception (Auto-Retrying): {e}", flush=True)
        time.sleep(POLL_SEC)


@app.route("/")
def index():
    return render_template("index.html")


# ---- preload persisted data (CSV) before routes/engine start ----
signal_history = load_signal_history()


@app.after_request
def compress_response(response):
    """Gzip-compress large JSON payloads (10-day history ≈ 700KB → ~120KB)."""
    if (response.mimetype == "application/json"
            and response.status_code == 200
            and "gzip" in request.headers.get("Accept-Encoding", "")):
        data = response.get_data()
        if len(data) > 1024:
            response.set_data(gzip.compress(data, compresslevel=5))
            response.headers["Content-Encoding"] = "gzip"
            response.headers["Content-Length"] = str(len(response.get_data()))
            response.headers.add("Vary", "Accept-Encoding")
    return response


@app.route("/api/state")
def api_state():
    with LOCK:
        snap = {k: v for k, v in STATE.items() if k != "full_history"}
        snap["history"] = list(STATE["history"])
        snap["log"] = list(reversed(STATE["log"]))[:50]
        snap["server_now"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return jsonify(snap)


@app.route("/api/history")
def api_history():
    """Full chart history (default: last 10 days) — compact [issue, number, time] rows.
       `?since=<issue>` returns only newer rounds (incremental sync)."""
    days = request.args.get("days", default=FULL_HISTORY_DAYS, type=int)
    days = max(1, min(days, FULL_HISTORY_DAYS))
    since = (request.args.get("since") or "").strip()
    with LOCK:
        rows = list(STATE.get("full_history") or [])
        meta = dict(STATE.get("hist_meta") or {})
    if since:
        rows = [r for r in rows if r["issue"] > since]
    elif days < FULL_HISTORY_DAYS and rows:
        rows = trim_full_history(rows, days)
    payload = [[r["issue"], r["number"], r.get("block_time", "")] for r in rows]
    return jsonify({
        "days": days,
        "count": len(payload),
        "incremental": bool(since),
        "meta": meta,
        "last_time": rows[-1]["block_time"] if rows else None,
        "history": payload,
    })


@app.route("/api/telegram-test")
def api_telegram_test():
    """Header 📡 button — Telegram ချိတ်ဆက်မှု ချက်ချင်း စမ်းသပ်။"""
    cfg = load_tg_config()
    if not cfg:
        return jsonify({"ok": False,
                        "error": "telegram.json မှာ token & chat_id မဖြည့်ရသေးပါ"})
    token, chat = cfg[0], cfg[1]
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": "✅ TRX Terminal — Telegram Test OK"},
            timeout=10)
        if r.status_code == 200:
            return jsonify({"ok": True})
        return jsonify({"ok": False, "error": f"HTTP {r.status_code}: {r.text[:100]}"})
    except requests.RequestException as e:
        return jsonify({"ok": False, "error": str(e)[:100]})


@app.route("/api/latest")
def api_latest():
    """Micro-endpoint (few hundred bytes) — frontend polls this every ~1.2s
       so new candles appear almost instantly without heavy /api/state."""
    with LOCK:
        h = STATE.get("history") or []
        r = h[-1] if h else None
    if not r:
        return jsonify({"round": None})
    return jsonify({"round": {
        "issue": r["issue"],
        "number": r["number"],
        "type": r["type"],
        "block_time": r.get("block_time", ""),
    }})


@app.route("/api/backtest")
def api_backtest():
    if request.args.get("refresh") == "1":
        with LOCK:
            STATE["backtest"] = None      # engine re-calibrates next cycle
    with LOCK:
        bt = STATE.get("backtest")
    return jsonify(bt or {"status": "waiting"})


def start_engine():
    """Idempotent engine bootstrap — dev (`python app.py`) နှင့် cloud
       (gunicorn post_fork) နှစ်မျိုးလုံးမှာ တစ်ခါပဲ စဖြစ်ရမယ်။"""
    global _engine_started
    with _ENGINE_LOCK:
        if _engine_started:
            return
        _engine_started = True
    STATE["log"][:] = load_trade_log()
    if not os.path.exists(TG_CONFIG_FILE):
        try:
            with open(TG_CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump({"token": "PUT_YOUR_BOT_TOKEN_HERE",
                           "chat_id": "PUT_YOUR_CHAT_ID_HERE",
                           "rsi_up": 60,
                           "rsi_down": 40,
                           "remind_sec": 300}, f, indent=2)
            print("📄 telegram.json created — bot token & chat_id ဖြည့်ပါ (TG RSI alerts)", flush=True)
        except OSError:
            pass
    threading.Thread(target=_tg_worker, daemon=True).start()
    threading.Thread(target=engine_loop, daemon=True).start()


_engine_started = False
_ENGINE_LOCK = threading.Lock()


if __name__ == "__main__":
    start_engine()
    print("=" * 52, flush=True)
    print("📈 FOREX-STYLE CONFLUENCE ENGINE v2 — WEB DASHBOARD", flush=True)
    print(f"   EMA {FAST_EMA}/{SLOW_EMA} + MOM + RSI{RSI_PERIOD} + STDEV Filter + Gap + S/R", flush=True)
    print(f"   Chart History: {FULL_HISTORY_DAYS} days ({MAX_FULL_ROWS:,} cap) · BB · RSI Pane · Patterns · S/R · Trendlines", flush=True)
    print(f"   Entry ≥ |{SCORE_TRADE}| | Risk: Flat {BET_SIZE:,} MMK | SL {-STOP_LOSS_UNITS}u / TP +{TAKE_PROFIT_UNITS}u", flush=True)
    print("   Open: http://127.0.0.1:5000", flush=True)
    print("=" * 52, flush=True)
    app.run(
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "5000")),
        threaded=True)


# ---- cloud hosting (gunicorn / Render) — engine starts on module import ----
# TRX_NO_ENGINE=1 → disable (tests, tooling)
if os.environ.get("TRX_NO_ENGINE") != "1":
    start_engine()
