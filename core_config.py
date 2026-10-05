# -*- coding: utf-8 -*-
"""Runtime configuration for the legacy TRX engine.

Values are intentionally unchanged from app_core.py. Keeping them here makes
configuration reviewable without mixing it with signal, settlement, HTTP, and
background-worker behavior.
"""
import os

# ================= DATA SOURCE =================
URL_DATA = "https://trxchart.com/api/trx-data"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# Low-latency tail polling. Keep these env-tunable so hosting can back off
# without a code deploy if the upstream source ever rate-limits.
try:
    POLL_SEC = max(0.25, min(float(os.environ.get("TRX_POLL_SEC", "0.5")), 5.0))
except (TypeError, ValueError):
    POLL_SEC = 0.5
try:
    TAIL_LIMIT = max(20, min(int(os.environ.get("TRX_TAIL_LIMIT", "50")), 500))
except (TypeError, ValueError):
    TAIL_LIMIT = 50

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

# ================= 12-STEP STAKING ENGINE (3-Tier × 4-Step) =================
# 90-day backtest နဲ့ အတည်ပြုခဲ့တဲ့ strategy (strategy_test.py)
STAKE_TIERS = [
    [200, 400, 600, 1200],              # Tier 1 (4 Steps)
    [2500, 5000, 10000, 20000],         # Tier 2 (4 Steps)
    [40000, 80000, 160000, 320000],     # Tier 3 (4 Steps)
]
STAKE_PAYOUT = 1.96
RSI_STRAT_PERIOD = 14
RSI_STRAT_OVERSOLD = 32.0     # prev RSI ≤32 & cur=BIG → next bet BIG
RSI_STRAT_OVERBOUGHT = 68.0   # prev RSI ≥68 & cur=SMALL → next bet SMALL

LOG_FILE = os.path.join(BASE_DIR, "signals_log.csv")
HIST_FILE = os.path.join(BASE_DIR, "signals_history.csv")
STRAT_DAILY_FILE = os.path.join(BASE_DIR, "strat_daily_reports.json")
HISTORY_KEEP = 400
LOG_KEEP = 200
SIGNALS_KEEP = 300

# ================= FULL CHART HISTORY (30 DAYS) =================
FULL_HISTORY_DAYS = 30          # chart အတွက် သိမ်းဆည်းမယ့် ရက်အရေအတွက်
MAX_FULL_ROWS = 45200           # memory safety cap

# ================= TELEGRAM NOTIFICATIONS =================
# telegram.json → {"token": "<BotFather token>", "chat_id": "<your chat id>"}
TG_CONFIG_FILE = os.path.join(BASE_DIR, "telegram.json")
TG_RSI_UP = 60.0        # chart RSI pane — 60 ကျော်ရင် Noti
TG_RSI_DOWN = 40.0      # 40 အောက်ဆင်းရင် Noti
TG_MIN_GAP_SEC = 30     # anti-spam: message ကြားခံ အနည်းဆုံး gap
TG_REMIND_SEC = 300     # zone ထဲ ဆက်ရှိနေရင် 5 မိနစ်တစ်ခါ reminder
TG_HYST = 2.0           # hysteresis — re-arm ဖို့ level ကနေ ဒီအောက်မှာ ဆင်းရမယ်

# ---- ⚠️ PRE-SIGNAL RADAR (RSI 40/60 · hysteresis 45/55) ----
# 33/67 trading signal မလာခင် ကြိုပြင်ဆင်ဖို့ radar — buffer zone logic:
#   oversold : fire RSI<40 · reset RSI>45 (45 အထက် ပြန်တက်မှ ပြန်အလုပ်လုပ်)
#   overbought: fire RSI>60 · reset RSI<55 (55 အောက် ပြန်ဆင်းမှ ပြန်အလုပ်လုပ်)
RADAR_DOWN = 40.0
RADAR_RESET_DOWN = 45.0
RADAR_UP = 60.0
RADAR_RESET_UP = 55.0

# ---- 🔥 BIG/SMALL STREAK TELEGRAM ALERT ----
# Notify once at streak 8, then again for every fresh round while the same side
# continues (9, 10, 11, ...). This is notification-only and does not affect
# signal generation, risk, 12-step, L1, chart, or settlement logic.
TG_STREAK_ALERT_FROM = 8

