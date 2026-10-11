"""Offline fixtures: fast provider reads, unresolved orders and exact receipts."""
import copy
import json
from uuid import uuid4

import pytest

from tests_admin_dashboard import admin, login, headers
from tests_trxchart_account_sync import setup, connect_body, decoded, Response, TOKEN
from tests_trxchart_order import service, place, OrderService, Response as OrderResponse
from admin_dashboard import AdminStore
from trade_order_tracking import receipt, result_for
from trxchart_account_sync import HistorySync, ProviderError
from trade_journal import normalize


def provider_row(state=-1, number=-1, ident='provider-order'):
    return {'addTime': '2026-10-11 17:00:00', 'issueNumber': '20261011103010700',
            'orderId': ident, 'selectType': 'big', 'amount': 100,
            'profitAmount': 196 if state == 1 else 0, 'state': state, 'number': number}


@pytest.mark.parametrize('placeholder', [-1, '-1', '', '-', None, 'provider-not-published'])
def test_pending_unpublished_number_does_not_freeze_real_sync(placeholder):
    rows = HistorySync.provider_rows({'success': True, 'list': [provider_row(number=placeholder)]}, 'real')
    assert rows[0]['state'] == -1 and rows[0]['pnl_minor'] is None and rows[0]['number'] is None


@pytest.mark.parametrize('state', ['-1', '0', '1'])
def test_canonical_provider_state_strings_are_safe(state):
    row = provider_row(state=int(state), number=8)
    row['state'] = state
    assert HistorySync.provider_rows({'success': True, 'list': [row]}, 'real')[0]['state'] == int(state)


def test_fast_path_reads_one_history_without_waiting_for_demo_or_wallet(admin, monkeypatch):
    client, store, provider = setup(admin)
    login(client)
    assert client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client)).status_code == 200
    clock = [1000.0]
    monkeypatch.setattr('trxchart_account_sync.time.monotonic', lambda: clock[0])
    sync = store.history_sync
    sync.last_wallet_sync = clock[0]
    sync.watch_trade()
    provider.pending = False
    provider.bad_demo = True
    provider.wallet_status = 503
    provider.calls.clear()
    sync.sync_once()
    assert [c[:2] for c in provider.calls] == [('GET', '/api/bet/history?size=500')]
    assert decoded(store, 'trade_journal')['rows'][0]['state'] == 1
    assert sync.poll_delay() == 2 and sync.last_fetch_ms == 0
    assert sync.timing()['status'] == 'connected'
    sync.failures = 9
    assert sync.poll_delay() == 15
    clock[0] += 21
    assert sync.poll_delay() == 900


def test_trade_watch_renews_without_waking_every_browser_poll(admin, monkeypatch):
    _, store, _ = setup(admin)
    now = [1000.0]
    monkeypatch.setattr('trxchart_account_sync.time.monotonic', lambda: now[0])
    sync = store.history_sync
    sync.wake.clear();sync.watch_trade();assert sync.wake.is_set()
    sync.wake.clear();now[0] += 1;sync.watch_trade();assert not sync.wake.is_set()
    now[0] += 20;assert not sync.fast()


def test_rotated_token_refresh_is_read_only_and_bounded(admin, monkeypatch):
    client, store, provider = setup(admin)
    login(client)
    client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client))
    sync = store.history_sync
    expected, config = sync.read();config['token'] = 'stale-token';sync.save(config, expected, 'fixture')
    original = sync.request
    calls = []
    def request(session, method, path, **kwargs):
        calls.append((method, path))
        if path == '/api/bet/history?size=500' and kwargs['headers']['X-API-Token'] == 'stale-token':
            raise ProviderError('unavailable', path, 403)
        return original(session, method, path, **kwargs)
    sync.request = request
    sync.watch_trade();sync.last_wallet_sync = 1e100
    sync.sync_once()
    assert calls == [('GET', '/api/bet/history?size=500'), ('GET', '/'), ('GET', '/api/bet/history?size=500')]
    assert decoded(store, 'trxchart_account')['token'] == TOKEN
    assert sync.public()['active']


def test_conflicting_old_settlement_does_not_discard_unrelated_new_order(admin):
    client, store, provider = setup(admin);login(client)
    client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client))
    provider.pending = False;store.history_sync.sync_once()
    state = decoded(store, 'trade_journal');old = state['rows'][0]
    conflict = copy.deepcopy(old);conflict['pnl_minor'] += 100
    new = normalize([provider_row(state=1, number=8)], 'real', 'Asia/Yangon')[0]
    sync = store.history_sync
    expected, config = sync.read()
    with sync.session(config) as session:
        sync.commit(session, config, expected, [conflict, new], 'synced', ['real'], {}, wallet=False)
    rows = decoded(store, 'trade_journal')['rows']
    assert next(r for r in rows if r['id'] == old['id']) == old
    assert next(r for r in rows if r['id'] == new['id'])['state'] == 1
    assert 'held for review' in sync.public()['error']


def test_receipt_whitelisting_exact_ids_and_no_token_leak():
    data = receipt({'success': True, 'orderId': 20261011123456789,
                    'orderNumber': 'different-display-alias', 'issueNumber': 20261011103010700,
                    'token': 'SECRET', 'balance': 5000, 'phone': 'private'})
    assert data == {'provider_id': '20261011123456789', 'issue': '20261011103010700'}
    assert receipt({'orderId': 'one', 'data': {'orderId': 'two'}}) == {}
    assert receipt({'id': 'an-account-id', 'token': 'SECRET'}) == {}
    assert receipt({'order': {'id': 'explicit-order'}}) == {'provider_id': 'explicit-order'}


