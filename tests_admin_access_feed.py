import copy
import json
import re
from types import SimpleNamespace
from urllib.parse import parse_qs,urlsplit
from datetime import datetime, timedelta, timezone
import pytest
from werkzeug.security import check_password_hash
from tests_admin_dashboard import admin,login,headers
from feed_connection import DEFAULT_FEED,validate_feed,request_feed
from telegram_messages import render_message,validate_messages,MESSAGE_DEFAULTS


def test_password_change_invalidates_sessions_and_stays_hashed(admin):
    client,store,core,_=admin
    login(client)
    other=core.app.test_client();login(other)
    assert client.post('/api/admin/password',json={},headers=headers(client)).status_code==400
    new='another-long-test-password'
    body={'current':'wrong','new':new,'confirm':new}
    assert client.post('/api/admin/password',json=body,headers=headers(client)).status_code==403
    body['current']='test-admin-secret'
    assert client.post('/api/admin/password',json=body).status_code==403
    assert client.post('/api/admin/password',json=body,headers=headers(client)).status_code==200
    assert other.get('/api/admin/settings').status_code==401
    assert client.get('/api/admin/settings').status_code==401
    saved=store.private_get('password')['value']
    assert new not in saved and check_password_hash(saved,new)
    from admin_dashboard import AdminStore
    assert AdminStore(store.path).private_get('password')['value']==saved
    token=re.search(r'name="csrf" value="([^"]+)"',client.get('/admin/login').text)[1]
    assert client.post('/admin/login',data={'csrf':token,'password':new}).status_code==302
    assert new not in client.get('/api/admin/backup').text
    assert saved not in client.get('/api/admin/backup').text
    assert new not in str(store.events())


def test_password_change_validation_and_brute_force_limit(admin):
    client,store,*_=admin;login(client)
    for new,confirm in [('short','short'),('long-enough-new-secret','mismatch')]:
        assert client.post('/api/admin/password',headers=headers(client),json={'current':'test-admin-secret','new':new,'confirm':confirm}).status_code==400
    for _ in range(5):
        assert client.post('/api/admin/password',headers=headers(client),json={'current':'bad','new':'long-enough-new-secret','confirm':'long-enough-new-secret'}).status_code==403
    assert client.post('/api/admin/password',headers=headers(client),json={'current':'bad','new':'long-enough-new-secret','confirm':'long-enough-new-secret'}).status_code==429
    assert store.private_get('password')['revision']==0


@pytest.mark.parametrize('url',['http://trxchart.com/api','https://127.0.0.1/api','https://localhost/api','https://user:pass@example.com/api','https://example.com/api?key=secret','https://example.com:8443/api'])
def test_feed_endpoint_validation(url,monkeypatch):
    monkeypatch.setattr('feed_connection.socket.getaddrinfo',lambda *a,**k:[(None,None,None,None,('127.0.0.1',443))])
    with pytest.raises(ValueError):validate_feed({**DEFAULT_FEED,'url':url})


def test_auth_modes_and_secret_safe_network_failure():
    calls=[]
    http=SimpleNamespace(get=lambda url,**kwargs:calls.append((url,kwargs)) or SimpleNamespace(status_code=200))
    for mode in ('none','bearer','header','query'):
        cfg={**DEFAULT_FEED,'auth':mode,'key':'PRIVATEKEYVALUE','key_name':'api_key'}
        request_feed(http,cfg,45200,30)
        url,kwargs=calls[-1]
        assert parse_qs(urlsplit(url).query)['limit']==['45200']
        assert kwargs['allow_redirects'] is False
        if mode=='bearer':assert kwargs['headers']['Authorization']=='Bearer PRIVATEKEYVALUE'
        if mode=='header':assert kwargs['headers']['api_key']=='PRIVATEKEYVALUE'
        if mode=='query':assert parse_qs(urlsplit(url).query)['api_key']==['PRIVATEKEYVALUE']
    import requests
    def broken(*a,**k):raise requests.ReadTimeout('https://host/?key=PRIVATEKEYVALUE')
    with pytest.raises(ValueError) as error:request_feed(SimpleNamespace(get=broken),cfg,50,6)
    assert 'PRIVATEKEYVALUE' not in str(error.value)


def test_feed_save_checks_overlap_encryption_revisions_and_secret_exclusion(admin,monkeypatch):
    client,store,core,_=admin;login(client)
    monkeypatch.setattr('feed_connection.socket.getaddrinfo',lambda *a,**k:[(None,None,None,None,('1.1.1.1',443))])
    rows=[{'issue':str(20261005103010001+i),'number':i%10,'block_time':datetime.now(timezone.utc).isoformat()} for i in range(20)]
    core.STATE['history']=rows
    core.parse_history=lambda raw:raw
    monkeypatch.setattr('requests.get',lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:rows))
    value={**DEFAULT_FEED,'auth':'bearer','key':'PRIVATEKEYVALUE','revision':0}
    check=client.post('/api/admin/feed/check',json=value,headers=headers(client))
    assert check.status_code==200 and check.json['matched_rounds']==20
    assert store.feed_config()[0]==0
    saved=client.put('/api/admin/feed',json=value,headers=headers(client))
    assert saved.status_code==200 and saved.json['settings']['key_set']
    assert 'PRIVATEKEYVALUE' not in saved.text
    assert 'PRIVATEKEYVALUE' not in store.private_get('feed')['value']
    assert 'PRIVATEKEYVALUE' not in client.get('/api/admin/backup').text
    assert 'PRIVATEKEYVALUE' not in str(store.events())
    assert client.put('/api/admin/feed',json=value,headers=headers(client)).status_code==409
    assert store.feed_config()[1]['key']=='PRIVATEKEYVALUE'
    # Empty key retains only when destination/authentication have not changed.
    value.update(revision=1,key='')
    assert client.post('/api/admin/feed/check',json=value,headers=headers(client)).status_code==200
    value['url']='https://different.example/api'
    assert client.post('/api/admin/feed/check',json=value,headers=headers(client)).status_code==400
    mismatch=[{**r,'number':(r['number']+1)%10} for r in rows]
    monkeypatch.setattr('requests.get',lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:mismatch))
    value.update(url=DEFAULT_FEED['url'],key='PRIVATEKEYVALUE')
    assert client.put('/api/admin/feed',json=value,headers=headers(client)).status_code==400
    assert store.feed_config()[0]==1


