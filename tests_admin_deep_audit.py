"""Regressions for atomic restore, message customization and resilient delivery."""
import copy
import queue
from types import SimpleNamespace
import pytest
from tests_admin_dashboard import admin, login, headers
from telegram_messages import MESSAGE_DEFAULTS, render_message, validate_template


def test_restore_database_failure_rolls_back_every_group(admin):
    client,store,*_=admin
    login(client)
    original=client.get('/api/admin/backup').json
    backup=copy.deepcopy(original)
    backup['expected_revision']=0
    backup['settings']['alerts']=False
    backup['controls']['telegram']['settings']['engines']['l1']=False
    with store.connect() as db:
        db.execute("CREATE TRIGGER reject_restore BEFORE UPDATE ON controls WHEN NEW.name='twelve' BEGIN SELECT RAISE(ABORT,'test rollback'); END")
    response=client.post('/api/admin/restore',json=backup,headers=headers(client))
    assert response.status_code==503
    assert store.cached['revision']==0 and store.cached['settings']==original['settings']
    assert store.control('telegram')==original['controls']['telegram']
    assert store.read()['settings']==original['settings']
    assert not any(e['kind']=='backup_restored' for e in store.events())


def test_message_revision_preview_backup_and_old_backup_compatibility(admin):
    client,store,*_=admin
    assert client.get('/api/admin/telegram/messages').status_code==401
    login(client)
    data=client.get('/api/admin/telegram/messages').json
    data['settings']['templates']['l1.signal']='မင်္ဂလာပါ {engine}\n{body}'
    assert client.put('/api/admin/telegram/messages',json=data).status_code==403
    assert client.put('/api/admin/telegram/messages',json=data,headers=headers(client)).status_code==200
    assert client.put('/api/admin/telegram/messages',json=data,headers=headers(client)).status_code==409
    preview=client.post('/api/admin/telegram/messages/preview',json={'engine':'l1','category':'signal','template':data['settings']['templates']['l1.signal']},headers=headers(client))
    assert preview.status_code==200 and 'မင်္ဂလာပါ L1 CAPITAL' in preview.json['text'] and '500 MMK' in preview.json['text']
    backup=client.get('/api/admin/backup').json
    assert backup['controls']['messages']['revision']==1
    backup['expected_revision']=0
    assert client.post('/api/admin/restore',json=backup,headers=headers(client)).status_code==200
    del backup['controls']['messages']
    backup['expected_revision']=1
    backup['expected_control_revisions']={name:item['revision'] for name,item in store.controls.items()}
    assert client.post('/api/admin/restore',json=backup,headers=headers(client)).status_code==200
    assert store.control('messages')['settings']==data['settings']


@pytest.mark.parametrize('template',['{password}','{original.__class__}','{body!r}','{body:1000}','{','', 'x'*1801])
def test_template_validation_blocks_unknown_or_executable_fields(template):
    with pytest.raises(ValueError):validate_template(template)


def test_custom_heading_keeps_engine_facts_and_unicode_limit_falls_back():
    message='L1 CAPITAL\nIssue: 123\nStake: 500 MMK'
    rendered=render_message('My alert — {engine}',message,'l1','signal')
    assert rendered['details_appended'] and message in rendered['text']
    assert render_message('{body}',message,'l1','signal')['text'].startswith('Issue: 123\nStake: 500 MMK')
    assert message.split('\n')[0] in render_message('{body}',message,'l1','signal')['text']
    assert render_message('😀'*1700+'{original}','x'*1000,'l1','signal')['fallback']
    assert render_message('{{hello}} {title}',message,'l1','signal')['text'].startswith('{hello} L1 CAPITAL')


def test_logs_filter_before_limit_and_cursor_no_cross_channel_loss(admin):
    client,store,*_=admin
    login(client)
    store.event('money_change',{'message':'old audit'})
    for i in range(110):store.event('telegram',{'message':f'alert {i}'})
    audit=client.get('/api/admin/events?kind=audit&limit=10').json
    assert any(e['kind']=='money_change' for e in audit['events'])
    newest=client.get('/api/admin/events?kind=telegram&limit=10').json
    older=client.get('/api/admin/events?kind=telegram&limit=10&before='+str(newest['next_before'])).json
    assert not {e['id'] for e in newest['events']}.intersection(e['id'] for e in older['events'])
    assert client.get('/api/admin/events?kind=telegram&search=alert%2050').json['events'][0]['detail']['message']=='alert 50'
    assert client.get('/api/admin/events?before=bad').status_code==400


