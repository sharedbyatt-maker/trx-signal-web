# -*- coding: utf-8 -*-
"""On-demand Monte Carlo risk audit for the independent Robust Engine."""
from __future__ import annotations

import random
from collections import defaultdict

import requests

from robust_engine import (
    BASE_STAKE,
    DAILY_SL,
    DAILY_TP,
    INITIAL_DEPOSIT,
    PAROLI_WINS,
    PAYOUT,
    build_signals,
    normalize_history,
    precompute_features,
)

URL_DATA = "https://trxchart.com/api/trx-data"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
MAX_FETCH_LIMIT = 530000
MC_RUNS = 20000
MC_SEED = 20260906


def fetch_full_history():
    session = requests.Session()
    session.headers.update(HEADERS)
    r = session.get(f"{URL_DATA}?limit={MAX_FETCH_LIMIT}", timeout=90)
    r.raise_for_status()
    data = r.json()
    raw = data if isinstance(data, list) else data.get("data", [])
    rows = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        issue = str(item.get("issueNumber") or item.get("issue") or "")
        val = item.get("number") if item.get("number") is not None else item.get("result")
        bt = str(item.get("blockTime") or item.get("time") or "")
        if not issue or val is None:
            continue
        rows.append({
            "issue": issue,
            "number": val,
            "block_time": bt,
            "date": bt[:10] if len(bt) >= 10 else "",
        })
    history = normalize_history(rows)
    history.sort(key=lambda x: (0, int(x["issue"])) if str(x["issue"]).isdigit() else (1, str(x["issue"])))
    return history


def simulate_true_dd(history, signals, days, days_indices_map):
    balance = INITIAL_DEPOSIT
    peak_equity = INITIAL_DEPOSIT
    max_dd = 0
    max_dd_pct_peak = 0.0

    trades = wins = 0
    daily_profit_list = []
    opportunities_by_day = []
    executed_outcomes = []
    busted = False

    for day in days:
        day_profit = 0
        step = 0

        day_opps = []
        for i in days_indices_map[day]:
            sig = signals[i]
            if sig is not None:
                day_opps.append(history[i]["type"] == sig)
        opportunities_by_day.append(day_opps)

        for i in days_indices_map[day]:
            if day_profit >= DAILY_TP or day_profit <= -DAILY_SL:
                break

            sig = signals[i]
            if sig is None:
                continue

            stake = BASE_STAKE * (2 ** step)
            if day_profit - stake < -DAILY_SL:
                break

            current_equity = balance + day_profit
            if current_equity < stake:
                busted = True
                break

            trades += 1
            is_win = history[i]["type"] == sig
            executed_outcomes.append(is_win)

            if is_win:
                wins += 1
                day_profit += int(round(stake * PAYOUT)) - stake
                step += 1
                if step >= PAROLI_WINS:
                    step = 0
            else:
                day_profit -= stake
                step = 0

            equity = balance + day_profit
            if equity > peak_equity:
                peak_equity = equity

            dd = peak_equity - equity
            if dd > max_dd:
                max_dd = dd
                max_dd_pct_peak = (dd / peak_equity * 100.0) if peak_equity > 0 else 0.0

            if equity <= 0:
                busted = True
                break

        balance += day_profit
        daily_profit_list.append(day_profit)
        if busted:
            break

    n_days = max(1, len(daily_profit_list))
    return {
        "ending_balance": balance,
        "net_profit": balance - INITIAL_DEPOSIT,
        "avg_daily": sum(daily_profit_list) / n_days,
        "trades": trades,
        "wins": wins,
        "win_rate": wins / trades * 100 if trades else 0.0,
        "max_dd": max_dd,
        "max_dd_pct_initial": max_dd / INITIAL_DEPOSIT * 100,
        "max_dd_pct_peak": max_dd_pct_peak,
        "daily_profit_list": daily_profit_list,
        "opportunities_by_day": opportunities_by_day,
        "executed_outcomes": executed_outcomes,
        "busted": busted,
    }


