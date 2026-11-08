from datetime import datetime, timedelta, timezone

from app_core import ema_series
from pullback_alert import pullback_alert


START = datetime(2026, 11, 8, 0, 0, 54, tzinfo=timezone.utc)
MINUTE = timedelta(minutes=1)


def rounds(sides):
    return [
        {"type": side, "block_time": (START + i * MINUTE).isoformat()}
        for i, side in enumerate(sides)
    ]


def alert(rows, age=0, ema=ema_series):
    now = datetime.fromisoformat(rows[-1]["block_time"]) + timedelta(seconds=age)
    return pullback_alert(rows, ema, now)


def test_downtrend_starts_at_three_repeats_and_resets():
    rows = rounds(["SMALL"] * 160 + ["BIG"] * 5 + ["SMALL"] + ["BIG"] * 3)
    assert alert(rows[:162]) is None
    for count in (3, 4, 5):
        assert f"🔴 Downtrend · အတက် candle {count}" in alert(rows[:160 + count])
    assert alert(rows[:166]) is None
    assert alert(rows[:168]) is None
    assert "candle 3" in alert(rows)


def test_uptrend_and_stale_or_future_data():
    rows = rounds(["BIG"] * 160 + ["SMALL"] * 4)
    message = alert(rows)
    assert "🟡 Uptrend · အကျ candle 4" in message
    assert "TRX/ROUND · 1m · 09:44 Bangkok" in message
    assert alert(rows, age=60) is None
    assert alert(rows, age=-1) is None


def test_gap_and_wick_crossing_reset():
    rows = rounds(["SMALL"] * 160 + ["BIG"] * 3)
    assert alert(rows)
    rows[-1]["block_time"] = (START + len(rows) * MINUTE).isoformat()
    assert alert(rows) is None

    rows = rounds(["SMALL"] * 160 + ["BIG"] * 3)
    # Three additions in the same final minute make a wick above the EMA,
    # although the candle still closes below it and stays green.
    rows += [dict(rows[-1], type=side) for side in ["BIG", "BIG", "SMALL", "SMALL"]]

    def line(closes, period):
        return [None] * 99 + [-155] * (len(closes) - 103) + [-155, -156, -157, -156.5]

    # Use a falling synthetic EMA with final close (-157) below it.
    def falling_line(closes, period):
        return line(closes, period)[:-4] + [-153, -154, -155, -156.5]

    assert alert(rows[:-4], ema=falling_line)
    assert alert(rows, ema=falling_line) is None
