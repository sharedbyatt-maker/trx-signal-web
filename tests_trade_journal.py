import copy
from datetime import datetime, timezone

import pytest
from tests_admin_dashboard import admin, login, headers
from trade_journal import normalize, merge, snapshot, export_rows


def row(**changes):
    return {'addTime':'2026-10-10 00:15:00','issueNumber':'20261010103010001',
            'selectType':'big','amount':100,'profitAmount':198,'state':1,'number':8,**changes}


def value(rows, **cfg):
    return {'limits':{'tp':100,'sl':100,'timezone':'Asia/Bangkok',**cfg},'rows':rows}


def test_day_boundary_pending_and_real_demo_are_separate():
    rows=normalize([row(orderId='w'),row(orderId='l',state=0),row(orderId='p',state=-1)],'real','Asia/Yangon')
    rows+=normalize([row(orderId='demo')],'demo','Asia/Yangon')
    snap=snapshot(value(rows),1,now=datetime(2026,10,9,18,tzinfo=timezone.utc))
    assert snap['today']=='2026-10-10'
    assert snap['summary']=={'pnl':-2.0,'staked':300.0,'trades':3,'wins':1,'losses':1,'pending':1,'status':'within_limits'}
    assert snapshot(value(rows,timezone='UTC'),1,'real','2026-10-09')['summary']['trades']==3
    assert snapshot(value(rows),1,'demo','2026-10-10')['summary']['pnl']==98
    assert snapshot(value(rows),1,'real','2026-10-09')['summary']['trades']==0


def test_idempotence_settlement_conflicts_and_export_round_trip():
    pending=normalize([row(orderId='x',state=-1)],'real','Asia/Yangon')
    settled=normalize([row(orderId='x')],'real','Asia/Yangon')
    merged,counts=merge(pending,settled)
    assert counts=={'added':0,'updated':1,'unchanged':0}
    assert merge(merged,pending)[1]['unchanged']==1
    assert merge(merged,settled)[1]['unchanged']==1
    with pytest.raises(ValueError,match='conflicts'):
        merge(merged,normalize([row(orderId='x',state=0)],'real','Asia/Yangon'))
    assert normalize(export_rows(value(merged),'real'),'real','UTC')==merged
    fallback=normalize([row()],'real','Asia/Yangon')
    assert normalize(export_rows(value(fallback),'real'),'real','UTC')==fallback
    with pytest.raises(ValueError,match='Duplicate'):
        normalize([row(),row()],'real','UTC')
    assert len(normalize([row(orderId='a'),row(orderId='b')],'real','UTC'))==2


@pytest.mark.parametrize('change',[{'addTime':'00:15:00'},{'issueNumber':'100001'},{'amount':True},{'amount':'NaN'},{'amount':'1.001'},{'profitAmount':None},{'state':True},{'state':2},{'selectType':'other'},{'number':False}])
def test_invalid_records_rejected(change):
    with pytest.raises(ValueError):normalize([row(**change)],'real','UTC')


@pytest.mark.parametrize('cfg,pnl,status',[({'tp':98},98,'tp_reached'),({'sl':100},-100,'sl_reached'),({'tp':0,'sl':0},98,'limits_disabled')])
def test_target_status(cfg,pnl,status):
    state=1 if pnl>0 else 0
    rows=normalize([row(state=state)],'real','Asia/Yangon')
    assert snapshot(value(rows,**cfg),1,'real','2026-10-10')['summary']['status']==status


def test_private_routes_revision_encryption_atomic_import_and_backup(admin):
    client,store,_,_=admin
    for path in ('trade-journal','trade-journal/export'):
        assert client.get('/api/admin/'+path).status_code==401
    assert client.post('/api/admin/trade-journal/import',json={}).status_code==401
    login(client)
    assert client.put('/api/admin/trade-journal',json={}).status_code==403
    base=client.get('/api/admin/trade-journal').json
    assert base['revision']==0 and base['stored_records']==0
    targets={'tp':50,'sl':100,'timezone':'Asia/Yangon'}
    body={'revision':0,'limits':targets}
    assert client.put('/api/admin/trade-journal?date=invalid',json=body,headers=headers(client)).status_code==400
    assert store.private_get('trade_journal')['revision']==0
    assert client.put('/api/admin/trade-journal',json=body,headers=headers(client)).json['revision']==1
    assert client.put('/api/admin/trade-journal',json=body,headers=headers(client)).status_code==409
    batch={'revision':1,'mode':'real','source_timezone':'Asia/Yangon','history':{'success':True,'list':[row(orderId='synthetic-order',token='DO-NOT-STORE')]}}
    response=client.post('/api/admin/trade-journal/import',json=batch,headers=headers(client))
    assert response.status_code==200 and response.json['import_result']['added']==1
    assert 'no-store' in response.headers['Cache-Control']
    encrypted=store.private_get('trade_journal')['value']
    assert 'synthetic-order' not in encrypted and 'DO-NOT-STORE' not in encrypted
    decrypted=store.vault.cipher.decrypt(encrypted.encode()).decode()
    assert 'synthetic-order' in decrypted and 'DO-NOT-STORE' not in decrypted
    assert 'synthetic-order' not in client.get('/api/admin/backup').text
    batch['revision']=2
    batch['history']['list']=[row(orderId='new'),row(orderId='synthetic-order',state=0)]
    assert client.post('/api/admin/trade-journal/import',json=batch,headers=headers(client)).status_code==400
    assert store.private_get('trade_journal')['revision']==2
    assert client.get('/api/admin/trade-journal?date=2026-10-10').json['summary']['pnl']==98
    exported=client.get('/api/admin/trade-journal/export?mode=real').json
    assert len(exported['list'])==1
    batch['history']=exported
    assert client.post('/api/admin/trade-journal/import',json=batch,headers=headers(client)).json['import_result']['unchanged']==1
    assert client.get('/api/admin/trade-journal?mode=demo').json['stored_records']==1
    assert client.get('/api/admin/trade-journal?mode=demo').json['summary']['trades']==0
