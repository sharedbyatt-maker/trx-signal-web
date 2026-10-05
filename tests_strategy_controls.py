"""Causal money settings, frozen rules and private delivery controls."""
import copy
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo
import pytest
from admin_dashboard import AdminStore
from strategy_settings import MONEY_DEFAULTS, MoneySchedule, validate_money, ladder, risk_status
from telegram_controls import TELEGRAM_DEFAULTS, allowed, classify
from tests_admin_dashboard import admin, login, headers
from tests_l1_capital import make_rows, FakeCore
import l1_capital as l1


def test_defaults_match_both_frozen_ladders():
    from core_config import STAKE_TIERS
    assert ladder(MONEY_DEFAULTS['l1'])==l1.STAKES
    assert ladder(MONEY_DEFAULTS['twelve'])==STAKE_TIERS
    for name in MONEY_DEFAULTS:assert validate_money(name,MONEY_DEFAULTS[name])==MONEY_DEFAULTS[name]


def test_strategy_api_frozen_rules_revision_boundary_and_pending(admin):
    client,store,core,_=admin
    login(client)
    core.STATE.update(connected=True,history=[{'issue':'100'}],strat_pending={'issue':'101','stake':200})
    core.last_issue='100'
    core._money_processing_issue='102' # engine already processing a newer source
    before=copy.deepcopy(core.STATE['strat_pending'])
    data=client.get('/api/admin/strategies/twelve').json
    assert data['defaults']['base']==200 and data['info']['rules']
    value=copy.deepcopy(data['settings']);value['base']=300
    saved=client.put('/api/admin/strategies/twelve',json={'revision':0,'settings':value},headers=headers(client))
    assert saved.status_code==200
    assert core.STATE['strat_pending']==before
    schedule=MoneySchedule('twelve',store.money_history('twelve'))
    assert schedule.at(102)['base']==200 and schedule.at(103)['base']==300
    assert client.put('/api/admin/strategies/twelve',json={'revision':0,'settings':value},headers=headers(client)).status_code==409
    value['rsi_low']=30
    assert client.put('/api/admin/strategies/twelve',json={'revision':1,'settings':value},headers=headers(client)).status_code==400
    assert AdminStore(store.path).control('twelve')['settings']['base']==300


def test_l1_money_change_does_not_reprice_prior_trade_and_pending():
    outcomes=['SMALL']*17;outcomes[15]='BIG'
    rows=make_rows(17,outcomes);rsi=[50.0]*17;rsi[14]=31
    money=copy.deepcopy(MONEY_DEFAULTS['l1']);money['base']=1000
    change={'after_issue':int(rows[15]['issue']),'settings':money}
    with patch.object(l1,'_rsi',return_value=rsi):
        old=l1.replay_l1(rows)
        new=l1.replay_l1(rows,[change])
    assert old['trades']==new['trades'] and new['trades'][-1]['stake']==500
    assert new['pending']['stake']==2000 # continuation source after boundary
    # A save at current source leaves the already armed continuation untouched.
    change['after_issue']=int(rows[-1]['issue'])
    with patch.object(l1,'_rsi',return_value=rsi):
        fixed=l1.replay_l1(rows,[change],current_money=money)
    assert fixed['pending']['stake']==1000
    assert fixed['money_settings']['base']==1000
    assert fixed['daily_summary']==old['daily_summary']


def test_l1_issued_ledger_guards_replay_after_restore(tmp_path):
    outcomes=['SMALL']*17;outcomes[15]='BIG'
    rows=make_rows(17,outcomes);rsi=[50.0]*17;rsi[14]=31
    money=copy.deepcopy(MONEY_DEFAULTS['l1']);money['base']=1000
    store=AdminStore(tmp_path/'admin.sqlite3')
    store.lock_stake(rows[-1]['issue'],500)
    store.save_control('l1',money,0,int(rows[14]['issue']))
    with patch.object(l1,'_rsi',return_value=rsi):
        snap=l1.replay_l1(rows,store.money_history('l1'),store.issued)
    assert snap['trades'][-1]['stake']==500 and snap['trades'][-1]['pnl']==-500
    assert store.lock_stake(rows[-1]['issue'],1000)==500
    assert AdminStore(store.path).issued[str(rows[-1]['issue'])]==500


