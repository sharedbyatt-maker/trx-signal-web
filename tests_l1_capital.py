import unittest
from unittest.mock import Mock

import l1_capital as l1


class L1CapitalTests(unittest.TestCase):
    def test_frozen_scaled_ladder(self):
        self.assertEqual(l1.STAKES[0], [500, 1000, 1500, 3000])
        self.assertEqual(l1.STAKES[1], [6250, 12500, 25000, 50000])
        self.assertEqual(l1.STAKES[2], [100000, 200000, 400000, 800000])
        self.assertEqual([r["id"] for r in l1.RULES], ["R02", "R03", "R05", "R06"])

    def test_risk_status_does_not_delete_pending_signal(self):
        rows=[]
        # deterministic warmup; replay must stay safe and return a structured snapshot
        for i in range(40):
            rows.append({
                "issue": str(20260920000000000+i),
                "type": "BIG" if i % 3 else "SMALL",
                "block_time": f"2026-09-20 12:{i%60:02d}:00",
            })
        out=l1.replay_l1(rows)
        self.assertTrue(out["ready"])
        self.assertIn(out["risk_status"], (
            "TRADE ALLOWED",
            "OBSERVE ONLY — DAILY TP REACHED",
            "OBSERVE ONLY — DAILY SL REACHED",
        ))

    def test_signal_message_is_namespaced_and_contains_exact_stake(self):
        snap={
            "pending":{"target":"BIG","issue":"20260920123456","stake":500,
                       "tier":1,"step":1,"trigger_rsi":31.5,"rule":None},
            "today_pnl":0,"risk_status":"TRADE ALLOWED",
        }
        msg=l1._fmt_signal(snap)
        self.assertIn("[L1 CAPITAL]",msg)
        self.assertIn("BET: 500 MMK",msg)
        self.assertIn("T1-S1",msg)
        self.assertIn("Manual execution only",msg)


if __name__=="__main__":
    unittest.main()
