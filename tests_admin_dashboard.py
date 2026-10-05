import copy
import re
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, jsonify, render_template
from werkzeug.security import generate_password_hash
from admin_dashboard import AdminStore, DEFAULTS, install_admin


def render_terminal_defaults():
    app = Flask(__name__, template_folder=str(Path('templates').resolve()), static_folder=str(Path('static').resolve()))
    with app.test_request_context('/'):
        return render_template('index.html', admin_defaults=DEFAULTS)


@pytest.fixture
def admin(tmp_path):
    app = Flask(__name__, template_folder=str(Path('templates').resolve()))
    core = SimpleNamespace(app=app, LOCK=threading.RLock(), STATE={'strat_log': []}, signal_history=[],
                           load_tg_config=lambda: None, _engine_thread=None)
    def daily():
        return jsonify(report={'settled_bets': 0, 'net_pnl': 0}, history=[])
    core.api_strat_daily_report = daily
    store = AdminStore(tmp_path / 'admin.sqlite3')
    cleared = []
    install_admin(core, lambda: (jsonify(ok=False, status='OFFLINE', engine={}, feed={}, queues={}),503),
                  SimpleNamespace(public_snapshot=lambda: {'trades': [], 'daily_summary': {}}),
                  lambda: cleared.append(True), password_hash=generate_password_hash('test-admin-secret'), store=store)
    app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    return app.test_client(), store, core, cleared


def login(client):
    response = client.get('/admin/login')
    token = re.search(r'name="csrf" value="([^"]+)"', response.text)[1]
    return client.post('/admin/login', data={'csrf': token, 'password': 'test-admin-secret'})


def headers(client):
    with client.session_transaction() as sess:
        return {'X-CSRF-Token': sess['csrf']}


def test_admin_auth_and_csrf_boundaries(admin):
    client, store, _, _ = admin
    for path in ('status', 'settings', 'events', 'reports', 'backup'):
        assert client.get('/api/admin/' + path).status_code == 401
    for path, method in (('settings', 'put'), ('logout', 'post'), ('maintenance', 'post'), ('restore', 'post')):
        assert getattr(client, method)('/api/admin/' + path, json={}).status_code == 401
    assert client.post('/admin/login', data={'password': 'test-admin-secret'}).status_code == 403
    assert login(client).status_code == 302
    assert client.get('/admin').status_code == 200
    assert client.put('/api/admin/settings', json={}).status_code == 403
    assert client.get('/api/admin/status').json['health']['status'] == 'OFFLINE'
    assert 'no-store' in client.get('/admin').headers['Cache-Control']
    assert client.post('/api/admin/logout', headers=headers(client)).status_code == 200
    assert client.get('/api/admin/settings').status_code == 401


def test_validated_settings_revision_and_restart(admin):
    client, store, _, _ = admin
    login(client)
    value = copy.deepcopy(DEFAULTS)
    value.update(timeframe=5, range=30, telegram=False)
    value['indicators']['hss'] = True
    data = {'revision': 0, 'settings': value}
    assert client.put('/api/admin/settings', json=data, headers=headers(client)).status_code == 200
    assert AdminStore(store.path).cached['settings'] == value
    assert client.put('/api/admin/settings', json=data, headers=headers(client)).status_code == 409
    data['revision'] = 1
    data['settings']['timeframe'] = 2
    assert client.put('/api/admin/settings', json=data, headers=headers(client)).status_code == 400
    assert store.cached['revision'] == 1
    assert store.events()[0]['kind'] == 'settings_saved'


def test_backup_restore_and_maintenance_preconditions(admin):
    client, store, core, cleared = admin
    login(client)
    auth = headers(client)
    backup = client.get('/api/admin/backup').json
    backup['settings']['alerts'] = False
    backup['expected_revision'] = 0
    assert client.post('/api/admin/restore', json=backup, headers=auth).status_code == 200
    assert store.cached['settings']['alerts'] is False
    assert client.post('/api/admin/restore', json=backup, headers=auth).status_code == 409
    for action, code in (('delete_all',400),('history_refresh',503),('telegram_test',409)):
        assert client.post('/api/admin/maintenance', json={'action': action}, headers=auth).status_code == code
    assert client.post('/api/admin/maintenance', json={'action':'cache_refresh'}, headers=auth).status_code == 202
    import time
    for _ in range(50):
        if cleared:
            break
        time.sleep(.01)
    assert cleared and core.STATE['backtest'] is None


def test_login_rate_limit(admin):
    client, *_ = admin
    token = re.search(r'name="csrf" value="([^"]+)"', client.get('/admin/login').text)[1]
    for _ in range(5):
        assert client.post('/admin/login', data={'csrf':token,'password':'wrong'}).status_code == 200
    assert client.post('/admin/login', data={'csrf':token,'password':'wrong'}).status_code == 429


def test_restore_rejects_invalid_events_without_mutating(admin):
    client, store, *_ = admin
    login(client)
    for events in ([{'bad':True}], [{'at':'x','kind':'test','detail':'not-object'}]):
        result = client.post('/api/admin/restore', headers=headers(client), json={'schema':1,'settings':DEFAULTS,'expected_revision':0,'events':events})
        assert result.status_code == 400
        assert store.cached['revision'] == 0


def test_engine_owned_refresh_preserves_latest_and_pending(monkeypatch):
    import os
    os.environ['TRX_NO_ENGINE'] = '1'
    import app_core as core
    latest = '20261005103010002'
    raw = [dict(issueNumber='20261005103010001', number=2, blockTime='2026-10-05 00:00:00'),
           dict(issueNumber=latest, number=8, blockTime='2026-10-05 00:01:00')]
    calls = []
    class Response:
        status_code = 200
        def json(self):
            return raw if len(calls) == 1 else [dict(raw[0], number=7)]
    def get(url, **kwargs):
        calls.append(url)
        return Response()
    sleeps = []
    def sleep(_):
        sleeps.append(True)
        if len(sleeps) == 1:
            core._admin_history_refresh_requested.set()
        else:
            raise StopIteration('test complete')
    monkeypatch.setattr(core.session, 'get', get)
    monkeypatch.setattr(core.time, 'sleep', sleep)
    monkeypatch.setattr(core, 'last_issue', latest)
    monkeypatch.setattr(core, '_admin_history_refresh_requested', threading.Event())
    monkeypatch.setattr(core, '_admin_history_refresh_result', {})
    original = copy.deepcopy(core.STATE)
    monkeypatch.setattr(core, 'STATE', {**original, 'history':core.parse_history(raw), 'pending':{'issue':'next','stake':500}})
    monkeypatch.setattr(core, 'pending', {'issue':'next','stake':500})
    with pytest.raises(StopIteration):
        core.engine_loop()
    assert len(calls) == 2 and all(f'limit={core.MAX_FULL_ROWS}' in u for u in calls)
    assert core.last_issue == latest
    assert core.pending == {'issue':'next','stake':500}
    assert core.STATE['full_history'][-1]['issue'] == latest
    assert core.STATE['full_history'][0]['number'] == 7
    assert core._admin_history_refresh_result['ok'] is True
    assert not core._admin_history_refresh_requested.is_set()