def test_worker_survives_failure_uses_original_routing_and_discards_stale_signal(monkeypatch,tmp_path):
    import app_core as core
    from admin_dashboard import AdminStore
    store=AdminStore(tmp_path/'a.sqlite3')
    templates=copy.deepcopy(MESSAGE_DEFAULTS)
    templates['templates']['l1.result']='Market-looking custom heading\n{body}'
    store.save_control('messages',templates,0)
    q=queue.Queue();sent=[]
    monkeypatch.setattr(core,'_admin_store',store,raising=False)
    monkeypatch.setattr(core,'_tg_queue',q)
    monkeypatch.setattr(core,'load_tg_config',lambda:('token','chat'))
    def send(text,cfg):
        if not sent:
            sent.append('failed');raise ValueError('SECRET')
        sent.append(text);return 'sent'
    monkeypatch.setattr(core,'_send_telegram',send)
    monkeypatch.setattr(core,'STATE',copy.deepcopy(core.STATE))
    q.put(core.TelegramNotification('first','l1','result'))
    stale=core.TelegramNotification('old actionable signal','l1','signal');stale.created-=60;q.put(stale)
    q.put(core.TelegramNotification('L1 CAPITAL\nStake: 500 MMK','l1','result'));q.put(None)
    core._tg_worker()
    assert q.unfinished_tasks==0 and len(sent)==2 and 'Market-looking' in sent[-1]
    records=store.events()
    assert records[0]['detail']['engine']=='l1'
    assert any(e['detail']['result']=='expired signal — discarded' for e in records)
    assert 'SECRET' not in str(records)


def test_api_response_and_long_rate_limit_are_not_false_success(monkeypatch):
    import app_core as core
    monkeypatch.setattr(core,'_tg_rate_limited_until',0)
    post=lambda *a,**k:SimpleNamespace(status_code=200,json=lambda:{'ok':False})
    monkeypatch.setattr(core.requests,'post',post)
    assert core._send_telegram('sample',('token','chat'))=='Telegram rejected response'
    calls=[]
    def limited(*a,**k):
        calls.append(True)
        return SimpleNamespace(status_code=429,json=lambda:{'parameters':{'retry_after':3600}})
    monkeypatch.setattr(core.requests,'post',limited)
    assert 'rate limited' in core._send_telegram('sample',('token','chat'))
    assert 'rate limited' in core._send_telegram('sample2',('token','chat'))
    assert len(calls)==1


def test_corrupt_override_blocks_fallback_and_can_be_replaced(monkeypatch,tmp_path):
    import app_core as core
    from admin_dashboard import AdminStore
    store=AdminStore(tmp_path/'a.sqlite3')
    store.vault.path.write_bytes(b'broken ciphertext')
    monkeypatch.setattr(core,'_admin_store',store,raising=False)
    monkeypatch.setenv('TG_TOKEN','123456:'+('x'*30));monkeypatch.setenv('TG_CHAT','123456')
    assert core.load_tg_config() is None
    assert 'unreadable' in core._tg_config_error
    store.vault.save('123456:'+('y'*30),'999999')
    assert core.load_tg_config()[1]=='999999' and core._tg_config_error is None


def test_maximum_unicode_templates_produce_a_restorable_backup(admin):
    client,store,*_=admin
    login(client)
    value={'templates':{key:'က'*1800 for key in MESSAGE_DEFAULTS['templates']}}
    store.save_control('messages',value,0)
    assert len(str(store.events()[0]['detail']))<2000
    backup=client.get('/api/admin/backup').json
    backup['expected_revision']=0
    assert client.post('/api/admin/restore',json=backup,headers=headers(client)).status_code==200
    assert store.control('messages')['settings']==value
