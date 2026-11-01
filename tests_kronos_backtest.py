"""Synthetic fixtures verify isolation, never model quality or published results."""
import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0,str(Path(__file__).parent/'research/kronos'))
import backtest


class WalkForward(unittest.TestCase):
    def setUp(self):
        self.start=datetime(2026,1,1,tzinfo=timezone.utc)
        self.rows=[[str(100000+i),9,(self.start+timedelta(minutes=i)).isoformat()] for i in range(400)]
        self.now=self.start+timedelta(minutes=401)
        self.inputs=[]
    def infer(self,bars,tf):
        self.inputs.append([dict(bar) for bar in bars])
        return [bars[-1]['close']]*12
    def run_one(self,rows=None):
        return backtest.run(rows or self.rows,self.infer,now=self.now,timeframe=1,max_origins=1,lookback=128)
    def test_known_horizon_errors_and_retrospective_identity(self):
        result=self.run_one()
        self.assertEqual([p['error'] for p in result['horizons']],[1,3,6,12])
        self.assertEqual([p['majority'] for p in result['horizons']],[0]*4)
        self.assertTrue(result['retrospective_only'])
        self.assertEqual(len(result['origins']),1)
    def test_future_outcomes_cannot_enter_model_input(self):
        original=self.run_one();first=self.inputs[-1]
        changed=[row[:] for row in self.rows]
        for row in changed[388:]:row[1]=0
        second=self.run_one(changed)
        self.assertEqual(first,self.inputs[-1])
        self.assertEqual(original['origins'],second['origins'])
        self.assertEqual(len(first),128)
        self.assertEqual(first[-1]['time'].isoformat(),'2026-01-01T12:57:00')
    def test_missing_target_minute_excludes_origin(self):
        changed=[row[:] for row in self.rows];changed.pop(390)
        result=self.run_one(changed)
        self.assertEqual(result['origins'],[])
    def test_missing_context_minute_never_reaches_model(self):
        changed=[row[:] for row in self.rows];changed.pop(300)
        self.run_one(changed)
        self.assertEqual(self.inputs,[])
    def test_nonoverlapping_windows_and_bound(self):
        result=backtest.run(self.rows,self.infer,now=self.now,timeframe=1,max_origins=8,lookback=128)
        self.assertEqual(len(result['origins']),8)
        for first,second in zip(result['origins'],result['origins'][1:]):
            self.assertLessEqual(first['last_target_end_utc'],second['input_end_utc'])
        with self.assertRaises(ValueError):backtest.run(self.rows,self.infer,max_origins=9)
    def test_empty_history_and_conflicts(self):
        result=backtest.run([],self.infer,now=self.now)
        self.assertEqual(result['origins'],[])
        self.assertEqual(self.inputs,[])
        with self.assertRaises(ValueError):self.run_one(self.rows+[[self.rows[-1][0],0,self.rows[-1][2]]])


if __name__=='__main__':unittest.main()
