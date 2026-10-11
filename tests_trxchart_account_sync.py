"""Offline provider fixtures: no real accounts or trades."""
import json
from urllib.parse import urlsplit

import pytest
import requests
from tests_admin_dashboard import admin, login, headers
from trxchart_account_sync import HistorySync, ProviderError, ORIGIN

TOKEN = 'fixture-header-secret-' + 'x' * 32
COOKIE = 'fixture-cookie-secret'
PASSWORD = 'fixture-password-never-save'


class Response:
    def __init__(self, value, status=200):
        self.status_code = status
        self.body = value.encode() if isinstance(value, str) else json.dumps(value).encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def iter_content(self, size): yield self.body


class Provider:
    def __init__(self):
        self.calls = []
        self.expired = False
        self.bad_demo = False
        self.demo_status = None
        self.pending = True
        self.balance = 1000
        self.wallet_status = 200
        self.wallet_success = True
        self.hook = None
    def factory(self):
        owner = self
        class Session:
            def __init__(self):
                self.headers = {}
                self.cookies = requests.cookies.RequestsCookieJar()
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def request(self, method, url, **kwargs):
                assert urlsplit(url).scheme == 'https' and urlsplit(url).netloc == 'trxchart.com'
                assert kwargs['allow_redirects'] is False and kwargs['timeout'] == (3, 8)
                path = url.removeprefix(ORIGIN)
                owner.calls.append((method, path, kwargs))
                if path == '/login':
                    return Response('<form>Provider login</form>')
                if path == '/api/auth/login':
                    assert kwargs['json']['password'] == PASSWORD
                    self.cookies.set('session', COOKIE, domain='trxchart.com', secure=True)
                    return Response({'success': True})
                assert self.cookies.get('session') == COOKIE
                if owner.expired:
                    return Response({'message': 'provider-secret-must-not-echo'}, 401)
                if path == '/':
                    return Response("const _AT = '" + TOKEN + "';")
                if path == '/api/session-alive':
                    return Response({'logged_out': False})
                assert kwargs['headers'] == {'X-API-Token': TOKEN}
                if path == '/api/user/info':
                    return Response({'success': owner.wallet_success, 'balance': owner.balance, 'phone': 'fixture-private-phone'}, owner.wallet_status)
                if path == '/api/demo/history?size=500':
                    if owner.demo_status:
                        return Response('SECRET-provider-body', owner.demo_status)
                    if owner.hook:
                        owner.hook()
                        owner.hook = None
                    return Response({'success': not owner.bad_demo, 'list': []})
                assert path == '/api/bet/history?size=500'
                return Response({'success': True, 'list': [{
                    'addTime': '2026-10-11 08:15:00', 'issueNumber': 20261011103010115,
                    'orderId': 20261011123456789, 'selectType': 'big', 'amount': 100,
                    'profitAmount': 196, 'state': -1 if owner.pending else 1, 'number': 8,
                    'token': TOKEN, 'password': PASSWORD,
                }]})
        return Session()


def connect_body(revision=0):
    return {'revision': revision, 'consent': True, 'phone': 'fixture@example.invalid',
            'password': PASSWORD, 'twofa': ''}


def decoded(store, name):
    return json.loads(store.vault.cipher.decrypt(store.private_get(name)['value'].encode()))


def setup(admin):
    client, store, _, _ = admin
    provider = Provider()
    store.history_sync = HistorySync(store, provider.factory)
    store.history_sync.start = lambda: None  # explicit offline worker control
    return client, store, provider


