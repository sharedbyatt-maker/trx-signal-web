"""No real model output, network calls, application imports or orders."""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).parent/'research/kronos'))
import batch
import pipeline


class Timeframes(unittest.TestCase):
    def test_five_minute_output_preserved_when_only_one_minute_is_due(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);now=datetime.now(timezone.utc).isoformat()
            original=json.dumps({'forecasts':[{'timeframe':5,'generated_at_utc':now}]})
            (root/'index.json').write_text(original)
            (root/'backtest.json').write_text(json.dumps({'generated_at_utc':now,'timeframe':5}))
            (root/'backtest-1m.json').write_text(json.dumps({'generated_at_utc':now,'timeframe':1}))
            args=SimpleNamespace(output=folder,history_url='https://example.test',kronos_dir='/unused')
            frozen=[[1,9,'2026-01-01']]
            def publish(args,*,history_rows):
                self.assertIs(history_rows,frozen)
                pipeline.write_json(root/f'status-{args.timeframe}m.json',{'status':'ready','timeframe':args.timeframe})
            with patch.object(batch,'get_history',return_value=frozen) as feed,patch.object(batch,'publish',side_effect=publish) as model,patch.object(batch.subprocess,'run') as historical:
                batch.run(args)
            feed.assert_called_once();self.assertEqual([call.args[0].timeframe for call in model.call_args_list],[1])
            historical.assert_not_called();self.assertEqual((root/'index.json').read_text(),original)
    def test_first_run_generates_both_timeframes_with_independent_statuses(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);args=SimpleNamespace(output=folder,history_url='https://example.test',kronos_dir='/unused')
            events=[];feeds={5:[[5]],1:[[1]]}
            def publish(args,*,history_rows):
                events.append(args.timeframe)
                self.assertIs(history_rows,feeds[args.timeframe])
                pipeline.write_json(root/f'status-{args.timeframe}m.json',{'status':'ready','timeframe':args.timeframe})
            with patch.object(batch,'get_history',side_effect=[feeds[5],feeds[1]]),patch.object(batch,'publish',side_effect=publish) as model,patch.object(batch.subprocess,'run',side_effect=lambda *args,**kwargs:events.append('backtest')) as historical:
                batch.run(args)
            self.assertEqual([call.args[0].timeframe for call in model.call_args_list],[5,1])
            self.assertEqual([call.args[0][-1] for call in historical.call_args_list],[str(root/'backtest-1m.json'),str(root/'backtest.json')])
            self.assertEqual(events,[5,'backtest','backtest',1])
            self.assertEqual(set(json.loads((root/'status.json').read_text())['timeframes']),{'1','5'})
    def test_one_timeframe_failure_does_not_erase_the_other(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);args=SimpleNamespace(output=folder,history_url='https://example.test',kronos_dir='/unused')
            def publish(args,*,history_rows):
                failed=args.timeframe==1
                pipeline.write_json(root/f'status-{args.timeframe}m.json',{'status':'failed' if failed else 'ready'})
                if failed:raise ValueError('1m unavailable')
            with patch.object(batch,'get_history',return_value=[]),patch.object(batch,'publish',side_effect=publish),patch.object(batch.subprocess,'run'):
                with self.assertRaisesRegex(RuntimeError,'1m unavailable'):batch.run(args)
            state=json.loads((root/'status.json').read_text())
            self.assertEqual(state['timeframes']['5']['status'],'ready')
            self.assertEqual(state['timeframes']['1']['status'],'failed')
    def test_frozen_feed_failure_is_reported_without_forecasts(self):
        with tempfile.TemporaryDirectory() as folder:
            args=SimpleNamespace(output=folder,history_url='https://example.test',kronos_dir='/unused')
            with patch.object(batch,'get_history',side_effect=ValueError('feed unavailable')),patch.object(batch,'publish') as model:
                with self.assertRaises(RuntimeError):batch.run(args)
            model.assert_not_called()
            for tf in (1,5):self.assertEqual(json.loads((Path(folder)/f'status-{tf}m.json').read_text())['status'],'failed')
    def test_fast_archive_does_not_evict_existing_five_minute_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);(root/'forecasts').mkdir()
            original='{"immutable":"existing 5m forecast"}'
            (root/'forecasts/old-5.json').write_text(original)
            entries=[{'file':f'forecasts/old-{i}-1.json','timeframe':1,'origin_issue':str(i),'generated_at_utc':'2026-01-01T00:00:00Z'} for i in range(720)]
            entries.append({'file':'forecasts/old-5.json','timeframe':5,'origin_issue':'old5','generated_at_utc':'2026-01-01T00:00:00Z'})
            pipeline.write_json(root/'index.json',{'schema':'kronos-index-v1','forecasts':entries})
            now=datetime.now(timezone.utc)
            rows=[[str(100000+i),i%10,(now-timedelta(minutes=399-i)).isoformat()] for i in range(400)]
            def model(command,**kwargs):
                pipeline.write_json(Path(command[-1]),{'origin_issue':rows[-1][0],'generated_at_utc':now.isoformat()})
            args=SimpleNamespace(output=folder,timeframe=1,history_url='https://example.test',kronos_dir='/unused')
            with patch.object(pipeline.subprocess,'run',side_effect=model):pipeline.run(args,history_rows=rows)
            manifest=json.loads((root/'index.json').read_text())
            self.assertEqual(sum(entry['timeframe']==1 for entry in manifest['forecasts']),720)
            self.assertEqual(sum(entry['timeframe']==5 for entry in manifest['forecasts']),1)
            self.assertEqual((root/'forecasts/old-5.json').read_text(),original)


if __name__=='__main__':unittest.main()
