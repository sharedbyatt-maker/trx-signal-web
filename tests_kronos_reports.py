import importlib.util
import json
import tempfile
import unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path

spec=importlib.util.spec_from_file_location('kronos_reports',Path(__file__).parent/'research/kronos/reports.py')
reports=importlib.util.module_from_spec(spec);spec.loader.exec_module(reports)

class Reports(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,1,1,tzinfo=timezone.utc)
        self.rows=[[str(100000+i),i%10,(self.start+timedelta(minutes=i)).isoformat()] for i in range(160)]
        origin=128
        local=(self.start+timedelta(minutes=origin)).astimezone(reports.SOURCE).replace(tzinfo=None)
        self.snapshot={'schema':'kronos-round-snapshot-v1','data_source':'big-small-walk','source':'official-kronos-inference-cpu','timeframe_minutes':1,'source_timezone':'Asia/Yangon','research_only':True,'model':'Kronos-mini','lookback_bars':64,'origin_issue':self.rows[origin][0],'origin_bar_time_local':local.isoformat(),'generated_at_utc':(self.start+timedelta(minutes=origin,seconds=1)).isoformat(),'forecast_delta':[-1,1]}
        self.now=self.start+timedelta(minutes=161)
    def test_causal_completed_targets_and_known_error(self):
        points=reports.evaluate(self.snapshot,self.rows,'forecasts/a.json',self.now)
        self.assertEqual([p['error'] for p in points],[2,1])
        self.assertEqual(reports.random_error(2,0),1)
    def test_started_and_incomplete_targets_not_scored(self):
        self.snapshot['generated_at_utc']=(self.start+timedelta(minutes=129,seconds=1)).isoformat()
        points=reports.evaluate(self.snapshot,self.rows,'forecasts/a.json',self.now)
        self.assertEqual(len(points),1)
        self.assertTrue(points[0]['id'].endswith(':1'))
        self.assertEqual(reports.evaluate(self.snapshot,self.rows,'a',self.start+timedelta(minutes=130)),[])
    def test_missing_source_round_not_scored(self):
        points=reports.evaluate(self.snapshot,self.rows[:130]+self.rows[131:],'a',self.now)
        self.assertEqual(len(points),1)
    def test_measured_records_immutable_and_daily_totals(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'forecasts').mkdir();file=root/'forecasts/a.json'
            original=json.dumps(self.snapshot);file.write_text(original)
            manifest={'forecasts':[{'file':'forecasts/a.json'}]}
            ledger,summary=reports.build(root,manifest,self.rows,{'points':[]},self.now)
            self.assertEqual(summary['days'][0]['targets'],2)
            self.assertEqual(summary['days'][0]['error'],3)
            changed=[r[:] for r in self.rows];changed[129][1]=0
            second,_=reports.build(root,manifest,changed,ledger,self.now)
            self.assertEqual(second,ledger)
            self.assertEqual(file.read_text(),original)
            old,_=reports.build(root,manifest,[],ledger,self.now+timedelta(days=31))
            self.assertEqual(old['points'],[])
    def test_origin_after_generation_is_rejected(self):
        self.snapshot['generated_at_utc']=self.start.isoformat()
        with self.assertRaises(ValueError):reports.evaluate(self.snapshot,self.rows,'a',self.now)

if __name__=='__main__':unittest.main()