def test_easy_message_editor_keeps_facts_and_literal_braces():
    simple={'heading':'မင်္ဂလာပါ','before':'{ဒီစာက placeholder မဟုတ်ပါ}','after':'Manual only'}
    original='L1 CAPITAL SIGNAL\nIssue: 123\nStake: 500 MMK'
    result=render_message(simple,original,'l1','signal')
    assert result['text'].startswith('မင်္ဂလာပါ') and original in result['text']
    assert '{ဒီစာက placeholder မဟုတ်ပါ}' in result['text']
    settings=copy.deepcopy(MESSAGE_DEFAULTS);settings['templates']['l1.signal']=simple
    assert validate_messages(settings)==settings
    with pytest.raises(ValueError):render_message({'heading':'x','before':'x'},original,'l1','signal')


def test_feed_recovery_uses_selected_endpoint_and_auth(monkeypatch,tmp_path):
    import app
    from admin_dashboard import AdminStore
    store=AdminStore(tmp_path/'admin.sqlite3')
    config={**DEFAULT_FEED,'url':'https://another.example/api','auth':'bearer','key':'PRIVATEKEYVALUE'}
    store.save_feed(config,0)
    monkeypatch.setattr(app.core,'_admin_store',store,raising=False)
    monkeypatch.setattr(app,'_last_recovery_attempt',0)
    monkeypatch.setattr(app,'_feed_health',copy.deepcopy(app._feed_health))
    monkeypatch.setattr(app,'_feed_cache',{})
    calls=[]
    def get(url,**kwargs):
        calls.append((url,kwargs))
        return SimpleNamespace(status_code=200,json=lambda:[{'issue':'20261005103010099'}])
    monkeypatch.setattr(app,'_original_session_get',get)
    assert app._is_live_tail_url('https://another.example/api?limit=50')
    assert not app._is_live_tail_url(DEFAULT_FEED['url']+'?limit=50')
    assert app._recovery_fetch('20261005103010098') is not None
    assert all(url.startswith(config['url']) for url,_ in calls)
    assert calls[0][1]['headers']['Authorization']=='Bearer PRIVATEKEYVALUE'
    assert calls[0][1]['allow_redirects'] is False


def test_corrupt_feed_config_can_be_replaced_without_exposing_ciphertext(admin,monkeypatch):
    client,store,core,_=admin;login(client)
    store.private_save('feed','invalid-ciphertext',0,{'action':'fixture'})
    response=client.get('/api/admin/feed')
    assert response.status_code==200 and response.json['error'] and response.json['revision']==1
    monkeypatch.setattr('feed_connection.socket.getaddrinfo',lambda *a,**k:[(None,None,None,None,('1.1.1.1',443))])
    rows=[{'issue':str(20261005103010001+i),'number':i%10,'block_time':datetime.now(timezone.utc).isoformat()} for i in range(20)]
    core.STATE['history']=rows;core.parse_history=lambda raw:raw
    monkeypatch.setattr('requests.get',lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:rows))
    assert client.put('/api/admin/feed',json={**DEFAULT_FEED,'revision':1},headers=headers(client)).status_code==200
    assert store.feed_config()[1]==DEFAULT_FEED


def test_api_check_rejects_missing_stale_or_future_round_time(admin,monkeypatch):
    client,store,core,_=admin;login(client)
    monkeypatch.setattr('feed_connection.socket.getaddrinfo',lambda *a,**k:[(None,None,None,None,('1.1.1.1',443))])
    rows=[{'issue':str(20261005103010001+i),'number':i%10,'block_time':''} for i in range(20)]
    core.STATE['history']=copy.deepcopy(rows);core.parse_history=lambda raw:raw
    core.source_time_iso=lambda value:'converted' if value else None
    monkeypatch.setattr('requests.get',lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:rows))
    def check():return client.post('/api/admin/feed/check',json=DEFAULT_FEED,headers=headers(client))
    assert check().status_code==400
    now=datetime.now(timezone.utc)
    for offset in (-360, 120):
        for row in rows:row['block_time']=(now+timedelta(seconds=offset)).isoformat()
        assert check().status_code==400
    for row in rows:row['block_time']=(now-timedelta(seconds=20)).isoformat()
    assert check().status_code==200
    assert store.feed_config()[0]==0

