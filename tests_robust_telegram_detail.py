# -*- coding: utf-8 -*-
import robust_integration as ri


def test_running_settlement_message_is_unambiguous():
    msg = ri.format_robust_telegram_event({
        "kind": "settlement",
        "outcome": "LOSS",
        "issue": "20260906103010413",
        "signal": "BIG",
        "actual": "SMALL",
        "stake": 1000,
        "trade_pnl": -1000,
        "daily_profit": -1000,
        "bankroll": 299000,
        "next_paroli_step": 0,
        "next_stake": 1000,
        "trading_active": True,
    })
    assert "Engine: 🟢 RUNNING — no stop triggered" in msg
    assert "Waiting for the next VALID setup" in msg
    assert "new signal is NOT guaranteed" in msg
    assert "Next Eligible Stake: 1,000 MMK" in msg
    assert "Daily TP: +10,000 MMK" in msg
    assert "Daily SL: -8,000 MMK" in msg


def test_stopped_settlement_message_is_unambiguous():
    msg = ri.format_robust_telegram_event({
        "kind": "settlement",
        "outcome": "LOSS",
        "issue": "20260906103010413",
        "signal": "BIG",
        "actual": "SMALL",
        "stake": 1000,
        "trade_pnl": -1000,
        "daily_profit": -8000,
        "bankroll": 292000,
        "next_paroli_step": 0,
        "next_stake": 1000,
        "trading_active": False,
    })
    assert "Engine: 🔴 NOT TRADING" in msg
    assert "Daily SL / hard risk stop reached" in msg
    assert "No more Robust signals until the next daily reset" in msg


def test_signal_and_stop_messages_show_engine_state():
    signal = ri.format_robust_telegram_event({
        "kind": "signal", "issue": "1", "target": "BIG", "paroli_step": 0,
        "stake": 1000, "daily_profit": 960, "bankroll": 300960,
    })
    assert "NEW SIGNAL — TRADE ARMED" in signal
    assert "Engine: 🟢 ACTIVE — this issue is armed" in signal
    assert "Entry filter: |Score| ≥ 40" in signal

    stop = ri.format_robust_telegram_event({
        "kind": "daily_risk_stop", "daily_profit": -8000,
        "bankroll": 292000, "reason": "Daily SL / pre-trade hard risk guard",
    })
    assert "Engine: 🔴 STOPPED FOR TODAY" in stop
    assert "New Robust signals: DISABLED" in stop
    assert "Resume: Automatically at the next daily reset" in stop


if __name__ == "__main__":
    test_running_settlement_message_is_unambiguous()
    test_stopped_settlement_message_is_unambiguous()
    test_signal_and_stop_messages_show_engine_state()
    print("ROBUST TELEGRAM DETAIL TESTS: ALL PASSED")