def test_auth_csrf_consent_encrypted_session_and_read_only_transport(admin):
    client, store, provider = setup(admin)
    path = '/api/admin/trxchart-account'
    for method in ('get', 'post', 'delete'):
        assert getattr(client, method)(path, json={}).status_code == 401
    assert client.post(path + '/refresh', json={}).status_code == 401
    login(client)
    assert client.put('/api/admin/trade-journal', json={'revision': 0, 'limits': {
        'tp': 125, 'sl': 350, 'timezone': 'Asia/Bangkok'}}, headers=headers(client)).status_code == 200
    assert client.post(path, json=connect_body()).status_code == 403
    assert client.delete(path).status_code == 403
    assert client.post(path, json={**connect_body(), 'consent': False}, headers=headers(client)).status_code == 400
    assert provider.calls == []
    result = client.post(path, json=connect_body(), headers=headers(client))
    assert result.status_code == 200 and result.json['active']
    for secret in (TOKEN, COOKIE, PASSWORD, 'fixture@example.invalid'):
        assert secret not in result.text
        assert secret not in client.get('/api/admin/backup').text
        assert secret not in client.get('/api/admin/events').text
        assert secret not in store.private_get('trxchart_account')['value']
    saved = decoded(store, 'trxchart_account')
    assert saved['token'] == TOKEN and saved['cookies'][0]['value'] == COOKIE
    assert PASSWORD not in json.dumps(saved)
    journal = decoded(store, 'trade_journal')
    assert journal['limits'] == {'tp': 125, 'sl': 350, 'timezone': 'Asia/Bangkok'}
    assert TOKEN not in json.dumps(journal) and PASSWORD not in json.dumps(journal)
    assert journal['rows'][0]['issue'] == '20261011103010115'
    assert journal['rows'][0]['external_id'] == '20261011123456789'
    assert journal['synced_at']['real'] == journal['synced_at']['demo']
    assert [x[:2] for x in provider.calls] == [('GET', '/login'), ('POST', '/api/auth/login'), ('GET', '/'),
        ('GET', '/api/session-alive'), ('GET', '/api/bet/history?size=500'), ('GET', '/'),
        ('GET', '/api/demo/history?size=500'), ('GET', '/'), ('GET', '/api/user/info')]
    with pytest.raises(ValueError, match='not allowed'):
        HistorySync.request(provider.factory(), 'POST', '/api/bet/place')
    with pytest.raises(ValueError, match='not allowed'):
        HistorySync.request(provider.factory(), 'GET', 'https://elsewhere.invalid/')


def test_polling_settlement_atomic_modes_expiry_and_no_relogin(admin):
    client, store, provider = setup(admin)
    login(client)
    assert client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client)).status_code == 200
    provider.pending = False
    provider.bad_demo = True
    previous = store.private_get('trade_journal')
    store.history_sync.sync_once()
    assert store.private_get('trade_journal') == previous
    assert store.history_sync.public()['status'] == 'invalid_data'
    provider.bad_demo = False
    store.history_sync.sync_once()
    journal = decoded(store, 'trade_journal')
    assert len(journal['rows']) == 1 and journal['rows'][0]['pnl_minor'] == 9600
    provider.expired = True
    store.history_sync.sync_once()
    assert store.history_sync.public()['status'] == 'expired'
    assert not store.history_sync.public()['active']
    assert TOKEN not in json.dumps(decoded(store, 'trxchart_account'))
    assert COOKIE not in json.dumps(decoded(store, 'trxchart_account'))
    calls = len(provider.calls)
    store.history_sync.sync_once()
    assert len(provider.calls) == calls
    assert sum(method == 'POST' for method, _, _ in provider.calls) == 1
    assert 'provider-secret' not in client.get('/api/admin/trxchart-account').text
    assert decoded(store, 'trade_journal')['rows'] == journal['rows']


def test_disconnect_discards_inflight_rows_and_prevents_account_mix(admin):
    client, store, provider = setup(admin)
    login(client)
    path = '/api/admin/trxchart-account'
    assert client.post(path, json=connect_body(), headers=headers(client)).status_code == 200
    previous = store.private_get('trade_journal')
    provider.pending = False
    provider.hook = store.history_sync.disconnect
    store.history_sync.sync_once()
    assert store.private_get('trade_journal') == previous
    assert not store.history_sync.public()['active']
    saved = decoded(store, 'trxchart_account')
    assert 'cookies' not in saved and 'token' not in saved
    body = connect_body(store.history_sync.public()['revision'])
    body['phone'] = 'different@example.invalid'
    calls = len(provider.calls)
    assert client.post(path, json=body, headers=headers(client)).status_code == 400
    assert len(provider.calls) == calls
    assert client.post(path + '/refresh', json={}, headers=headers(client)).status_code == 400


def test_provider_errors_are_redacted_and_redirects_never_followed():
    class Session:
        def request(self, *args, **kwargs):
            assert kwargs['allow_redirects'] is False
            raise requests.ConnectionError('SECRET-cookie-and-password')
    with pytest.raises(ProviderError) as caught:
        HistorySync.request(Session(), 'GET', '/')
    assert 'SECRET' not in str(caught.value)
    class Redirect:
        def request(self, *args, **kwargs): return Response('SECRET', 302)
    with pytest.raises(ProviderError) as caught:
        HistorySync.request(Redirect(), 'GET', '/')
    assert caught.value.code == 'expired' and 'SECRET' not in str(caught.value)


