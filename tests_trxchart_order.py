"""Order regressions use only fake provider sessions; no live orders."""
import json
import threading
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import requests

from admin_dashboard import AdminStore
from trxchart_account_sync import ProviderError
from trxchart_bet import OrderService, OrderError, MAX_RESPONSE_BYTES


class Response:
    def __init__(self, code=200, body=None, raw=None):
        self.status_code = code
        self.raw = raw if raw is not None else json.dumps({'success': True} if body is None else body).encode()
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def iter_content(self, size):
        if isinstance(self.raw, Exception):
            raise self.raw
        for at in range(0, len(self.raw), size):
            yield self.raw[at:at + size]


class Client:
    def __init__(self, response):
        self.response, self.calls = response, []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def post(self, url, **kwargs):
        self.calls.append((url, kwargs))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class Sync:
    def __init__(self, response):
        self.client = Client(response)
        self.operation = threading.Lock()
        self.active = True
        self.token_error = None

    def read(self):
        return 0, {'active': self.active}

    def session(self, config):
        return self.client

    def token(self, client):
        if self.token_error:
            raise self.token_error
        return 'fake-token'


class Clock:
    value = datetime(2026, 10, 11, 14, 0, tzinfo=timezone(timedelta(hours=7)))

    def __call__(self):
        return self.value

    def advance(self, seconds=31):
        self.value += timedelta(seconds=seconds)


@pytest.fixture
def service(tmp_path, monkeypatch):
    monkeypatch.setenv('TRX_ORDER_ENABLED', '1')
    for key in ('MAX_AMOUNT', 'DAILY_MAX_COUNT', 'DAILY_MAX_TOTAL', 'MIN_INTERVAL_SEC'):
        monkeypatch.delenv('TRX_ORDER_' + key, raising=False)
    monkeypatch.setenv('TRX_ORDER_MAX_AMOUNT', '100')
    monkeypatch.setenv('TRX_ORDER_MIN_INTERVAL_SEC', '30')
    sync, store, clock = Sync(Response()), AdminStore(tmp_path / 'orders.sqlite3'), Clock()
    return OrderService(sync, store, now=clock), sync, store, clock


def place(svc, **changes):
    args = {'direction': 'BIG', 'amount': 10, 'confirmed': True, 'mode': 'real', 'request_id': str(uuid4())}
    args.update(changes)
    return svc.place(**args)


def test_explicitly_disabled(service, monkeypatch):
    svc, sync, _, _ = service
    monkeypatch.setenv('TRX_ORDER_ENABLED', '0')
    with pytest.raises(OrderError) as exc:
        place(svc)
    assert exc.value.status == 403 and not sync.client.calls


@pytest.mark.parametrize('changes', [
    {'direction': 'big'}, {'direction': ['BIG']}, {'amount': 0}, {'amount': 101},
    {'amount': True}, {'amount': 10.5}, {'amount': '10'}, {'confirmed': 'yes'},
    {'confirmed': False}, {'mode': 'demo'}, {'mode': None}, {'request_id': None},
    {'request_id': 'not-an-id'},
])
def test_invalid_input_never_sends(service, changes):
    svc, sync, _, _ = service
    with pytest.raises(OrderError):
        place(svc, **changes)
    assert not sync.client.calls


def test_exact_real_payload_and_durable_audit(service):
    svc, sync, store, _ = service
    out = place(svc, amount=100)
    url, kwargs = sync.client.calls[0]
    assert url == 'https://trxchart.com/api/bet'
    assert kwargs == {'json': {'direction': 'BIG', 'amount': 100}, 'headers': {'X-API-Token': 'fake-token'},
                      'timeout': (3, 8), 'allow_redirects': False, 'stream': True}
    assert out['ok'] and out['today_count'] == 1 and out['today_total'] == 100
    assert [e['detail']['outcome'] for e in reversed(store.events())] == ['pending', 'accepted']
    assert sync.client.response.closed
    assert 'fake-token' not in json.dumps(store.events())


@pytest.mark.parametrize('response,outcome', [
    (Response(body={}), 'unknown'), (Response(body={'error': 'secret-value'}), 'unknown'),
    (Response(body={'success': 0}), 'unknown'), (Response(body={'success': 1}), 'unknown'),
    (Response(body={'success': True, 'error': 'secret-value'}), 'unknown'),
    (Response(body={'success': False}), 'rejected'), (Response(body=[]), 'unknown'),
    (Response(500), 'unknown'), (Response(502), 'unknown'), (Response(408), 'unknown'),
    (Response(201), 'unknown'), (Response(403), 'rejected'), (Response(302), 'rejected'),
    (Response(raw=b'not JSON'), 'unknown'), (Response(raw=b'\xff'), 'unknown'),
    (Response(raw=b'x' * (MAX_RESPONSE_BYTES + 1)), 'unknown'),
    (Response(raw=requests.Timeout()), 'unknown'), (requests.Timeout(), 'unknown'),
])
def test_uncertain_responses_never_claim_success_or_retry(service, response, outcome):
    svc, sync, _, _ = service
    sync.client.response = response
    out = place(svc)
    assert out['outcome'] == outcome and not out['ok']
    assert len(sync.client.calls) == 1 and out['today_count'] == 1
    assert 'secret-value' not in out['message']


