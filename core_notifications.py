# -*- coding: utf-8 -*-
"""Pure notification decision/formatting helpers.

These functions have no I/O and preserve the legacy engine's public behavior.
"""
from core_config import TG_HYST, TG_REMIND_SEC


def consecutive_bs_streak(history):
    """Return (BIG|SMALL, count) for the current completed-round streak."""
    if not history:
        return None, 0
    last_type = history[-1].get("type")
    if last_type not in ("BIG", "SMALL"):
        return None, 0
    count = 0
    for row in reversed(history):
        if row.get("type") != last_type:
            break
        count += 1
    return last_type, count


def format_streak_telegram(latest, streak_type, streak_count):
    """Pure formatter for the long-streak Telegram notification."""
    icon = "🔴" if streak_type == "BIG" else "🔵"
    label = "BIG (B)" if streak_type == "BIG" else "SMALL (S)"
    short_issue = str((latest or {}).get("short_issue") or (latest or {}).get("issue") or "")[-6:]
    block_time = str((latest or {}).get("block_time") or "")
    return (
        "[STREAK ALERT]\n"
        f"{icon} {label} × {int(streak_count)} CONSECUTIVE\n\n"
        f"Current Streak: {int(streak_count)} rounds\n"
        f"Latest Issue: …{short_issue}\n"
        f"Latest Result: {streak_type}\n"
        f"Time: {block_time or '—'}\n\n"
        f"Status: 🔥 {label} has continued for {int(streak_count)} rounds."
    )


def rsi_alert_state(r_now, up_lv, dn_lv, armed_up, armed_down,
                    up_ts, down_ts, now_ts, remind_sec=TG_REMIND_SEC):
    """Pure zone/edge logic (unit-testable).
       Every fresh reach of the level sends exactly once; re-arms only after a
       real pullback of TG_HYST — kills oscillation spam & Telegram 429 drops."""
    msgs = []
    # ---- up side ----
    if r_now >= up_lv:
        if armed_up:
            msgs.append(("enter_up", up_lv))
            armed_up = False
            up_ts = now_ts
        elif now_ts - up_ts >= remind_sec:
            msgs.append(("remind_up", up_lv))
            up_ts = now_ts
    elif r_now < up_lv - TG_HYST:
        armed_up = True
    # ---- down side ----
    if r_now <= dn_lv:
        if armed_down:
            msgs.append(("enter_down", dn_lv))
            armed_down = False
            down_ts = now_ts
        elif now_ts - down_ts >= remind_sec:
            msgs.append(("remind_down", dn_lv))
            down_ts = now_ts
    elif r_now > dn_lv + TG_HYST:
        armed_down = True
    return msgs, armed_up, armed_down, up_ts, down_ts
