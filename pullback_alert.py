"""Telegram-only observation of the 1m chart's EMA100 pullbacks."""
from datetime import timedelta
from zoneinfo import ZoneInfo

from feed_utils import source_time_utc


EMA_PERIOD = 100
# Twelve EMA periods make the seed's influence negligible while bounding work.
HISTORY_LIMIT = EMA_PERIOD * 12
BANGKOK = ZoneInfo("Asia/Bangkok")


def pullback_alert(rows, ema_series, now):
    """Return a message only for a fresh, qualifying completed 1m candle."""
    if not rows:
        return None
    timestamp = source_time_utc(rows[-1].get("block_time"))
    if timestamp is None or not timedelta(0) <= now - timestamp < timedelta(minutes=1):
        return None

    # Match the chart's +1 BIG / -1 SMALL walk and source-minute OHLC.
    # The absolute walk origin cancels out of slope and crossing comparisons.
    bars = []
    close = 0
    for row in rows[-HISTORY_LIMIT:]:
        when = source_time_utc(row.get("block_time"))
        side = row.get("type")
        if when is None or side not in ("BIG", "SMALL"):
            bars.clear()
            continue
        minute = when.replace(second=0, microsecond=0)
        if bars and minute < bars[-1][0]:
            bars.clear()
        opened = close
        close += 1 if side == "BIG" else -1
        if bars and minute == bars[-1][0]:
            _, first, high, low, _ = bars[-1]
            bars[-1] = (minute, first, max(high, close), min(low, close), close)
        else:
            bars.append((minute, opened, max(opened, close), min(opened, close), close))

    values = ema_series([bar[4] for bar in bars], EMA_PERIOD)
    if len(bars) < EMA_PERIOD + 3:
        return None

    direction = None
    count = 0
    for index in range(len(bars) - 1, EMA_PERIOD - 1, -1):
        minute, opened, high, low, closed = bars[index]
        if index < len(bars) - 1 and bars[index + 1][0] - minute != timedelta(minutes=1):
            break
        previous, current = values[index - 1], values[index]
        # A touch is allowed. Any wick extending through EMA100 breaks the run.
        if closed > opened and current < previous and high <= current:
            match = "down"
        elif closed < opened and current > previous and low >= current:
            match = "up"
        else:
            break
        if direction and match != direction:
            break
        direction = match
        count += 1

    if count < 3:
        return None
    label, candle, position = (
        ("🔴 Downtrend", "အတက်", "အောက်") if direction == "down"
        else ("🟡 Uptrend", "အကျ", "အပေါ်")
    )
    end = (bars[-1][0] + timedelta(minutes=1)).astimezone(BANGKOK)
    return (
        f"{label} · {candle} candle {count} တုံးဆက်တိုက်\n"
        f"{count} တုံးလုံး အပြာအစက်လိုင်း{position}မှာ ရှိပါတယ်။\n"
        f"TRX/ROUND · 1m · {end:%H:%M} Bangkok"
    )