def test_restart_keeps_count_total_cooldown_and_idempotency(service):
    svc, sync, store, clock = service
    request_id = str(uuid4())
    place(svc, request_id=request_id)
    restarted = OrderService(sync, AdminStore(store.path), now=clock)
    assert restarted.status()['today_count'] == 1
    assert restarted.status()['today_total'] == 10
    assert restarted.status()['retry_after_sec'] == 30
    replay = place(restarted, request_id=request_id)
    assert replay['ok'] and replay['replayed'] and len(sync.client.calls) == 1
    with pytest.raises(OrderError) as exc:
        place(restarted)
    assert exc.value.status == 429
    clock.advance()
    with pytest.raises(OrderError) as exc:
        place(restarted, amount=11, request_id=request_id)
    assert exc.value.status == 409


def test_daily_caps_and_midnight_cooldown(service, monkeypatch):
    svc, sync, _, clock = service
    monkeypatch.setenv('TRX_ORDER_DAILY_MAX_COUNT', '2')
    monkeypatch.setenv('TRX_ORDER_DAILY_MAX_TOTAL', '15')
    place(svc)
    clock.advance()
    with pytest.raises(OrderError):
        place(svc)
    place(svc, amount=5)
    clock.advance()
    with pytest.raises(OrderError):
        place(svc, amount=1)
    clock.value = clock.value.replace(hour=23, minute=59, second=50)
    monkeypatch.setenv('TRX_ORDER_DAILY_MAX_COUNT', '3')
    monkeypatch.setenv('TRX_ORDER_DAILY_MAX_TOTAL', '20')
    place(svc, amount=1)
    clock.advance(15)
    assert svc.status()['today_count'] == 0
    with pytest.raises(OrderError) as exc:
        place(svc)
    assert exc.value.status == 429
    clock.advance(16)
    assert place(svc)['today_count'] == 1


def test_pending_after_crash_is_unknown_and_not_resent(service, monkeypatch):
    svc, sync, store, clock = service
    request_id = str(uuid4())
    def crash(*args):
        raise RuntimeError('process interruption')
    monkeypatch.setattr(svc, '_send', crash)
    with pytest.raises(RuntimeError):
        place(svc, request_id=request_id)
    restarted = OrderService(sync, AdminStore(store.path), now=clock)
    replay = place(restarted, request_id=request_id)
    assert replay['outcome'] == 'unknown' and replay['replayed']
    assert replay['today_count'] == 1 and not sync.client.calls
    assert store.events()[0]['detail']['outcome'] == 'pending'


def test_token_failure_or_disconnected_does_not_consume_limits(service):
    svc, sync, store, _ = service
    sync.token_error = ProviderError('expired')
    with pytest.raises(ProviderError):
        place(svc)
    assert svc.status()['today_count'] == 0 and not store.events()
    sync.active = False
    with pytest.raises(ProviderError):
        place(svc)
    assert not sync.client.calls
    assert not svc.lock.locked() and not sync.operation.locked()


def test_sync_and_order_cannot_share_rotating_token(service):
    svc, sync, _, _ = service
    with sync.operation:
        with pytest.raises(OrderError) as exc:
            place(svc)
        assert exc.value.status == 409
    assert not sync.client.calls and not svc.lock.locked()


def test_two_services_share_transactional_daily_limit(service, monkeypatch):
    svc, sync, store, clock = service
    monkeypatch.setenv('TRX_ORDER_DAILY_MAX_COUNT', '1')
    other_sync = Sync(Response())
    other = OrderService(other_sync, AdminStore(store.path), now=clock)
    barrier = threading.Barrier(2)
    def token(client):
        barrier.wait(timeout=5)
        return 'fake-token'
    sync.token = other_sync.token = token
    results = []
    def submit(service):
        try:
            results.append(place(service)['outcome'])
        except OrderError as exc:
            results.append(exc.status)
    threads = [threading.Thread(target=submit, args=(x,)) for x in (svc, other)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)
        assert not thread.is_alive()
    assert sorted(map(str, results)) == ['429', 'accepted']
    assert len(sync.client.calls) + len(other_sync.client.calls) == 1
    assert svc.status()['today_count'] == 1