def test_money_validation_and_risk_limits():
    for bad in (float('nan'),0,True,10001):
        money=copy.deepcopy(MONEY_DEFAULTS['l1']);money['multipliers'][0][1]=bad
        with pytest.raises(ValueError):validate_money('l1',money)
    money=copy.deepcopy(MONEY_DEFAULTS['twelve'])
    assert risk_status(money,500000)=='TRADE ALLOWED' # original TP disabled
    money.update(tp=1000,sl=2000)
    assert 'TP REACHED' in risk_status(money,1000)
    assert 'SL REACHED' in risk_status(money,-2000)
    money.update(tp=0,sl=0)
    assert 'STAKE EXCEEDS' in risk_status(money,0,50001)


def test_telegram_policy_quiet_hours_and_engine_dispatch(monkeypatch,tmp_path):
    import app_core as core
    import queue
    store=AdminStore(tmp_path/'admin.sqlite3')
    policy=copy.deepcopy(TELEGRAM_DEFAULTS);policy['engines']['l1']=False
    store.save_control('telegram',policy,0)
    q=queue.Queue();sent=[]
    monkeypatch.setattr(core,'_admin_store',store,raising=False)
    monkeypatch.setattr(core,'_tg_queue',q)
    monkeypatch.setattr(core,'load_tg_config',lambda:('fixture','fixture'))
    monkeypatch.setattr(core,'_send_telegram',lambda text,cfg:sent.append(text) or 'sent')
    assert core.tg_notify('🟦 [L1 CAPITAL] — SIGNAL') and q.empty()
    q.put(('queued before switch','l1','signal'));q.put(None)
    core._tg_worker();assert not sent
    policy['quiet'].update(enabled=True,start='22:00',end='07:00')
    for hour in (23,0,6):assert not allowed(policy,'twelve','signal',datetime(2026,10,5,hour,0,tzinfo=ZoneInfo('Asia/Bangkok')))
    assert allowed(policy,'twelve','signal',datetime(2026,10,5,7,0,tzinfo=ZoneInfo('Asia/Bangkok')))


def test_credentials_private_encrypted_and_excluded_from_backup(admin):
    client,store,core,_=admin;login(client)
    token='123456:abcdefghijklmnopqrstuvwxyz123456'
    assert client.put('/api/admin/telegram/credentials',json={'token':token,'chat':'-10012345678'},headers=headers(client)).status_code==200
    assert token not in store.vault.path.read_text()
    assert token not in client.get('/api/admin/telegram').text
    assert token not in client.get('/api/admin/backup').text
    assert token not in str(store.events())
    assert store.credential_override()['token']==token
    assert client.delete('/api/admin/telegram/credentials',headers=headers(client)).status_code==200
    assert store.credential_override() is None


def test_backup_round_trip_causal_controls_and_invalid_atomicity(admin,tmp_path):
    client,store,core,_=admin;login(client)
    core.STATE.update(connected=True,history=[{'issue':'100'}])
    money=copy.deepcopy(MONEY_DEFAULTS['l1']);money['base']=700
    store.save_control('l1',money,0,100);store.lock_stake('101',500)
    backup=client.get('/api/admin/backup').json
    bad=copy.deepcopy(backup);bad['expected_revision']=0;bad['controls']['l1']['settings']['rsi']=30
    assert client.post('/api/admin/restore',json=bad,headers=headers(client)).status_code==400
    assert store.cached['revision']==0 and store.control('l1')['revision']==1
    # Active restore applies money after the current source and keeps issued stakes.
    core.STATE['history']=[{'issue':'200'}]
    backup['expected_revision']=0
    assert client.post('/api/admin/restore',json=backup,headers=headers(client)).status_code==200
    assert store.money_history('l1')[-1]['after_issue']==200
    assert store.issued['101']==500


