"""Notification-only cadence, compatibility and authenticated preview checks."""
import copy
import pytest
from admin_dashboard import AdminStore
from telegram_controls import TELEGRAM_DEFAULTS, validate_telegram, validate_streak, streak_should_alert
from tests_admin_dashboard import admin, login, headers


def test_default_streak_cadence_matches_existing_behavior():
    for side in ('BIG','SMALL'):
        assert [n for n in range(1,13) if streak_should_alert(TELEGRAM_DEFAULTS,side,n)] == list(range(8,13))
    assert not streak_should_alert(TELEGRAM_DEFAULTS,None,8)


def test_side_once_interval_and_delivery_switches():
    policy=copy.deepcopy(TELEGRAM_DEFAULTS)
    policy['streak'].update(start=6,repeat='interval',interval=2,side='BIG')
    assert [n for n in range(1,12) if streak_should_alert(policy,'BIG',n)] == [6,8,10]
    assert not any(streak_should_alert(policy,'SMALL',n) for n in range(1,12))
    policy['streak']['repeat']='once'
    assert [n for n in range(1,12) if streak_should_alert(policy,'BIG',n)] == [6]
    policy['types']['streak']=False
    assert not streak_should_alert(policy,'BIG',6)
    policy['types']['streak']=True;policy['engines']['market']=False
    assert not streak_should_alert(policy,'BIG',6)


@pytest.mark.parametrize('key,value',[('start',0),('start',101),('start',True),('start',8.5),('interval',0),('interval',101),('interval',False),('repeat','unknown'),('side','B')])
def test_invalid_streak_controls_rejected(key,value):
    cfg=copy.deepcopy(TELEGRAM_DEFAULTS['streak']);cfg[key]=value
    with pytest.raises(ValueError):validate_streak(cfg)


def test_legacy_policy_read_and_reopen_keep_existing_switches(tmp_path):
    legacy=copy.deepcopy(TELEGRAM_DEFAULTS);legacy.pop('streak');legacy['types']['streak']=False
    assert validate_telegram(legacy)['streak']==TELEGRAM_DEFAULTS['streak']
    store=AdminStore(tmp_path/'admin.sqlite3')
    import json
    with store.connect() as db:db.execute("UPDATE controls SET value=? WHERE name='telegram'",(json.dumps(legacy),))
    reopened=AdminStore(store.path)
    assert not reopened.control('telegram')['settings']['types']['streak']
    assert reopened.control('telegram')['settings']['streak']['start']==8
    assert reopened.control('telegram')['revision']==0


def test_policy_save_restart_legacy_client_and_preview_have_no_signal_side_effects(admin,monkeypatch):
    client,store,core,_=admin
    assert client.post('/api/admin/telegram/streak/preview',json={}).status_code==401
    login(client)
    policy=copy.deepcopy(TELEGRAM_DEFAULTS);policy['streak'].update(start=10,repeat='interval',interval=3,side='SMALL')
    before=copy.deepcopy(core.STATE)
    sent=[];monkeypatch.setattr(core,'tg_notify',lambda *a,**k:sent.append(a),raising=False)
    data={'revision':0,'settings':policy}
    assert client.put('/api/admin/telegram',json=data,headers=headers(client)).status_code==200
    assert AdminStore(store.path).control('telegram')['settings']==policy
    invalid=copy.deepcopy(policy);invalid['streak']['start']=0
    assert client.put('/api/admin/telegram',json={'revision':1,'settings':invalid},headers=headers(client)).status_code==400
    assert store.control('telegram')['revision']==1
    assert client.put('/api/admin/telegram',json=data,headers=headers(client)).status_code==409
    preview=client.post('/api/admin/telegram/streak/preview',json={'streak':policy['streak']},headers=headers(client))
    assert preview.status_code==200 and 'SMALL (S) × 10' in preview.json['text']
    assert not sent and core.STATE==before
    assert client.post('/api/admin/telegram/streak/preview',json={'streak':policy['streak']}).status_code==403
    legacy=copy.deepcopy(policy);legacy.pop('streak');legacy['quiet']['start']='23:00'
    assert client.put('/api/admin/telegram',json={'revision':1,'settings':legacy},headers=headers(client)).status_code==200
    assert store.control('telegram')['settings']['streak']==policy['streak']