def simulate_mc_once(shuffled_outcomes, opp_counts):
    balance = INITIAL_DEPOSIT
    peak = INITIAL_DEPOSIT
    max_dd = 0
    ptr = 0
    trades = wins = 0
    busted = False

    for count in opp_counts:
        day_profit = 0
        step = 0

        for _ in range(count):
            is_win = shuffled_outcomes[ptr]
            ptr += 1

            if day_profit >= DAILY_TP or day_profit <= -DAILY_SL:
                continue

            stake = BASE_STAKE * (2 ** step)
            if day_profit - stake < -DAILY_SL:
                continue

            equity_before = balance + day_profit
            if equity_before < stake:
                busted = True
                continue

            trades += 1
            if is_win:
                wins += 1
                day_profit += int(round(stake * PAYOUT)) - stake
                step += 1
                if step >= PAROLI_WINS:
                    step = 0
            else:
                day_profit -= stake
                step = 0

            equity = balance + day_profit
            if equity > peak:
                peak = equity

            dd = peak - equity
            if dd > max_dd:
                max_dd = dd

            if equity <= 0:
                busted = True

        balance += day_profit

    return balance, max_dd, busted, trades, wins


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def monte_carlo(opportunities_by_day, runs=MC_RUNS, seed=MC_SEED, progress=None):
    flat = [x for day in opportunities_by_day for x in day]
    opp_counts = [len(day) for day in opportunities_by_day]
    if not flat:
        raise ValueError("No Robust signal opportunities in locked-test window")

    rng = random.Random(seed)
    end_balances = []
    max_dds = []
    busts = below_initial = dd_over_20 = dd_over_30 = 0
    work = flat[:]

    for n in range(runs):
        work[:] = flat
        rng.shuffle(work)
        end_bal, dd, busted, _, _ = simulate_mc_once(work, opp_counts)
        end_balances.append(end_bal)
        max_dds.append(dd)

        if busted:
            busts += 1
        if end_bal < INITIAL_DEPOSIT:
            below_initial += 1
        if dd > INITIAL_DEPOSIT * 0.20:
            dd_over_20 += 1
        if dd > INITIAL_DEPOSIT * 0.30:
            dd_over_30 += 1

        if progress and ((n + 1) % max(1, runs // 20) == 0 or n + 1 == runs):
            progress("monte_carlo", int((n + 1) * 100 / runs))

    end_balances.sort()
    max_dds.sort()

    return {
        "runs": runs,
        "median_end": percentile(end_balances, 0.50),
        "p05_end": percentile(end_balances, 0.05),
        "p01_end": percentile(end_balances, 0.01),
        "worst_end": end_balances[0],
        "median_dd": percentile(max_dds, 0.50),
        "p95_dd": percentile(max_dds, 0.95),
        "p99_dd": percentile(max_dds, 0.99),
        "worst_dd": max_dds[-1],
        "p_loss": below_initial / runs * 100,
        "p_bust": busts / runs * 100,
        "p_dd20": dd_over_20 / runs * 100,
        "p_dd30": dd_over_30 / runs * 100,
        "total_opps": len(flat),
        "opp_wr": sum(flat) / len(flat) * 100,
    }


def run_full_audit(progress=None, history=None, runs=MC_RUNS):
    if progress:
        progress("fetching_history", 2)
    history = normalize_history(history) if history is not None else fetch_full_history()
    if len(history) < 1000:
        raise ValueError("Not enough history for Robust risk audit")

    if progress:
        progress("computing_features", 8)
    feat = precompute_features(history)
    signals = build_signals(history, feat)

    days = sorted({x["date"] for x in history if x.get("date")})
    if len(days) < 5:
        raise ValueError("Not enough dated history for locked-test audit")

    test_days = days[int(len(days) * 0.80):]
    days_indices_map = defaultdict(list)
    for idx, row in enumerate(history):
        days_indices_map[row["date"]].append(idx)

    if progress:
        progress("locked_test", 12)
    actual = simulate_true_dd(history, signals, test_days, days_indices_map)
    if not actual["opportunities_by_day"] or not any(actual["opportunities_by_day"]):
        raise ValueError("No Robust signal opportunities in locked-test window")

    mc = monte_carlo(actual["opportunities_by_day"], runs=runs, progress=progress)
    if progress:
        progress("complete", 100)

    return {
        "history_rounds": len(history),
        "history_days": len(days),
        "locked_test_days": len(test_days),
        "actual_locked_test": actual,
        "monte_carlo": mc,
    }
