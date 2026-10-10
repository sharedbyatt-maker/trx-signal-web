import copy
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest
import requests

from tests_admin_dashboard import admin, login, headers
from trongrid_feed import DEFAULT_TRONGRID, ENDPOINT, TronGridFeed, RoundResponse, block_record, validate_trongrid


def fixture_blocks():
    now=int(datetime.now(timezone.utc).timestamp()*1000)
    latest=now//60000*60000+54000
    if latest>now:latest-=60000
    head_time=latest+3000
    head_height=100000
    def block(ts):
        n=head_height+(ts-head_time)//3000
        digit=(ts//60000)%10
        return {'blockID':'0'*16+'a'*47+str(digit),'block_header':{'raw_data':{'number':n,'timestamp':ts}}}
    rows=[block_record(block(latest-i*60000),latest-i*60000) for i in range(3,-1,-1)]
    live=[{'issue':r['issueNumber'],'number':r['number'],'block_time':r['blockTime']} for r in rows]
    calls=[]
    def post(url,**kwargs):
        calls.append((url,kwargs))
        target=kwargs['json'].get('id_or_num')
        ts=head_time if target is None else head_time+(int(target)-head_height)*3000
        return SimpleNamespace(status_code=200,json=lambda:block(ts))
    return live,post,calls


def test_block_round_mapping_day_boundary_and_decimal_digit():
    for stamp,issue in [('2026-10-09T23:59:54+00:00','20261009103011440'),('2026-10-10T00:00:54+00:00','20261010103010001')]:
        ts=int(datetime.fromisoformat(stamp).timestamp()*1000)
        block={'blockID':'0'*16+'a'*45+'7ff','block_header':{'raw_data':{'timestamp':ts}}}
        assert block_record(block,ts)['issueNumber']==issue
        assert block_record(block,ts)['number']==7
        with pytest.raises(ValueError):block_record(block,ts+3000)
    block['blockID']='a'*64
    with pytest.raises(ValueError):block_record(block,ts)


def test_adapter_validates_overlap_caches_and_never_sends_wallet_write():
    live,post,calls=fixture_blocks()
    adapter=TronGridFeed()
    result=adapter.fetch('PRIVATE-TEST-KEY',live,post=post)
    assert len(result.json())==4
    assert len(calls)==5
    assert calls[0][1]['json']=={'detail':False}
    assert adapter.fetch('PRIVATE-TEST-KEY',live,post=post).json()==result.json()
    assert len(calls)==5
    assert all(u==ENDPOINT and k['json']['detail'] is False and not k['allow_redirects'] for u,k in calls)
    assert all(k['headers']=={'TRON-PRO-API-KEY':'PRIVATE-TEST-KEY'} for _,k in calls)
    result.json().clear()
    assert len(result.json())==4
    bad=[{**r,'number':(r['number']+1)%10} for r in live]
    with pytest.raises(ValueError,match='do not match'):TronGridFeed().fetch('key',bad,post=post)
    with pytest.raises(ValueError,match='at least 3'):TronGridFeed().fetch('key',live[-2:],post=post)


def test_adapter_cold_fallback_keeps_overlap_and_all_missing_rounds():
    live,post,calls=fixture_blocks()
    from feed_utils import source_time_utc
    old=[]
    for row in live:
        stamp=int(source_time_utc(row['block_time']).timestamp()*1000)-3*60000
        head=post(ENDPOINT,json={'detail':False}) .json()['block_header']['raw_data']
        height=head['number']+round((stamp-head['timestamp'])/3000)
        raw=block_record(post(ENDPOINT,json={'id_or_num':str(height)}).json(),stamp)
        old.append({'issue':raw['issueNumber'],'number':raw['number'],'block_time':raw['blockTime']})
    result=TronGridFeed().fetch('key',old,post=post).json()
    assert len(result)==6
    assert result[-1]['issueNumber']==live[-1]['issue']
    assert all(int(b['issueNumber'])-int(a['issueNumber'])==1 for a,b in zip(result,result[1:]))


def test_adapter_rate_limit_cooldown_and_secret_safe_errors():
    live,post,calls=fixture_blocks();adapter=TronGridFeed();limited=[]
    def rate(*a,**k):limited.append(True);return SimpleNamespace(status_code=429)
    with pytest.raises(ValueError,match='HTTP 429'):adapter.fetch('key',live,post=rate)
    with pytest.raises(ValueError,match='cooling down'):adapter.fetch('key',live,post=rate)
    assert len(limited)==1
    def broken(*a,**k):raise requests.ReadTimeout('PRIVATE-TEST-KEY')
    with pytest.raises(ValueError) as err:TronGridFeed().fetch('PRIVATE-TEST-KEY',live,post=broken)
    assert 'PRIVATE-TEST-KEY' not in str(err.value)
    old=[{**r,'block_time':'2020-01-01T00:00:54+00:00'} for r in live]
    with pytest.raises(ValueError,match='8 minutes'):TronGridFeed().fetch('key',old,post=post)


def test_admin_trongrid_auth_encryption_revisions_probe_and_clear(admin,monkeypatch):
    client,store,core,_=admin
    assert client.get('/api/admin/trongrid').status_code==401
    assert client.post('/api/admin/trongrid/check',json={}).status_code==401
    login(client)
    assert client.put('/api/admin/trongrid',json={}).status_code==403
    live,post,calls=fixture_blocks();core.STATE['history']=live
    monkeypatch.setattr('trongrid_feed.requests.post',post)
    money=copy.deepcopy(store.controls)
    value={'mode':'backup','key':'PRIVATE-TEST-KEY','revision':0}
    assert client.post('/api/admin/trongrid/check',json=value,headers=headers(client)).json['matched_rounds']==4
    assert store.trongrid_config()==(0,DEFAULT_TRONGRID)
    saved=client.put('/api/admin/trongrid',json=value,headers=headers(client))
    assert saved.status_code==200 and saved.json['settings']['key_set']
    assert 'PRIVATE-TEST-KEY' not in saved.text
    assert 'PRIVATE-TEST-KEY' not in store.private_get('trongrid')['value']
    assert 'PRIVATE-TEST-KEY' not in client.get('/api/admin/backup').text
    assert 'PRIVATE-TEST-KEY' not in str(store.events())
    from admin_dashboard import AdminStore
    assert AdminStore(store.path).trongrid_config()[1]['key']=='PRIVATE-TEST-KEY'
    assert client.put('/api/admin/trongrid',json=value,headers=headers(client)).status_code==409
    assert client.put('/api/admin/trongrid',json={'mode':'live','key':'','revision':1},headers=headers(client)).status_code==200
    assert store.trongrid_config()[1]['key']=='PRIVATE-TEST-KEY'
    assert client.delete('/api/admin/trongrid',json={'revision':2},headers=headers(client)).status_code==200
    assert store.trongrid_config()==(3,DEFAULT_TRONGRID)
    assert store.controls==money


def test_failed_probe_does_not_save_and_corrupt_key_can_clear(admin,monkeypatch):
    client,store,core,_=admin;login(client)
    live,post,calls=fixture_blocks();core.STATE['history']=[{**r,'number':(r['number']+1)%10} for r in live]
    monkeypatch.setattr('trongrid_feed.requests.post',post)
    value={'mode':'live','key':'PRIVATE-TEST-KEY','revision':0}
    assert client.put('/api/admin/trongrid',json=value,headers=headers(client)).status_code==400
    assert store.trongrid_config()==(0,DEFAULT_TRONGRID)
    store.private_save('trongrid','unreadable',0,{'mode':'fixture'})
    assert client.get('/api/admin/trongrid').json['error']
    assert client.delete('/api/admin/trongrid',json={'revision':1},headers=headers(client)).status_code==200


@pytest.mark.parametrize('value',[{'mode':'live','key':''},{'mode':'x','key':'key'},{'mode':'live','key':'key\n'},{'mode':'live','key':'a b'},{'mode':'live','key':123}])
def test_invalid_keys_and_modes(value):
    with pytest.raises(ValueError):validate_trongrid(value)


def test_feed_backup_and_live_routing_preserve_full_history_and_defaults(monkeypatch):
    import app_core as core
    from feed_connection import DEFAULT_FEED
    tg={'mode':'disabled','key':''};primary_calls=[];tg_calls=[]
    live,_,_=fixture_blocks()
    primary=RoundResponse([{'issueNumber':r['issue'],'number':r['number'],'blockTime':r['block_time']} for r in live])
    store=SimpleNamespace(feed_config=lambda:(0,DEFAULT_FEED),trongrid_config=lambda:(0,tg.copy()))
    monkeypatch.setattr(core,'_admin_store',store,raising=False)
    monkeypatch.setattr(core,'STATE',{'history':live})
    def get(*a,**k):primary_calls.append(True);return primary
    monkeypatch.setattr(core,'request_feed',get)
    def fetch(*a,**k):tg_calls.append(True);return primary
    monkeypatch.setattr('trongrid_feed.LIVE_TRONGRID.fetch',fetch)
    monkeypatch.setattr(core,'_record_external_feed',lambda response:None,raising=False)
    assert core.fetch_feed(50,6) is primary and not tg_calls
    tg.update(mode='backup',key='key')
    assert core.fetch_feed(50,6) is primary and not tg_calls
    def offline(*a,**k):raise ValueError('Primary unavailable')
    monkeypatch.setattr(core,'request_feed',offline)
    assert core.fetch_feed(50,6) is primary and tg_calls==[True]
    with pytest.raises(ValueError):core.fetch_feed(45200,30)
    assert len(tg_calls)==1
    mismatched=RoundResponse([{**r,'number':(r['number']+1)%10} for r in primary.json()])
    monkeypatch.setattr(core,'request_feed',lambda *a,**k:mismatched)
    assert core.fetch_feed(50,6) is primary and len(tg_calls)==2
    assert core.STATE['data_source']=='trongrid'
    monkeypatch.setattr(core,'request_feed',get)
    assert core.fetch_feed(50,6) is primary and len(tg_calls)==2
    assert core.STATE['data_source']=='primary'
    tg['mode']='live'
    assert core.fetch_feed(50,6) is primary and len(tg_calls)==3
    def reject(*a,**k):raise ValueError('Mismatch')
    monkeypatch.setattr('trongrid_feed.LIVE_TRONGRID.fetch',reject)
    with pytest.raises(ValueError,match='Mismatch'):core.fetch_feed(50,6)
