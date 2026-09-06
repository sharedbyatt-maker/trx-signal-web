import os
import tempfile
from pathlib import Path
import app_core as c


def test_daily_ledger_and_dedupe():
    with tempfile.TemporaryDirectory() as td:
        old=c.STRAT_DAILY_FILE
        try:
            c.STRAT_DAILY_FILE=str(Path(td)/'daily.json')
            c.strat_daily_reports={}
            day='2026-09-06'
            assert c._strat_daily_event(day,'signal:1',signals=1,max_stake=200,max_tier=1,max_step=1,last_issue='1')
            assert not c._strat_daily_event(day,'signal:1',signals=1)
            assert c._strat_daily_event(day,'bet:1',settled_bets=1,bet_wins=1,total_staked=200,total_returned=392,net_pnl=192,max_stake=200,max_tier=1,max_step=1,last_issue='1')
            r,_=c._strat_daily_snapshot(day,7)
            assert r['signals']==1 and r['settled_bets']==1 and r['bet_wins']==1
            assert r['total_staked']==200 and r['total_returned']==392 and r['net_pnl']==192
            assert r['bet_win_rate']==100.0
            assert r['roi_pct']==96.0 and r['avg_stake']==200
            assert r['break_even_win_rate']==round(100.0/c.STAKE_PAYOUT,2)
            assert os.path.exists(c.STRAT_DAILY_FILE)
        finally:
            c.STRAT_DAILY_FILE=old


def test_daily_formatter():
    r=c._empty_strat_daily('2026-09-06')
    r.update({'signals':3,'settled_bets':4,'bet_wins':3,'bet_losses':1,'bet_win_rate':75.0,'net_pnl':584,'total_staked':800,'total_returned':1384,'max_stake':400,'max_tier':1,'max_step':2})
    msg=c.format_strat_daily_telegram(r)
    assert '[12-STEP ENGINE]' in msg and 'DAILY REPORT' in msg and 'NET P/L: +584 MMK' in msg
    assert 'ROI on Staked:' in msg and 'Break-even WR @ 1.96x:' in msg


def test_daily_api_smoke():
    client=c.app.test_client()
    resp=client.get('/api/12step/daily-report?days=7')
    assert resp.status_code==200
    data=resp.get_json()
    assert 'report' in data and 'history' in data and 'engine' in data['report']
    assert 'roi_pct' in data['report'] and 'next_eligible_stake' in data['report']['engine']


if __name__=='__main__':
    test_daily_ledger_and_dedupe(); test_daily_formatter(); test_daily_api_smoke()
    print('DAILY12 TESTS: ALL PASSED')
