"""Admin audit: causal restore, concurrent edits and hostile input boundaries."""
import copy
import sqlite3
import pytest
from admin_dashboard import DEFAULTS
from strategy_settings import MONEY_DEFAULTS, MoneySchedule
from tests_admin_dashboard import admin, login, headers


def target_revisions(store):
    return {name: item['revision'] for name, item in store.controls.items()}


@pytest.mark.parametrize('issued', [False, True])
def test_live_default_money_restore_applies_only_after_live_boundary(admin, issued):
    client, store, core, _ = admin
    login(client)
    backup = client.get('/api/admin/backup').json
    money = copy.deepcopy(MONEY_DEFAULTS['l1'])
    money['base'] = 1000
    backup['controls']['l1'] = {'revision': 1, 'settings': money}
    backup['money_changes']['l1'] = [{'revision': 1, 'after_issue': '50', 'settings': money}]
    backup['issued_stakes'] = {'60': 1000}
    backup['expected_revision'] = 0
    pending = {'issue': '201', 'stake': 500}
    core.STATE.update(connected=True, history=[{'issue': '200'}], strat_pending=copy.deepcopy(pending))
    if issued:
        store.lock_stake('201', 500)
    response = client.post('/api/admin/restore', json=backup, headers=headers(client))
    assert response.status_code == 200
    schedule = MoneySchedule('l1', store.money_history('l1'))
    assert schedule.at(200)['base'] == 500
    assert schedule.at(201)['base'] == 1000
    assert store.money_history('l1')[0]['after_issue'] == 200
    assert core.STATE['strat_pending'] == pending
    assert '60' not in store.issued
    if issued:
        assert store.issued['201'] == 500


def test_restore_does_not_reprice_disconnected_live_state(admin):
    client, store, core, _ = admin
    login(client)
    backup = client.get('/api/admin/backup').json
    backup['expected_revision'] = 0
    core.STATE.update(connected=False, history=[{'issue': '200'}])
    response = client.post('/api/admin/restore', json=backup, headers=headers(client))
    assert response.status_code == 400
    assert store.cached['revision'] == 0
    assert all(item['revision'] == 0 for item in store.controls.values())


@pytest.mark.parametrize('group', ['l1', 'telegram', 'messages'])
def test_restore_rejects_other_session_control_edit_atomically(admin, group):
    client, store, core, _ = admin
    login(client)
    backup = client.get('/api/admin/backup').json
    backup.update(expected_revision=0)
    backup['settings']['alerts'] = False
    changed = store.control(group)['settings']
    if group == 'l1':
        changed['base'] = 600
        core.STATE.update(connected=True, history=[{'issue': '200'}])
        store.save_control(group, changed, 0, 100)
    elif group == 'telegram':
        changed['engines']['l1'] = False
        store.save_control(group, changed, 0)
    else:
        changed['templates']['l1.signal'] = 'Concurrent edit {original}'
        store.save_control(group, changed, 0)
    response = client.post('/api/admin/restore', json=backup, headers=headers(client))
    assert response.status_code == 409
    assert store.read()['settings'] == DEFAULTS
    assert store.control(group)['settings'] == changed
    assert not any(e['kind'] == 'backup_restored' for e in store.events())


@pytest.mark.parametrize('guard', [None, {'l1': True}, {}])
def test_new_backup_requires_valid_target_control_revisions(admin, guard):
    client, store, *_ = admin
    login(client)
    backup = client.get('/api/admin/backup').json
    backup.update(expected_revision=0, expected_control_revisions=guard)
    assert client.post('/api/admin/restore', json=backup, headers=headers(client)).status_code == 400
    assert store.read()['revision'] == 0


def test_legacy_backup_still_restores(admin):
    client, store, *_ = admin
    login(client)
    backup = client.get('/api/admin/backup').json
    backup.update(schema=1, expected_revision=0)
    backup.pop('expected_control_revisions')
    assert client.post('/api/admin/restore', json=backup, headers=headers(client)).status_code == 200


def test_restore_never_rewinds_delivery_revision_or_accepts_old_edit(admin):
    client, store, *_ = admin
    login(client)
    backup = client.get('/api/admin/backup').json
    changed = store.control('telegram')['settings']
    changed['engines']['l1'] = False
    store.save_control('telegram', changed, 0)
    backup.update(expected_revision=0, expected_control_revisions=target_revisions(store))
    assert client.post('/api/admin/restore', json=backup, headers=headers(client)).status_code == 200
    assert store.control('telegram')['revision'] == 2
    response = client.put('/api/admin/telegram', json={'revision': 0, 'settings': changed}, headers=headers(client))
    assert response.status_code == 409


def test_non_ascii_csrf_is_rejected_without_server_error(admin):
    client, store, *_ = admin
    client.get('/admin/login')
    assert client.post('/admin/login', data={'csrf': 'မမှန်', 'password': 'test-admin-secret'}).status_code == 403
    login(client)
    assert client.put('/api/admin/settings', json={}, headers={'X-CSRF-Token': 'မမှန်'}).status_code == 403
    assert store.read()['revision'] == 0


@pytest.mark.parametrize('engine,category', [([], 'signal'), ({}, 'result'), ('l1', []), ('l1', {})])
def test_message_channel_types_are_validated(admin, engine, category):
    client, *_ = admin
    login(client)
    response = client.post('/api/admin/telegram/messages/preview', json={
        'engine': engine, 'category': category, 'template': '{original}'}, headers=headers(client))
    assert response.status_code == 400


@pytest.mark.parametrize('template', ['\ud800{original}', {'heading': '\udfff', 'before': '', 'after': ''}])
def test_invalid_unicode_template_cannot_be_saved_or_previewed(admin, template):
    client, store, *_ = admin
    login(client)
    data = client.get('/api/admin/telegram/messages').json
    data['settings']['templates']['l1.signal'] = template
    assert client.put('/api/admin/telegram/messages', json=data, headers=headers(client)).status_code == 400
    assert client.post('/api/admin/telegram/messages/preview', json={
        'engine': 'l1', 'category': 'signal', 'template': template}, headers=headers(client)).status_code == 400
    assert store.control('messages')['revision'] == 0


def test_chart_and_private_changes_keep_audit_retention_bounded(admin):
    _, store, *_ = admin
    with store.connect() as db:
        db.executemany('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',
                       [('2026-10-06', 'fixture', '{}')] * 2000)
    store.save(DEFAULTS, 0)
    assert len(store.events(3000)) == 2000
    store.private_save('fixture', 'non-secret-test-value', 0, {'action': 'test'})
    assert len(store.events(3000)) == 2000


def test_failed_maintenance_audit_does_not_leave_job_permanently_queued(admin, monkeypatch):
    client, store, _, cleared = admin
    login(client)
    original = store.event
    def unavailable(*args):
        raise sqlite3.OperationalError('test unavailable database')
    monkeypatch.setattr(store, 'event', unavailable)
    response = client.post('/api/admin/maintenance', json={'action':'cache_refresh'}, headers=headers(client))
    assert response.status_code == 503
    assert client.get('/api/admin/status').json['maintenance']['status'] == 'failed'
    assert not cleared
    monkeypatch.setattr(store, 'event', original)
    assert client.post('/api/admin/maintenance', json={'action':'cache_refresh'}, headers=headers(client)).status_code == 202