def test_real_twelve_engine_settles_old_stake_and_arms_new_ladder(monkeypatch,tmp_path):
    import app_core as core
    import queue
    boot=[{'issueNumber':str(20261002103010001+i),'number':8,'blockTime':'2026-10-02 19:00:00'} for i in range(18)]
    recovered=[dict(boot[-1],issueNumber='20261002103010019',number=2),dict(boot[-1],issueNumber='20261002103010020',number=8)]
    store=AdminStore(tmp_path/'admin.sqlite3')
    monkeypatch.setattr(core,'_admin_store',store,raising=False)
    monkeypatch.setattr(core,'STATE',copy.deepcopy(core.STATE))
    core.STATE.update(backtest=None,strat_log=[],log=[],equity=[])
    for name,value in {'last_issue':None,'pending':None,'strat_pending':None,'unresolved_signal':None,'signal_history':[],
                        'strat_state':dict(core.strat_state,tier=0,step=0,signals=0,wins=0,losses=0,busts=0,pending=None)}.items():
        monkeypatch.setattr(core,name,value)
    responses=iter([SimpleNamespace(status_code=200,json=lambda:boot),SimpleNamespace(status_code=200,json=lambda:recovered)])
    monkeypatch.setattr(core.session,'get',lambda *a,**k:next(responses))
    sleeps=[]
    def sleep(_):
        if sleeps:raise SystemExit()
        assert core.strat_pending['stake']==200
        value=copy.deepcopy(MONEY_DEFAULTS['twelve']);value['base']=300
        store.save_control('twelve',value,0,int(boot[-1]['issueNumber']))
        assert core.strat_pending['stake']==200
        sleeps.append(True)
    monkeypatch.setattr(core.time,'sleep',sleep)
    monkeypatch.setattr(core,'rsi_series',lambda vals,*a:[31.0]*len(vals))
    monkeypatch.setattr(core,'analyze_all_in_one',lambda *a,**k:{'signal':'SKIP','score':0})
    events=[]
    monkeypatch.setattr(core,'_strat_daily_event',lambda *a,**k:events.append(k))
    for name in ('_send_previous_strat_daily_if_needed','append_signal_history','log_signal'):
        monkeypatch.setattr(core,name,lambda *a,**k:None)
    monkeypatch.setattr(core,'run_backtest',lambda *a,**k:None)
    monkeypatch.setattr(core,'feed_delay_seconds',lambda *a,**k:0)
    monkeypatch.setattr(core,'_tg_queue',queue.Queue(maxsize=512))
    try:
        with pytest.raises(SystemExit):core.engine_loop()
        settlements=[e for e in events if e.get('settled_bets')]
        assert [e['total_staked'] for e in settlements]==[200,600]
        assert [e['net_pnl'] for e in settlements]==[-200,576]
        assert core.strat_pending['stake']==300 # winning cycle reset
    finally:core._notification_context.historical=False



def test_backup_budget_reserves_space_for_monetary_history(admin):
    client,store,_,_=admin;login(client)
    with store.connect() as db:
        db.executemany('INSERT INTO issued_stakes VALUES(?,?)',[(str(20261001000000000+i),500) for i in range(12000)])
    store.refresh_controls()
    for _ in range(80):store.event('fixture',{'large':'x'*12000})
    result=client.get('/api/admin/backup')
    assert len(result.data)<1024*1024
    assert len(result.json['issued_stakes'])==12000
    assert result.json['events_truncated'] is True



def test_changed_withdrawal_threshold_notifies_next_actual_milestone():
    core=FakeCore(make_rows(18));service=l1.L1CapitalService(core,state_file='')
    snap={'ready':True,'pending':None,'today_pnl':0,'withdraw_milestone':50000,'withdraw_milestones_reached':1}
    with patch.object(l1,'replay_l1',return_value=snap):service.refresh_once()
    assert '50,000' in core.messages[-1]
    core.messages.clear()
    snap.update(withdraw_milestone=100000,withdraw_milestones_reached=0)
    with patch.object(l1,'replay_l1',return_value=snap):service.refresh_once()
    assert not core.messages # settings changes do not send retrospective milestones
    snap['withdraw_milestones_reached']=1
    with patch.object(l1,'replay_l1',return_value=snap):service.refresh_once()
    assert len(core.messages)==1 and '100,000' in core.messages[0]



def test_large_source_issue_survives_browser_backup_and_fresh_restore(admin,tmp_path):
    client,store,core,_=admin;login(client)
    issue=20261005103010409 # larger than JavaScript's exact Number range
    money=copy.deepcopy(MONEY_DEFAULTS['l1']);money['base']=600
    store.save_control('l1',money,0,issue)
    backup=client.get('/api/admin/backup').json
    assert backup['money_changes']['l1'][0]['after_issue']==str(issue)
    # Strings preserve every digit through JSON.parse / JSON.stringify in the UI.
    fresh,restored,_,_=globals()['admin'].__wrapped__(tmp_path/'fresh')
    login(fresh);backup['expected_revision']=0
    assert fresh.post('/api/admin/restore',json=backup,headers=headers(fresh)).status_code==200
    assert restored.money_history('l1')[0]['after_issue']==issue
    schedule=MoneySchedule('l1',restored.money_history('l1'))
    assert schedule.at(issue)['base']==500 and schedule.at(issue+1)['base']==600
