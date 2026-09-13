import os
os.environ["TRX_NO_ENGINE"] = "1"
import app_core as c


def row(issue, typ):
    return {
        "issue": str(issue),
        "short_issue": str(issue)[-6:],
        "type": typ,
        "block_time": "2026-09-13 12:23:00",
    }


def test_streak_counting():
    h = [row(i, "SMALL") for i in range(1, 4)] + [row(i, "BIG") for i in range(4, 12)]
    typ, n = c.consecutive_bs_streak(h)
    assert typ == "BIG" and n == 8
    h.append(row(12, "BIG"))
    assert c.consecutive_bs_streak(h) == ("BIG", 9)
    h.append(row(13, "SMALL"))
    assert c.consecutive_bs_streak(h) == ("SMALL", 1)


def test_threshold_is_eight():
    assert c.TG_STREAK_ALERT_FROM == 8


def test_formatter_big_and_small():
    b = c.format_streak_telegram(row("20260913103010888", "BIG"), "BIG", 8)
    assert "[STREAK ALERT]" in b
    assert "BIG (B) × 8 CONSECUTIVE" in b
    assert "Current Streak: 8 rounds" in b
    s = c.format_streak_telegram(row("20260913103010999", "SMALL"), "SMALL", 12)
    assert "SMALL (S) × 12 CONSECUTIVE" in s
    assert "Current Streak: 12 rounds" in s


def test_strategy_constants_unchanged():
    assert c.RSI_STRAT_OVERSOLD == 32.0
    assert c.RSI_STRAT_OVERBOUGHT == 68.0
    assert c.STAKE_TIERS == [[200, 400, 600, 1200], [2500, 5000, 10000, 20000], [40000, 80000, 160000, 320000]]


if __name__ == "__main__":
    test_streak_counting()
    test_threshold_is_eight()
    test_formatter_big_and_small()
    test_strategy_constants_unchanged()
    print("STREAK ALERT TESTS: ALL PASSED")