def test_wait_to_win_is_exact_and_survives_service_restart(service):
    svc, sync, store, clock = service
    sync.client.response = OrderResponse(body={'success': True, 'orderId': 'provider-order', 'issueNumber': '20261011103010700', 'token': 'SECRET'})
    request_id = str(uuid4())
    place(svc, request_id=request_id, amount=100)
    restarted = OrderService(sync, AdminStore(store.path), now=clock)
    pending = HistorySync.provider_rows({'success': True, 'list': [provider_row()]}, 'real')
    assert restarted.recent({'rows': pending})[0]['state'] == -1
    settled = normalize([provider_row(state=1, number=8)], 'real', 'Asia/Yangon')
    result = restarted.recent({'rows': settled})[0]
    assert result['id'] == request_id and result['state'] == 1 and result['pnl'] == 96
    assert result['result_source'] == 'order_id' and 'SECRET' not in json.dumps(result)
    place(restarted, request_id=request_id, amount=100)
    assert len(sync.client.calls) == 1


def test_no_guessing_an_order_from_similar_amount_side_or_time():
    order = {'side': 'BIG', 'stake': 100, 'outcome': 'accepted', 'provider_id': None, 'issue': None}
    rows = normalize([provider_row(state=1, number=8)], 'real', 'Asia/Yangon')
    assert result_for(order, rows) == (None, None)
    order['provider_id'] = 'some-other-order'
    assert result_for(order, rows) == (None, None)
    order['provider_id'] = None;order['issue'] = rows[0]['issue']
    assert result_for(order, rows)[1] == 'round'
    order['outcome'] = 'unknown'
    assert result_for(order, rows) == (None, None)


def test_private_trade_feed_watch_and_durable_wait_orders(admin):
    client, store, _, _ = admin
    assert client.get('/api/admin/trade-feed?watch=1').status_code == 401
    assert not store.history_sync.fast()
    login(client)
    with store.connect() as db:
        db.execute('INSERT INTO trxchart_orders VALUES(?,?,?,?,?,?,?)',
                   (str(uuid4()), '2026-10-11', 1791709200, 'BIG', 100, 'pending', None))
    data = client.get('/api/admin/trade-feed?watch=1').json
    assert store.history_sync.fast() and data['orders'][0]['state'] == -1
    assert data['orders'][0]['outcome'] == 'pending'
    assert data['sync']['interval_seconds'] == 2


def test_wallet_failure_cannot_hold_back_an_already_confirmed_result(admin):
    client, store, provider = setup(admin);login(client)
    client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client))
    provider.pending = False
    sync = store.history_sync;sync.watch_trade();sync.last_wallet_sync = 0
    original = sync.request
    def request(session, method, path, **kwargs):
        if path == '/api/user/info':
            assert decoded(store, 'trade_journal')['rows'][0]['state'] == 1
            raise ProviderError('unavailable', path, 503)
        return original(session, method, path, **kwargs)
    sync.request = request;sync.sync_once()
    assert sync.public()['status'] == 'connected'
    assert sync.public()['balance'] == '1000.00' and not sync.public()['balance_current']
    assert decoded(store, 'trade_journal')['rows'][0]['pnl_minor'] == 9600


def test_fast_expiry_erases_credentials_and_never_relogs_in(admin):
    client, store, provider = setup(admin);login(client)
    client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client))
    provider.calls.clear();provider.expired = True
    store.history_sync.watch_trade();store.history_sync.sync_once()
    assert not store.history_sync.public()['active']
    saved = decoded(store, 'trxchart_account')
    assert 'cookies' not in saved and 'token' not in saved
    assert all(method == 'GET' for method, _, _ in provider.calls)
    assert store.history_sync.public()['status'] == 'expired'


def test_order_session_refresh_preserves_latest_cookies_but_disconnect_wins(admin):
    client, store, provider = setup(admin);login(client)
    client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client))
    sync = store.history_sync;expected, config = sync.read()
    with sync.session(config) as session:
        session.cookies.set('after_post', 'fixture-rotated-cookie', domain='trxchart.com', secure=True)
        sync.order_sent(session, 'fresh-fixture-token', config, expected, 'accepted')
    saved = decoded(store, 'trxchart_account')
    assert saved['token'] == 'fresh-fixture-token' and not saved['balance_current']
    assert any(cookie['name'] == 'after_post' for cookie in saved['cookies'])
    expected, config = sync.read();sync.disconnect()
    with sync.session(config) as session:
        sync.order_sent(session, 'must-not-return', config, expected, 'accepted')
    assert not sync.public()['active'] and 'token' not in decoded(store, 'trxchart_account')


@pytest.mark.parametrize('change', [{'side': 'SMALL'}, {'stake': 200}, {'outcome': 'rejected'}, {'issue': '20261011103010001'}])
def test_explicit_receipt_cannot_settle_a_different_or_rejected_order(change):
    rows = normalize([provider_row(state=1, number=8)], 'real', 'Asia/Yangon')
    order = {'side': 'BIG', 'stake': 100, 'outcome': 'accepted', 'provider_id': 'provider-order'}
    assert result_for(order, rows)[1] == 'order_id'
    order.update(change)
    assert result_for(order, rows) == (None, None)
    order.update(side='BIG', stake=100, outcome='accepted')
    rows[0]['mode'] = 'demo'
    assert result_for(order, rows) == (None, None)


def test_invalid_provider_field_diagnostic_never_echoes_private_row():
    row = provider_row(state=1, number=8);row['amount'] = 'SECRET-private-value'
    with pytest.raises(ProviderError) as caught:
        HistorySync.provider_rows({'success': True, 'list': [row]}, 'real')
    assert 'SECRET' not in str(caught.value) and 'field:' in str(caught.value)
