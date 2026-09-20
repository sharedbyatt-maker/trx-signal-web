import os
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ["TRX_NO_ENGINE"] = "1"

import l1_capital as l1


def make_rows(count, outcomes=None):
    outcomes = outcomes or ["BIG"] * count
    return [
        {
            "issue": str(20260920000000000 + i),
            "type": outcomes[i],
            "block_time": f"2026-09-20 12:{i % 60:02d}:00",
        }
        for i in range(count)
    ]


def replay(rows, rsi):
    with patch.object(l1, "_rsi", return_value=rsi):
        return l1.replay_l1(rows)


class FakeCore:
    def __init__(self, rows, next_issue="20260920999999999"):
        self.LOCK = threading.Lock()
        self.STATE = {"full_history": rows, "next_issue": next_issue}
        self.messages = []

    def tg_notify(self, message):
        self.messages.append(message)


class L1CapitalTests(unittest.TestCase):
    def test_base_500_frozen_ladder_and_parameters(self):
        self.assertEqual(l1.STAKES[0], [500, 1000, 1500, 3000])
        self.assertEqual(l1.STAKES[1], [6250, 12500, 25000, 50000])
        self.assertEqual(l1.STAKES[2], [100000, 200000, 400000, 800000])
        self.assertEqual((l1.RSI_PERIOD, l1.OVERSOLD, l1.OVERBOUGHT), (14, 32.0, 68.0))
        self.assertEqual((l1.PAYOUT, l1.WORKING_BANKROLL), (1.96, 100_000))
        self.assertEqual((l1.DAILY_TP, l1.DAILY_SL), (5_000, 50_000))

    def test_frozen_rules_exact(self):
        self.assertEqual(l1.RULES, (
            {"id": "R02", "when": {"rsi_bucket": "70-79", "step": 1}, "skip": 3},
            {"id": "R03", "when": {"rsi_direction": "rising", "step": 2}, "skip": 2},
            {"id": "R05", "when": {"rsi_direction": "falling", "step": 1}, "skip": 3},
            {"id": "R06", "when": {"rsi_direction": "rising", "step": 1}, "skip": 1},
        ))
        self.assertEqual(l1._rule_skip([50, 75], 1, 1), (3, "R02"))
        self.assertEqual(l1._rule_skip([50, 55], 1, 2), (2, "R03"))
        self.assertEqual(l1._rule_skip([55, 50], 1, 1), (3, "R05"))
        self.assertEqual(l1._rule_skip([45, 50], 1, 1), (1, "R06"))

    def test_signal_uses_previous_rsi_and_next_target_issue(self):
        rows = make_rows(18)
        rsi = [50.0] * 18
        rsi[-2] = 31.0
        out = replay(rows, rsi)
        self.assertEqual(out["pending"]["target"], "BIG")
        self.assertIsNone(out["pending"]["issue"])
        self.assertEqual((out["pending"]["tier"], out["pending"]["step"]), (1, 1))
        self.assertEqual(out["pending"]["stake"], 500)

        core = FakeCore(rows, "20260920000000018")
        service = l1.L1CapitalService(core, state_file="")
        with patch.object(l1, "_rsi", return_value=rsi):
            snap = service.refresh_once()
        self.assertEqual(snap["pending"]["issue"], "20260920000000018")
        self.assertIn("Issue: 20260920000000018", core.messages[0])

    def test_win_resets_to_tier_one(self):
        outcomes = ["SMALL"] * 20
        outcomes[15] = outcomes[16] = "BIG"
        outcomes[-1] = "BIG"
        rsi = [50.0] * 20
        rsi[14] = 31.0
        rsi[-2] = 31.0
        out = replay(make_rows(20, outcomes), rsi)
        self.assertTrue(any(t["won"] and t["tier"] == 1 and t["step"] == 1 for t in out["trades"]))
        self.assertEqual((out["pending"]["tier"], out["pending"]["step"], out["pending"]["stake"]), (1, 1, 500))

    def test_loss_progresses_to_exact_next_stake(self):
        outcomes = ["SMALL"] * 17
        outcomes[15] = "BIG"
        rsi = [50.0] * 17
        rsi[14] = 31.0
        out = replay(make_rows(17, outcomes), rsi)
        self.assertEqual(out["trades"][-1]["pnl"], -500)
        self.assertEqual((out["pending"]["tier"], out["pending"]["step"], out["pending"]["stake"]), (1, 2, 1000))

    def test_skip_rule_waits_then_rearms_without_lookahead(self):
        outcomes = ["SMALL"] * 20
        outcomes[15] = "BIG"
        rsi = [50.0] * 20
        rsi[14] = 31.0
        rsi[16] = 75.0
        waiting = replay(make_rows(19, outcomes[:19]), rsi[:19])
        self.assertIsNone(waiting["pending"])
        self.assertEqual(waiting["waiting_rule"]["rule"], "R02")
        armed = replay(make_rows(20, outcomes), rsi)
        self.assertEqual((armed["pending"]["tier"], armed["pending"]["step"], armed["pending"]["stake"]), (1, 2, 1000))
        self.assertEqual(armed["pending"]["rule"], "R02")

    def test_completed_tier_requires_fresh_signal_and_moves_to_tier_two(self):
        outcomes = ["SMALL"] * 20
        outcomes[15] = "BIG"
        rsi = [50.0] * 20
        rsi[14] = 31.0
        rsi[18] = 70.0
        out = replay(make_rows(20, outcomes), rsi)
        self.assertEqual([t["stake"] for t in out["trades"][-4:]], [500, 1000, 1500, 3000])
        self.assertEqual((out["pending"]["target"], out["pending"]["tier"], out["pending"]["step"]), ("SMALL", 2, 1))
        self.assertEqual(out["pending"]["stake"], 6250)

    def test_tp_observe_only_does_not_stop_next_signal(self):
        rows = make_rows(28)
        rsi = [50.0] * 28
        for i in range(14, 28):
            rsi[i] = 31.0
        out = replay(rows, rsi)
        self.assertGreaterEqual(out["today_pnl"], l1.DAILY_TP)
        self.assertIn("TP REACHED", out["risk_status"])
        self.assertIsNotNone(out["pending"])

    def test_sl_observe_only_does_not_stop_next_signal(self):
        outcomes = ["SMALL"] * 24
        outcomes[15] = "BIG"
        outcomes[20:24] = ["BIG"] * 4
        rsi = [50.0] * 24
        rsi[14] = 31.0
        rsi[18] = 70.0
        rsi[22] = 31.0
        out = replay(make_rows(24, outcomes), rsi)
        self.assertLessEqual(out["today_pnl"], -l1.DAILY_SL)
        self.assertIn("SL REACHED", out["risk_status"])
        self.assertEqual((out["pending"]["tier"], out["pending"]["step"], out["pending"]["stake"]), (3, 1, 100000))

    def test_signal_telegram_is_namespaced_exact_and_deduplicated(self):
        rows = make_rows(18)
        rsi = [50.0] * 18
        rsi[-2] = 31.0
        core = FakeCore(rows)
        service = l1.L1CapitalService(core, state_file="")
        with patch.object(l1, "_rsi", return_value=rsi):
            service.refresh_once()
            service.refresh_once()
        self.assertEqual(len(core.messages), 1)
        message = core.messages[0]
        for token in ("[L1 CAPITAL]", "Target: BIG", "BET: 500 MMK", "T1-S1", "TRADE ALLOWED", "Working BR: 100,000 MMK"):
            self.assertIn(token, message)

    def test_withdrawal_milestone_alert_is_manual_and_deduplicated(self):
        core = FakeCore(make_rows(18))
        service = l1.L1CapitalService(core, state_file="")
        snap = {
            "ready": True, "pending": None, "withdraw_milestones_reached": 1,
            "today_pnl": 0, "model_total_pnl": 50_000,
        }
        with patch.object(l1, "replay_l1", return_value=snap):
            service.refresh_once()
            service.refresh_once()
        milestone_messages = [m for m in core.messages if "WITHDRAWAL MILESTONE" in m]
        self.assertEqual(len(milestone_messages), 1)
        self.assertIn("50,000 MMK", milestone_messages[0])
        self.assertIn("withdraw manually", milestone_messages[0])

    def test_result_win_and_loss_notifications_are_namespaced_and_deduplicated(self):
        core = FakeCore(make_rows(18))
        service = l1.L1CapitalService(core, state_file="")
        base = {
            "ready": True, "pending": None, "waiting_rule": None,
            "withdraw_milestones_reached": 0, "today_pnl": 480,
            "model_total_pnl": 480, "risk_status": "TRADE ALLOWED",
        }
        win = dict(base, last_trade={
            "issue": "101", "target": "BIG", "actual": "BIG", "stake": 500,
            "tier": 1, "step": 1, "pnl": 480, "won": True,
        })
        with patch.object(l1, "replay_l1", return_value=win):
            service.refresh_once()
            service.refresh_once()
        wins = [m for m in core.messages if "— RESULT" in m]
        self.assertEqual(len(wins), 1)
        self.assertIn("✅ WIN [L1 CAPITAL]", wins[0])
        self.assertIn("Issue: 101", wins[0])
        self.assertIn("P/L: +480 MMK", wins[0])

        loss = dict(base, today_pnl=-20, last_trade={
            "issue": "102", "target": "BIG", "actual": "SMALL", "stake": 500,
            "tier": 1, "step": 1, "pnl": -500, "won": False,
        }, pending={"issue": "103", "target": "BIG", "stake": 1000, "tier": 1, "step": 2})
        with patch.object(l1, "replay_l1", return_value=loss):
            service.refresh_once()
            service.refresh_once()
        losses = [m for m in core.messages if "❌ LOSS [L1 CAPITAL]" in m]
        self.assertEqual(len(losses), 1)
        self.assertIn("Next: BIG · 1,000 MMK · T1-S2", losses[0])

    def test_wait_rule_notification_only_on_state_change(self):
        core = FakeCore(make_rows(18))
        service = l1.L1CapitalService(core, state_file="")
        snap = {
            "ready": True, "pending": None, "last_trade": None,
            "waiting_rule": {"rule": "R02", "target": "BIG", "stake": 1000, "tier": 0, "bets": 1},
            "withdraw_milestones_reached": 0, "today_pnl": -500,
            "model_total_pnl": -500, "risk_status": "TRADE ALLOWED",
        }
        with patch.object(l1, "replay_l1", return_value=snap):
            service.refresh_once()
            service.refresh_once()
        waits = [m for m in core.messages if "WAIT / SKIP" in m]
        self.assertEqual(len(waits), 1)
        self.assertIn("Rule: R02", waits[0])
        self.assertIn("No manual bet now", waits[0])

    def test_plain_wait_is_transition_only_and_survives_restart(self):
        snap = {
            "ready": True, "pending": None, "last_trade": None, "waiting_rule": None,
            "withdraw_milestones_reached": 0, "today_pnl": 0,
            "model_total_pnl": 0, "risk_status": "TRADE ALLOWED",
        }
        with tempfile.TemporaryDirectory() as tmp:
            state_file = str(Path(tmp) / "l1.json")
            first = FakeCore(make_rows(18))
            second = FakeCore(make_rows(18))
            with patch.object(l1, "replay_l1", return_value=snap):
                svc = l1.L1CapitalService(first, state_file=state_file)
                svc.refresh_once(); svc.refresh_once()
                l1.L1CapitalService(second, state_file=state_file).refresh_once()
            self.assertEqual(len([m for m in first.messages if "— WAIT" in m]), 1)
            self.assertEqual(second.messages, [])

    def test_signal_dedupe_survives_service_restart(self):
        rows = make_rows(18)
        rsi = [50.0] * 18
        rsi[-2] = 31.0
        with tempfile.TemporaryDirectory() as tmp:
            state_file = str(Path(tmp) / "l1.json")
            first = FakeCore(rows)
            second = FakeCore(rows)
            with patch.object(l1, "_rsi", return_value=rsi):
                l1.L1CapitalService(first, state_file=state_file).refresh_once()
                l1.L1CapitalService(second, state_file=state_file).refresh_once()
            self.assertEqual(len(first.messages), 1)
            self.assertEqual(second.messages, [])

    def test_api_and_manual_only_startup_contract(self):
        import app
        client = app.app.test_client()
        response = client.get("/api/l1-capital")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["engine"], "L1 CAPITAL")
        source = Path("l1_capital.py").read_text(encoding="utf-8").lower()
        for forbidden in ("place_bet", "auto_bet", "6win"):
            self.assertNotIn(forbidden, source)

    def test_robust_backend_routes_and_assets_are_absent(self):
        import app
        root = Path(".")
        self.assertFalse((root / "robust_engine.py").exists())
        self.assertFalse((root / "robust_integration.py").exists())
        self.assertFalse((root / "static/js/robust.js").exists())
        self.assertFalse((root / "static/css/robust.css").exists())
        client = app.app.test_client()
        prefix = "/api/" + "rob" + "ust-engine"
        self.assertEqual(client.get(prefix + "/status").status_code, 404)
        html = client.get("/").get_data(as_text=True).lower()
        self.assertNotIn("rob" + "ust signal engine", html)


if __name__ == "__main__":
    unittest.main(verbosity=2)