def test_post_success_with_database_failure_stays_reserved(service):
    import sqlite3
    svc, sync, store, clock = service
    request_id = str(uuid4())
    with store.connect() as db:
        db.execute("CREATE TRIGGER fail_finish BEFORE UPDATE ON trxchart_orders BEGIN SELECT RAISE(ABORT,'fixture storage failure'); END")
    with pytest.raises(sqlite3.Error):
        place(svc, request_id=request_id)
    restarted = OrderService(sync, AdminStore(store.path), now=clock)
    result = place(restarted, request_id=request_id)
    assert result['outcome'] == 'unknown' and result['today_count'] == 1
    assert len(sync.client.calls) == 1


def test_order_timezone_does_not_require_os_zoneinfo(service):
    from zoneinfo import reset_tzpath, TZPATH
    svc, _, _, _ = service
    old = TZPATH
    try:
        reset_tzpath([])
        assert svc.status()['today_count'] == 0
        assert OrderService(svc.sync, svc.store).status()['mode'] == 'real'
    finally:
        reset_tzpath(old)


def test_order_endpoint_auth_csrf_mode_and_disabled(admin, monkeypatch):
    from tests_admin_dashboard import login, headers
    client, store, _, _ = admin
    assert client.get('/api/admin/trxchart-order').status_code == 401
    assert client.post('/api/admin/trxchart-order', json={}).status_code == 401
    login(client)
    monkeypatch.setenv('TRX_ORDER_ENABLED', '0')
    assert client.get('/api/admin/trxchart-order').json['enabled'] is False
    assert client.post('/api/admin/trxchart-order', json={}).status_code == 403
    body = {'direction': 'BIG', 'amount': 10, 'confirm': True, 'mode': 'real', 'request_id': str(uuid4())}
    assert client.post('/api/admin/trxchart-order', json=body, headers=headers(client)).status_code == 403
    monkeypatch.setenv('TRX_ORDER_ENABLED', '1')
    body['mode'] = 'demo'
    assert client.post('/api/admin/trxchart-order', json=body, headers=headers(client)).status_code == 400
    body['mode'] = 'real'
    sync = Sync(Response())
    store.orders.sync = sync
    response = client.post('/api/admin/trxchart-order', json=body, headers=headers(client))
    assert response.status_code == 200 and response.json['ok']
    assert client.post('/api/admin/trxchart-order', json=body, headers=headers(client)).json['replayed']
    assert len(sync.client.calls) == 1


# Imported so pytest also discovers the existing admin fixture in this module.
from tests_admin_dashboard import admin  # noqa: E402,F401


def test_default_permissions_are_enabled_without_local_limits(service, monkeypatch):
    svc, sync, _, _ = service
    for suffix in ('ENABLED', 'MAX_AMOUNT', 'DAILY_MAX_COUNT', 'DAILY_MAX_TOTAL', 'MIN_INTERVAL_SEC'):
        monkeypatch.delenv('TRX_ORDER_' + suffix, raising=False)
    assert svc.status()['enabled'] and svc.status()['unrestricted']
    for _ in range(35):
        assert place(svc, amount=1600)['ok']
    assert svc.status()['today_count'] == 35
    assert svc.status()['today_total'] == 56000
    assert svc.status()['retry_after_sec'] == 0
    assert len(sync.client.calls) == 35


def test_dashboard_permissions_override_environment_and_survive_restart(service, monkeypatch):
    svc, sync, store, clock = service
    monkeypatch.setenv('TRX_ORDER_ENABLED', '0')
    result = svc.save_permissions({'revision': 0, 'enabled': True, 'unrestricted': True})
    assert result['settings_revision'] == 1 and result['enabled'] and result['unrestricted']
    restarted = OrderService(sync, AdminStore(store.path), now=clock)
    assert place(restarted, amount=1600)['ok']
    assert place(restarted, amount=2000)['ok']
    with pytest.raises(RuntimeError):
        svc.save_permissions({'revision': 0, 'enabled': False, 'unrestricted': True})
    svc.save_permissions({'revision': 1, 'enabled': False, 'unrestricted': True})
    with pytest.raises(OrderError) as exc:
        place(restarted)
    assert exc.value.status == 403
    assert len(sync.client.calls) == 2


