from pathlib import Path

p = Path('app_core.py')
s = p.read_text(encoding='utf-8')

old = '''RADAR_UP = 60.0\nRADAR_RESET_UP = 55.0\n\n\ndef rsi_alert_state'''
new = '''RADAR_UP = 60.0\nRADAR_RESET_UP = 55.0\n\n# ---- 🔥 BIG/SMALL STREAK TELEGRAM ALERT ----\n# Notify once at streak 8, then again for every fresh round while the same side\n# continues (9, 10, 11, ...). This is notification-only and does not affect\n# signal generation, risk, 12-step, Robust, chart, or settlement logic.\nTG_STREAK_ALERT_FROM = 8\n\n\ndef consecutive_bs_streak(history):\n    \"\"\"Return (BIG|SMALL, count) for the current completed-round streak.\"\"\"\n    if not history:\n        return None, 0\n    last_type = history[-1].get(\"type\")\n    if last_type not in (\"BIG\", \"SMALL\"):\n        return None, 0\n    count = 0\n    for row in reversed(history):\n        if row.get(\"type\") != last_type:\n            break\n        count += 1\n    return last_type, count\n\n\ndef format_streak_telegram(latest, streak_type, streak_count):\n    \"\"\"Pure formatter for the long-streak Telegram notification.\"\"\"\n    icon = \"🔴\" if streak_type == \"BIG\" else \"🔵\"\n    label = \"BIG (B)\" if streak_type == \"BIG\" else \"SMALL (S)\"\n    short_issue = str((latest or {}).get(\"short_issue\") or (latest or {}).get(\"issue\") or \"\")[-6:]\n    block_time = str((latest or {}).get(\"block_time\") or \"\")\n    return (\n        \"[STREAK ALERT]\\n\"\n        f\"{icon} {label} × {int(streak_count)} CONSECUTIVE\\n\\n\"\n        f\"Current Streak: {int(streak_count)} rounds\\n\"\n        f\"Latest Issue: …{short_issue}\\n\"\n        f\"Latest Result: {streak_type}\\n\"\n        f\"Time: {block_time or '—'}\\n\\n\"\n        f\"Status: 🔥 {label} has continued for {int(streak_count)} rounds.\"\n    )\n\n\ndef rsi_alert_state'''
if old not in s:
    raise SystemExit('streak constant/helper insertion target not found')
s = s.replace(old, new, 1)

old = '''    global radar_armed_up, radar_armed_down\n    global strat_state, strat_pending\n    # ---- tail-mode polling state (local to engine thread) ----'''
new = '''    global radar_armed_up, radar_armed_down\n    global strat_state, strat_pending\n    # Notification-only dedupe: engine already processes each fresh issue once;\n    # this additionally guarantees one streak message per issue in this process.\n    last_streak_alert_issue = None\n    # ---- tail-mode polling state (local to engine thread) ----'''
if old not in s:
    raise SystemExit('engine local streak guard insertion target not found')
s = s.replace(old, new, 1)

old = '''                        analysis = analyze_all_in_one(parsed_history)\n\n                        # ---- ⚠️ PRE-SIGNAL RADAR (RSI 40/60 · hysteresis 45/55) ----'''
new = '''                        analysis = analyze_all_in_one(parsed_history)\n\n                        # ---- 🔥 BIG/SMALL LONG-STREAK TELEGRAM ALERT ----\n                        # Notification only: 8 first, then every fresh continuation 9,10,11,...\n                        streak_type, streak_count = consecutive_bs_streak(parsed_history)\n                        if (streak_type in (\"BIG\", \"SMALL\")\n                                and streak_count >= TG_STREAK_ALERT_FROM\n                                and latest[\"issue\"] != last_streak_alert_issue):\n                            tg_notify(format_streak_telegram(latest, streak_type, streak_count))\n                            last_streak_alert_issue = latest[\"issue\"]\n                            print(\n                                f\"[STREAK] {streak_type} x{streak_count} @ …{latest['short_issue']}\",\n                                flush=True,\n                            )\n\n                        # ---- ⚠️ PRE-SIGNAL RADAR (RSI 40/60 · hysteresis 45/55) ----'''
if old not in s:
    raise SystemExit('streak runtime insertion target not found')
s = s.replace(old, new, 1)

p.write_text(s, encoding='utf-8')

Path('tests_streak_alert.py').write_text(r'''import os
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
''', encoding='utf-8')
