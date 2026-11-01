"""Standard-library regression tests; never downloads Kronos weights."""
import importlib.util
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("round_forecast", Path(__file__).parent / "research" / "kronos" / "forecast.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class RoundWalkTests(unittest.TestCase):
    def prediction(self, **changes):
        class Column(list):
            def tolist(self): return list(self)
        values={'open':[100.,101.],'high':[103.,104.], 'low':[99.,100.], 'close':[101.,102.]}
        values.update(changes)
        return {key:Column(value) for key,value in values.items()}

    def test_extracts_all_four_genuine_model_columns(self):
        values=module.extract_ohlc(self.prediction(),2)
        self.assertEqual(values,[{'open':100.,'high':103.,'low':99.,'close':101.},
                                 {'open':101.,'high':104.,'low':100.,'close':102.}])

    def test_model_wicks_are_not_repaired_or_derived_from_closes(self):
        values=module.extract_ohlc(self.prediction(high=[90.,91.]),2)
        self.assertEqual([v['high'] for v in values],[90.,91.])

    def test_rejects_nonfinite_or_incomplete_ohlc_output(self):
        for change in ({'low':[float('nan'),1.]},{'open':[1.]}, {'high':[float('inf'),2.]}):
            with self.subTest(change=change),self.assertRaisesRegex(ValueError,'OHLC'):
                module.extract_ohlc(self.prediction(**change),2)

    def test_existing_backtest_close_api_remains_compatible(self):
        values=module.extract_ohlc(self.prediction(),2)
        with patch.object(module,'predict_ohlc',return_value=(values,256)):
            self.assertEqual(module.predict_bars(None,[],1),([101.,102.],256))

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
        rows = self.samples(400)
        rows.reverse()
        rows.append(rows[0])
        bars, issue = module.walk_bars(rows, 5)
        self.assertEqual(len(bars), 80)
        self.assertEqual(issue, "100399")
        self.assertEqual(bars[0]["low"], 95)

    def test_truncates_to_frontend_10000_round_window(self):
        rows = self.samples(10150)
        bars, issue = module.walk_bars(rows, 1)
        self.assertEqual(len(bars), 10000)
        self.assertEqual(bars[0]["open"], 100)
        self.assertEqual(issue, rows[-1][0])

    def test_live_inference_rejects_missing_minutes_inside_aggregated_candle(self):
        rows = self.samples(400)
        del rows[-8]
        # A 5m candle still exists, but one of its source rounds is unknown.
        with self.assertRaisesRegex(ValueError, 'missing or duplicate minute'):
            module.walk_bars(rows, 5, require_contiguous=True)

    def test_old_gap_outside_model_input_does_not_block_fresh_inference(self):
        rows = self.samples(2000)
        del rows[1]
        bars, issue = module.walk_bars(rows, 5, require_contiguous=True)
        self.assertEqual(issue, rows[-1][0])

    def test_normal_second_jitter_does_not_create_a_missing_minute(self):
        rows = self.samples(400)
        for i, row in enumerate(rows):
            row[2] = row[2][:-2] + ('54' if i % 2 else '55')
        self.assertEqual(module.walk_bars(rows, 1, require_contiguous=True)[1], rows[-1][0])


if __name__ == "__main__":
    unittest.main()