def test_permission_settings_auth_csrf_revision_and_validation(admin, monkeypatch):
    from tests_admin_dashboard import login, headers
    client, _, _, _ = admin
    path = '/api/admin/trxchart-order/settings'
    body = {'revision': 0, 'enabled': True, 'unrestricted': True}
    assert client.put(path, json=body).status_code == 401
    login(client)
    monkeypatch.setenv('TRX_ORDER_ENABLED', '0')
    monkeypatch.setenv('TRX_ORDER_MAX_AMOUNT', '100')
    assert client.put(path, json=body).status_code == 403
    assert client.put(path, json={**body, 'enabled': 'yes'}, headers=headers(client)).status_code == 400
    result = client.put(path, json=body, headers=headers(client))
    assert result.status_code == 200 and result.json['enabled']
    assert result.json['max_amount'] == 0 and result.json['unrestricted']
    assert client.put(path, json=body, headers=headers(client)).status_code == 409


@pytest.mark.parametrize('response,followed', [
    (Response(), True), (requests.Timeout(), True),
    (Response(body={'success': False}), False),
])
def test_sent_order_follows_results_without_resubmitting(service, response, followed):
    svc, sync, _, _ = service
    sync.client.response = response
    calls = []
    sync.follow_orders = lambda: calls.append('follow')
    request_id = str(uuid4())
    place(svc, request_id=request_id)
    assert calls == (['follow'] if followed else [])
    place(svc, request_id=request_id)
    assert len(sync.client.calls) == 1
    assert calls == (['follow'] if followed else [])


@pytest.mark.parametrize('status,body,code', [
    (400, {'error': 'invalid direction'}, 'invalid_direction'),
    (400, {'error': {'code': 'insufficient_balance'}}, 'insufficient_balance'),
    (200, {'success': False, 'message': 'betting is closed'}, 'round_closed'),
    (401, {'message': 'SECRET-password-token'}, 'session_expired'),
    (403, {'message': 'SECRET-password-token'}, 'permission_denied'),
    (429, {'message': 'SECRET-password-token'}, 'rate_limited'),
    (400, {'error': 'SECRET-password-token'}, 'invalid_request'),
    (400, {'error': 'invalid amount', 'message': 'insufficient funds'}, 'invalid_request'),
])
def test_rejection_diagnosis_survives_restart_replay_and_receipt_reload(service, status, body, code):
    svc, sync, store, clock = service
    sync.client.response = Response(status, body)
    request_id = str(uuid4())
    out = place(svc, request_id=request_id)
    assert out['outcome'] == 'rejected' and out['reason_code'] == code
    assert f'HTTP {status}' in out['message']
    restarted = OrderService(sync, AdminStore(store.path), now=clock)
    replay = place(restarted, request_id=request_id)
    assert replay['message'] == out['message'] and replay['reason_code'] == code
    assert replay['replayed'] and len(sync.client.calls) == 1
    row = restarted.recent({'rows': []})[0]
    assert row['message'] == out['message'] and row['http_status'] == status
    assert row['state'] == -1 and row['pnl'] is None
    with store.connect() as db:
        saved = str(db.execute('SELECT * FROM trxchart_order_diagnostics').fetchall())
    assert 'SECRET-password-token' not in saved + json.dumps(store.events()) + json.dumps(out) + json.dumps(row)


@pytest.mark.parametrize('raw', [b'not json SECRET', b'x' * (MAX_RESPONSE_BYTES + 1), requests.Timeout()])
def test_bounded_error_body_failure_keeps_known_http_rejection(service, raw):
    svc, sync, _, _ = service
    sync.client.response = Response(400, raw=raw)
    out = place(svc)
    assert out['outcome'] == 'rejected' and out['reason_code'] == 'invalid_request'
    assert len(sync.client.calls) == 1 and sync.client.response.closed


def test_existing_ledger_http_status_is_visible_without_inventing_missing_reason(service):
    svc, _, store, clock = service
    with store.connect() as db:
        db.execute('INSERT INTO trxchart_orders VALUES(?,?,?,?,?,?,?)',
                   (str(uuid4()), clock.value.date().isoformat(), clock.value.timestamp(), 'SMALL', 200, 'rejected', 400))
    row = svc.recent({'rows': []})[0]
    assert row['reason_code'] == 'invalid_request' and 'exact reason is unavailable' in row['message']


def test_order_auth_rejection_invalidates_account_but_permission_refusal_does_not(service):
    from trxchart_account_sync import HistorySync
    _, _, store, _ = service
    sync = HistorySync(store)
    class Session:
        cookies = []
        trxchart_order_reason = 'session_expired'
    sync.order_sent(Session(), 'fixture-token', {'active': True, 'status': 'connected', 'balance_current': True}, 0, 'rejected')
    revision, config = sync.read()
    assert not config['active'] and config['status'] == 'expired' and not config['balance_current']
    Session.trxchart_order_reason = 'permission_denied'
    sync.order_sent(Session(), 'fixture-token', {'active': True, 'status': 'connected'}, revision, 'rejected')
    assert sync.public()['active']
