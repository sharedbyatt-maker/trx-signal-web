"""Kronos-only data safety tests; no engines, downloads or orders."""
import importlib.util
import sys
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).parent / 'research' / 'kronos'
spec = importlib.util.spec_from_file_location('kronos_adapter', ROOT / 'forecast.py')
forecast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(forecast)
sys.path.insert(0, str(ROOT))
import pipeline


def rows():
    start = datetime(2026, 1, 1)
    return [[str(100000+i), i % 10, (start+timedelta(minutes=i)).isoformat()] for i in range(400)]


class Safety(unittest.TestCase):
    def test_conflicting_duplicate_is_rejected(self):
        data = rows()
        data.append([data[-1][0], 8, data[-1][2]])
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            forecast.walk_bars(data, 5)

    def test_timestamp_reversal_is_rejected(self):
        data = rows()
        data[-1][2] = data[0][2]
        with self.assertRaisesRegex(ValueError, 'increase'):
            forecast.walk_bars(data, 5)

    def test_offset_input_matches_source_local(self):
        data = rows()
        offset = [[i,n,t+'+06:30'] for i,n,t in data]
        self.assertEqual(forecast.walk_bars(data,5), forecast.walk_bars(offset,5))

    def test_fractional_digits_are_not_coerced(self):
        data = rows()
        data[-1][1] = 5.9
        self.assertEqual(forecast.walk_bars(data,1)[1], data[-2][0])

    def test_stale_feed_preserves_last_good_forecast(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'index.json').write_text('{"unchanged":true}')
            args = SimpleNamespace(output=directory,history_url='https://example.test',timeframe=5,kronos_dir='/unused')
            with patch.object(pipeline,'get_history',return_value=rows()), patch.object(pipeline.subprocess,'run') as model:
                with self.assertRaisesRegex(ValueError, 'stale'):
                    pipeline.run(args)
            model.assert_not_called()
            self.assertEqual((root/'index.json').read_text(),'{"unchanged":true}')
            self.assertIn('failed',(root/'status.json').read_text())
            self.assertFalse((root/'input.json').exists())


if __name__ == '__main__':
    unittest.main()