def test_login_preflight_is_private_credential_free_and_redacted(admin):
    client, store, provider = setup(admin)
    path = '/api/admin/trxchart-account/check'
    assert client.get(path).status_code == 401
    login(client)
    result = client.get(path)
    assert result.status_code == 200 and result.json['ok']
    assert [x[:2] for x in provider.calls] == [('GET', '/login')]
    assert not store.history_sync.public()['active']
    class Forbidden:
        def request(self, *args, **kwargs): return Response('SECRET-body', 403)
    with pytest.raises(ProviderError) as caught:
        HistorySync.request(Forbidden(), 'GET', '/login')
    assert caught.value.code == 'unavailable'
    assert 'login page' in str(caught.value) and 'HTTP 403' in str(caught.value)
    assert 'SECRET' not in str(caught.value)


def test_page_token_supports_dotted_format_without_header_injection(admin):
    _, store, _ = setup(admin)
    sync = store.history_sync
    class Page:
        def __init__(self, value): self.value = value
        def request(self, *args, **kwargs): return Response(self.value)
    token = 'fixture.segment-' + 'x' * 300 + '.signature='
    assert sync.token(Page('const _AT = "' + token + '";')) == token
    for value in ('no token', "const _AT = 'bad\\r\\nAuthorization: injection';"):
        with pytest.raises(ProviderError) as caught:
            sync.token(Page(value))
        assert 'account page token' in str(caught.value)
        assert 'Authorization' not in str(caught.value)


def test_demo_unavailability_preserves_verified_real_and_recovers(admin):
    client, store, provider = setup(admin)
    login(client)
    provider.demo_status = 409
    result = client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client))
    assert result.status_code == 200 and result.json['active']
    assert 'Demo history' in result.json['error'] and 'HTTP 409' in result.json['error']
    assert 'SECRET' not in result.text
    journal = decoded(store, 'trade_journal')
    assert len(journal['rows']) == 1
    assert set(journal['synced_at']) == {'real'}
    provider.demo_status = None
    store.history_sync.sync_once()
    journal = decoded(store, 'trade_journal')
    assert set(journal['synced_at']) == {'real', 'demo'}
    assert store.history_sync.public()['error'] is None
    assert sum(method == 'POST' for method, _, _ in provider.calls) == 1


def test_provider_balance_is_encrypted_and_never_derived_from_profit(admin):
    client, store, provider = setup(admin)
    login(client)
    provider.balance = '12,500.50 MMK'
    result = client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client))
    assert result.status_code == 200
    assert result.json['balance'] == '12500.50' and result.json['balance_current']
    assert decoded(store, 'trxchart_account')['balance'] == '12500.50'
    assert '12500.50' not in store.private_get('trxchart_account')['value']
    provider.balance = None
    store.history_sync.sync_once()
    public = store.history_sync.public()
    assert public['balance'] == '12500.50' and not public['balance_current']
    provider.balance = 0
    store.history_sync.sync_once()
    assert store.history_sync.public()['balance'] == '0.00'
    assert store.history_sync.public()['balance_current']
    store.history_sync.disconnect()
    assert store.history_sync.public()['balance'] is None


@pytest.mark.parametrize('status', [403, 409, 500])
def test_wallet_outage_preserves_history_and_marks_balance_stale(admin, status):
    client, store, provider = setup(admin)
    login(client)
    provider.balance = '12500.50'
    assert client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client)).status_code == 200
    provider.wallet_status = status
    provider.pending = False
    store.history_sync.sync_once()
    assert decoded(store, 'trade_journal')['rows'][0]['pnl_minor'] == 9600
    public = store.history_sync.public()
    assert public['active'] and public['balance'] == '12500.50' and not public['balance_current']
    assert 'balance could not be refreshed' in public['error']
    assert 'fixture-private-phone' not in json.dumps(public)


def test_wallet_session_expiry_disables_orders_and_drops_private_balance(admin):
    client, store, provider = setup(admin)
    login(client)
    provider.balance = '12500.50'
    assert client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client)).status_code == 200
    provider.wallet_status = 401
    store.history_sync.sync_once()
    public = store.history_sync.public()
    assert not public['active'] and public['status'] == 'expired' and public['balance'] is None


def test_unsuccessful_wallet_response_is_not_presented_as_balance(admin):
    client, store, provider = setup(admin)
    login(client)
    provider.balance = '12500.50'
    provider.wallet_success = False
    result = client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client))
    assert result.status_code == 200 and result.json['active']
    assert result.json['balance'] is None and not result.json['balance_current']
