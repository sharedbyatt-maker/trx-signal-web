import copy
import os
import queue
import time
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

os.environ["TRX_NO_ENGINE"] = "1"
import app
import app_core as core
import l1_capital as l1
from feed_utils import next_issue_number, feed_delay_seconds
from tests_l1_capital import FakeCore, make_rows


class SixFixesTests(unittest.TestCase):
    def test_midnight_month_and_year_rollover(self):
        cases = {
            "20261001103011439": "20261001103011440",
            "20261001103011440": "20261002103010001",
            "20261231103011440": "20270101103010001",
            "20260228103011440": "20260301103010001",
            "20280229103011440": "20280301103010001",
            "123": "124", "": "NEXT",
        }
        for old, new in cases.items():
            self.assertEqual(next_issue_number(old), new)

    def service_with_signal(self):
        fake = FakeCore(make_rows(18))
        service = l1.L1CapitalService(fake, state_file="")
        rsi = [50.0] * 18
        rsi[-2] = 31.0
        return fake, service, rsi

    def test_offline_hides_signal_and_suppresses_notifications(self):
        fake, service, rsi = self.service_with_signal()
        fake.STATE["connected"] = False
        with patch.object(l1, "_rsi", return_value=rsi):
            snap = service.refresh_once()
        self.assertFalse(snap["ready"])
        self.assertIsNone(snap["pending"])
        self.assertEqual(snap["feed_status"], "OFFLINE")
        self.assertEqual(fake.messages, [])

    def test_stale_api_snapshot_expires_without_observer_refresh(self):
        fake, service, rsi = self.service_with_signal()
        with patch.object(l1, "_rsi", return_value=rsi):
            self.assertTrue(service.refresh_once()["ready"])
        fake.STATE["last_result_received_mono"] = time.monotonic() - 90
        snap = service.public_snapshot()
        self.assertFalse(snap["ready"])
        self.assertIsNone(snap["pending"])
        self.assertEqual(snap["feed_status"], "STALE")

    def test_offline_then_recovery_reissues_only_unqueued_signal(self):
        fake, service, rsi = self.service_with_signal()
        with patch.object(l1, "_rsi", return_value=rsi):
            fake.STATE["feed_health"]["status"] = "STALE"
            service.refresh_once()
            self.assertEqual(fake.messages, [])
            fake.STATE["feed_health"]["status"] = "LIVE"
            self.assertTrue(service.refresh_once()["ready"])
            service.refresh_once()
        self.assertEqual(len(fake.messages), 1)

    def test_old_boot_snapshot_cannot_arm_signal_just_because_http_is_fresh(self):
        fake, service, rsi = self.service_with_signal()
        fake.STATE["feed_delay"] = 600
        with patch.object(l1, "_rsi", return_value=rsi):
            snap = service.refresh_once()
        self.assertEqual(snap["feed_status"], "STALE")
        self.assertIsNone(snap["pending"])
        self.assertEqual(fake.messages, [])

    def test_queue_full_signal_retries_after_space_available(self):
        fake, service, rsi = self.service_with_signal()
        with patch.object(l1, "_rsi", return_value=rsi):
            with patch.object(fake, "tg_notify", return_value=False):
                service.refresh_once()
            self.assertIsNone(service._last_alert_key)
            service.refresh_once()
            service.refresh_once()
        self.assertEqual(len(fake.messages), 1)

    def test_failed_result_wait_and_milestone_are_not_deduped(self):
        fake, service, _ = self.service_with_signal()
        snap = {"ready": True, "pending": None, "waiting_rule": None,
                "last_trade": {"issue": "101", "target": "BIG", "actual": "BIG",
                               "tier": 1, "step": 1, "stake": 500, "pnl": 480, "won": True},
                "withdraw_milestones_reached": 2, "today_pnl": 480}
        with patch.object(l1, "replay_l1", return_value=snap):
            with patch.object(fake, "tg_notify", return_value=False):
                service.refresh_once()
            self.assertIsNone(service._last_result_key)
            self.assertIsNone(service._last_mode)
            self.assertEqual(service._last_withdraw_units, 0)
            service.refresh_once()
            count = len(fake.messages)
            service.refresh_once()
        self.assertEqual(len(fake.messages), count)
        self.assertEqual(service._last_withdraw_units, 2)

    def test_daily_summary_includes_more_than_100_trades(self):
        rows = make_rows(200)
        with patch.object(l1, "_rsi", return_value=[31.0] * 200):
            snap = l1.replay_l1(rows)
        summary = snap["daily_summary"]
        self.assertEqual(len(snap["trades"]), 100)
        self.assertEqual(summary["bets"], 198)
        self.assertEqual(summary["wins"], 198)
        self.assertEqual(summary["losses"], 0)
        self.assertEqual(summary["staked"], 99_000)
        self.assertEqual(summary["pnl"], 95_040)
        self.assertEqual(summary["pnl"], snap["today_pnl"])

    def test_timezone_delay_and_explicit_offsets(self):
        now = datetime(2026, 10, 2, 12, 0, tzinfo=timezone.utc)
        with patch.dict(os.environ, {"TRX_SOURCE_TIMEZONE": "Asia/Yangon"}):
            self.assertEqual(feed_delay_seconds("2026-10-02 18:20:00", now), 600)
            self.assertEqual(feed_delay_seconds("2026-10-02T18:50:00+07:00", now), 600)
            self.assertEqual(feed_delay_seconds("2026-10-02T11:50:00Z", now), 600)
            self.assertEqual(feed_delay_seconds("2026-10-02 18:30:00", now), 0)
            self.assertIsNone(feed_delay_seconds("invalid", now))
        with patch.dict(os.environ, {"TRX_SOURCE_TIMEZONE": "UTC"}):
            self.assertEqual(feed_delay_seconds("2026-10-02 11:50:00", now), 600)

    def test_telegram_timeout_and_5xx_retry_but_4xx_does_not(self):
        cfg = ("fake-token", "fake-chat")
        with patch.object(core.requests, "post", side_effect=[
            core.requests.ReadTimeout("test"), SimpleNamespace(status_code=503),
            SimpleNamespace(status_code=200, json=lambda: {'ok':True}),
        ]) as post, patch.object(core.time, "sleep") as sleep:
            self.assertEqual(core._send_telegram("test", cfg), "sent (retry)")
            self.assertEqual(post.call_count, 3)
            self.assertEqual(sleep.call_count, 2)
        with patch.object(core.requests, "post", return_value=SimpleNamespace(status_code=400)) as post:
            self.assertEqual(core._send_telegram("test", cfg), "HTTP 400")
            self.assertEqual(post.call_count, 1)

    def test_telegram_429_respects_retry_after_and_exhaustion_is_visible(self):
        rate = SimpleNamespace(status_code=429, json=lambda: {"parameters": {"retry_after": 7}})
        with patch.object(core.requests, "post", side_effect=[rate, SimpleNamespace(status_code=200, json=lambda: {'ok':True})]), \
             patch.object(core.time, "sleep") as sleep:
            self.assertEqual(core._send_telegram("test", ("token", "chat")), "sent (retry)")
            sleep.assert_called_once_with(7)
        with patch.object(core.requests, "post", side_effect=core.requests.ConnectionError("secret-url")), \
             patch.object(core.time, "sleep"):
            result = core._send_telegram("test", ("token", "chat"))
            self.assertIn("failed after 3 attempts", result)
            self.assertNotIn("secret-url", result)

    def test_completed_prefixes_are_causal_and_boot_does_not_replay_old_signals(self):
        rows = [{"issue": str(i)} for i in range(100, 104)]
        prefixes = list(core.completed_prefixes(rows, "100"))
        self.assertEqual([r[-1]["issue"] for r in prefixes], ["101", "102", "103"])
        self.assertEqual(list(core.completed_prefixes(rows, None)), [rows])
        self.assertEqual(list(core.completed_prefixes(rows, "103")), [])

    def test_real_engine_catchup_settles_target_and_continuation(self):
        # Boot at 18; one recovery response contains loss 19 and win 20.
        # Both 12-step results must settle, rather than calling 19 MISSED.
        boot = [{"issueNumber": str(20261002103010001 + i), "number": 8,
                 "blockTime": "2026-10-02 19:00:00"} for i in range(18)]
        recovered = [dict(boot[-1], issueNumber="20261002103010019", number=2),
                     dict(boot[-1], issueNumber="20261002103010020", number=8)]
        old_state = copy.deepcopy(core.STATE)
        with ExitStack() as stack:
            for name, value in {"last_issue": None, "pending": None, "strat_pending": None,
                                "unresolved_signal": None, "signal_history": [],
                                "strat_state": dict(core.strat_state, tier=0, step=0, signals=0,
                                                    wins=0, losses=0, busts=0, pending=None)}.items():
                stack.enter_context(patch.object(core, name, value))
            core.STATE.update(backtest=None, strat_log=[], log=[], equity=[])
            responses = [SimpleNamespace(status_code=200, json=lambda: boot),
                         SimpleNamespace(status_code=200, json=lambda: recovered)]
            stack.enter_context(patch.object(core.session, "get", side_effect=responses))
            stack.enter_context(patch.object(core.time, "sleep", side_effect=[None, SystemExit]))
            stack.enter_context(patch.object(core, "rsi_series", side_effect=lambda vals, *a: [31.0] * len(vals)))
            stack.enter_context(patch.object(core, "analyze_all_in_one", return_value={"signal": "SKIP", "score": 0}))
            for name in ("_send_previous_strat_daily_if_needed", "_strat_daily_event", "append_signal_history", "log_signal"):
                stack.enter_context(patch.object(core, name))
            stack.enter_context(patch.object(core, "run_backtest", return_value=None))
            stack.enter_context(patch.object(core, "feed_delay_seconds", return_value=0))
            stack.enter_context(patch.object(core, "_tg_queue", queue.Queue(maxsize=512)))
            try:
                with self.assertRaises(SystemExit):
                    core.engine_loop()
                events = [e["outcome"] for e in core.STATE["strat_log"]]
                self.assertIn("STEP-LOSS", events)
                self.assertIn("WIN", events)
                self.assertEqual(core.STATE["next_issue"], "20261002103010021")
                queued = [m[0] if isinstance(m,tuple) else m for m in core._tg_queue.queue]
                self.assertFalse(any("Target Issue: …010020" in m and "12-STEP SIGNAL" in m for m in queued))
            finally:
                core.STATE.clear()
                core.STATE.update(old_state)
                core._notification_context.historical = False


if __name__ == "__main__":
    unittest.main(verbosity=2)

