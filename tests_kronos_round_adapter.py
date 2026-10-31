"""Standard-library regression tests; never downloads Kronos weights."""
import importlib.util
import unittest
from datetime import datetime, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location("round_forecast", Path(__file__).parent / "research" / "kronos" / "forecast.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RoundWalkTests(unittest.TestCase):
    def samples(self, count=150):
        origin = datetime(2026, 1, 1, 0, 0)
        return [[str(100000 + n), n % 10, (origin + timedelta(minutes=n)).strftime("%Y-%m-%d %H:%M:%S")] for n in range(count)]

    def test_m1_preserves_walk_and_round_origin(self):
        rows = self.samples(150)
        bars, issue = module.walk_bars(rows, 1)
        self.assertEqual(issue, rows[-1][0])
        self.assertEqual(len(bars), 150)
        self.assertEqual(bars[0]["open"], 100)
        self.assertEqual(bars[0]["close"], 99)
        self.assertEqual(bars[-1]["close"], 100)

    def test_bucket_dedup_and_unsorted_issues(self):
        rows = self.samples(150)
        rows.reverse()
        rows.append(rows[0])
        bars, issue = module.walk_bars(rows, 5)
        self.assertEqual(len(bars), 30)
        self.assertEqual(issue, "100149")
        self.assertEqual(bars[0]["low"], 95)

    def test_truncates_to_frontend_10000_round_window(self):
        rows = self.samples(10150)
        bars, issue = module.walk_bars(rows, 1)
        self.assertEqual(len(bars), 10000)
        self.assertEqual(bars[0]["open"], 100)
        self.assertEqual(issue, rows[-1][0])


if __name__ == "__main__":
    unittest.main()
