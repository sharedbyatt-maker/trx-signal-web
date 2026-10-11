"""Read-only TRXChart history client. Passwords are used once, never persisted."""
import copy
import hashlib
import json
import re
import threading
from datetime import datetime, timezone

import requests
from trade_journal import DEFAULT_LIMITS, normalize, merge

ORIGIN = 'https://trxchart.com'
FIELDS = ('addTime', 'issueNumber', 'selectType', 'amount', 'profitAmount', 'state',
          'number', 'orderId', 'orderNumber', 'id')
MESSAGES = {
    'expired': 'TRXChart session expired or was signed out elsewhere. Connect again.',
    'login_failed': 'TRXChart did not accept this login. Check your credentials and 2FA.',
    'unavailable': 'TRXChart is unavailable. Existing results are preserved; sync will retry.',
    'invalid_data': 'TRXChart returned unsupported history data. Existing results are preserved.',
    'storage': 'Private sync storage is unreadable. Reconnect to replace the session.',
}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


class ProviderError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(MESSAGES[code])


class HistorySync:
    def __init__(self, store, session_factory=requests.Session):
        self.store = store
        self.session_factory = session_factory
        self.operation = threading.Lock()
        self.thread_lock = threading.Lock()
        self.wake = threading.Event()
        self.thread = None
        self.failures = 0

    def read(self):
        state = self.store.private_get('trxchart_account')
        if not state['value']:
            return state['revision'], {'active': False, 'status': 'disconnected'}
        try:
            value = json.loads(self.store.vault.cipher.decrypt(state['value'].encode()))
            if not isinstance(value, dict):
                raise ValueError()
            return state['revision'], value
        except Exception:
            raise ProviderError('storage') from None

    def save(self, value, revision, action):
        payload = self.store.vault.cipher.encrypt(json.dumps(value).encode()).decode()
        return self.store.private_save('trxchart_account', payload, revision,
                                       {'action': action, 'status': value['status']})

    def public(self):
        try:
            revision, value = self.read()
        except ProviderError:
            revision = self.store.private_get('trxchart_account')['revision']
            value = {'active': False, 'status': 'storage', 'error': MESSAGES['storage']}
        return {'revision': revision, 'active': bool(value.get('active')),
                'status': value.get('status', 'disconnected'),
                'last_sync': value.get('last_sync'), 'connected_at': value.get('connected_at'),
                'error': value.get('error'), 'interval_seconds': 60,
                'worker_alive': bool(self.thread and self.thread.is_alive())}

    def session(self, value=None):
        client = self.session_factory()
        client.headers.update({'Origin': ORIGIN, 'Referer': ORIGIN + '/',
                               'Accept': 'application/json'})
        for cookie in (value or {}).get('cookies', []):
            if cookie.get('domain', '').lstrip('.') != 'trxchart.com':
                raise ProviderError('storage')
            client.cookies.set(cookie['name'], cookie['value'], domain=cookie['domain'],
                               path=cookie.get('path', '/'), secure=cookie.get('secure', True),
                               expires=cookie.get('expires'))
        return client

    @staticmethod
    def cookies(client):
        return [{'name': c.name, 'value': c.value, 'domain': c.domain,
                 'path': c.path, 'secure': c.secure, 'expires': c.expires}
                for c in client.cookies if c.domain.lstrip('.') == 'trxchart.com']

    @staticmethod
    def request(client, method, path, **kwargs):
        # Fixed origin and allowlist: a session can never reach another host or place an order.
        allowed = {'POST': {'/api/auth/login'},
                   'GET': {'/', '/api/session-alive', '/api/bet/history?size=500',
                           '/api/demo/history?size=500'}}
        if path not in allowed.get(method, set()):
            raise ValueError('Read-only endpoint is not allowed.')
        try:
            response = client.request(method, ORIGIN + path, timeout=(3, 8),
                                      allow_redirects=False, stream=True, **kwargs)
            with response:
                if response.status_code in (401, 403) or 300 <= response.status_code < 400:
                    raise ProviderError('login_failed' if path == '/api/auth/login' else 'expired')
                if response.status_code != 200:
                    raise ProviderError('login_failed' if path == '/api/auth/login' and response.status_code == 400 else 'unavailable')
                parts, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ProviderError('invalid_data')
                    parts.append(chunk)
                text = b''.join(parts).decode('utf-8')
                if path == '/':
                    return text
                data = json.loads(text)
                if not isinstance(data, dict):
                    raise ProviderError('invalid_data')
                return data
        except ProviderError:
            raise
        except (ValueError, UnicodeError):
            raise ProviderError('invalid_data') from None
        except Exception:
            # Never expose provider responses, URLs, request bodies or exception text.
            raise ProviderError('unavailable') from None

    def token(self, client):
        page = self.request(client, 'GET', '/')
        found = re.search(r"(?:const|let|var)\s+_AT\s*=\s*(['\"])([a-zA-Z0-9_-]{16,256})\1", page)
        if not found:
            raise ProviderError('expired')
        return found[2]

    def histories(self, client, token):
        alive = self.request(client, 'GET', '/api/session-alive')
        if alive.get('logged_out'):
            raise ProviderError('expired')
        incoming = []
        for mode in ('real', 'demo'):
            path = '/api/bet/history?size=500' if mode == 'real' else '/api/demo/history?size=500'
            data = self.request(client, 'GET', path, headers={'X-API-Token': token})
            rows = data.get('list')
            if data.get('success') is not True or not isinstance(rows, list) or len(rows) > 5000:
                raise ProviderError('invalid_data')
            clean = []
            for row in rows:
                if not isinstance(row, dict):
                    raise ProviderError('invalid_data')
                item = {key: row[key] for key in FIELDS if key in row}
                # Python retains exact JSON integers; convert identifiers before normalizing.
                for key in ('issueNumber', 'orderId', 'orderNumber', 'id'):
                    if type(item.get(key)) is int:
                        item[key] = str(item[key])
                clean.append(item)
            try:
                incoming.extend(normalize(clean, mode, 'Asia/Yangon') if clean else [])
            except (ValueError, TypeError):
                raise ProviderError('invalid_data') from None
        return incoming

    def commit(self, client, config, expected, incoming, action):
        with self.store.lock:
            if self.store.private_get('trxchart_account')['revision'] != expected:
                raise RuntimeError('Connection changed. Reconnect if needed.')
            state = self.store.private_get('trade_journal')
            try:
                journal = json.loads(self.store.vault.cipher.decrypt(state['value'].encode())) if state['value'] else {'rows': [], 'limits': copy.deepcopy(DEFAULT_LIMITS)}
            except Exception:
                raise ProviderError('storage') from None
            journal['rows'], counts = merge(journal['rows'], incoming)
            now = stamp()
            journal['imported_at'] = now
            journal['synced_at'] = {'real': now, 'demo': now}
            self.store.private_save('trade_journal', self.store.vault.cipher.encrypt(json.dumps(journal).encode()).decode(),
                                    state['revision'], {'action': 'server_history_synced', **counts})
            config.update(cookies=self.cookies(client), active=True, status='connected',
                          last_sync=now, error=None)
            self.save(config, expected, action)
            self.failures = 0

    def connect(self, data):
        if not isinstance(data, dict) or data.get('consent') is not True:
            raise ValueError('Approve encrypted session storage and read-only history access first.')
        phone, password, twofa = data.get('phone'), data.get('password'), data.get('twofa', '')
        if not isinstance(phone, str) or not 1 <= len(phone.strip()) <= 320 or not isinstance(password, str) or not 1 <= len(password) <= 1024:
            raise ValueError('Enter your TRXChart phone/email and password.')
        if not isinstance(twofa, str) or (twofa and not re.fullmatch(r'\d{6}', twofa)):
            raise ValueError('2FA must be empty or six digits.')
        if not self.operation.acquire(blocking=False):
            raise RuntimeError('A sync is running. Try connecting again shortly.')
        try:
            expected = self.store.private_get('trxchart_account')['revision']
            if type(data.get('revision')) is not int or data['revision'] != expected:
                raise RuntimeError('Connection changed. Refresh before connecting.')
            tag = hashlib.sha256(phone.strip().casefold().encode()).hexdigest()
            try:
                _, previous = self.read()
            except ProviderError:
                previous = {}
            if previous.get('account_tag') and previous['account_tag'] != tag:
                raise ValueError('This journal is linked to another account. Account histories cannot be mixed.')
            with self.session() as client:
                result = self.request(client, 'POST', '/api/auth/login',
                                      json={'phone': phone.strip(), 'password': password, 'twofa': twofa or None})
                if result.get('success') is not True:
                    raise ProviderError('login_failed')
                token = self.token(client)
                incoming = self.histories(client, token)
                self.commit(client, {'token': token, 'account_tag': tag, 'connected_at': stamp()},
                            expected, incoming, 'connected')
        finally:
            self.operation.release()
        self.wake.set()
        return self.public()

    def disconnect(self):
        with self.store.lock:
            revision = self.store.private_get('trxchart_account')['revision']
            try:
                _, previous = self.read()
            except ProviderError:
                previous = {}
            self.save({'active': False, 'status': 'disconnected',
                       'account_tag': previous.get('account_tag'), 'last_sync': previous.get('last_sync')},
                      revision, 'disconnected')
        self.wake.set()
        return self.public()

    def sync_once(self):
        if not self.operation.acquire(blocking=False):
            return
        expected = None
        try:
            expected, config = self.read()
            if not config.get('active'):
                return
            with self.session(config) as client:
                # Refresh the CSRF/API token in this same session, never log in automatically.
                config['token'] = self.token(client)
                incoming = self.histories(client, config['token'])
                self.commit(client, config, expected, incoming, 'synced')
        except (ProviderError, ValueError) as exc:
            self.failures += 1
            with self.store.lock:
                current, config = self.read()
                if current == expected and config.get('active'):
                    code = exc.code if isinstance(exc, ProviderError) else 'invalid_data'
                    if code == 'expired':
                        config = {k: config[k] for k in ('account_tag', 'last_sync', 'connected_at') if k in config}
                        config['active'] = False
                    config.update(status=code, error=MESSAGES[code])
                    self.save(config, current, 'sync_failed')
        except RuntimeError:
            pass  # Disconnect/reconnect won the revision lease; drop this in-flight result.
        finally:
            self.operation.release()

    def start(self):
        with self.thread_lock:
            if self.thread and self.thread.is_alive():
                return
            def loop():
                while True:
                    try:
                        self.sync_once()
                    except Exception:
                        self.failures += 1  # Isolated from the web request and signal engines.
                    delay = min(900, 60 * 2 ** min(self.failures, 4))
                    self.wake.wait(delay)
                    self.wake.clear()
            self.thread = threading.Thread(target=loop, name='trxchart-history-sync', daemon=True)
            self.thread.start()

    def refresh(self):
        if not self.public()['active']:
            raise ValueError('Connect TRXChart first.')
        self.wake.set()
        return self.public()
