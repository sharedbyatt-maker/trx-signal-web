"""Read-only TRXChart history client. Passwords are used once, never persisted."""
import copy
import hashlib
import json
import re
import threading
import time
from datetime import datetime, timezone

import requests
from trade_journal import DEFAULT_LIMITS, normalize, merge
from trxchart_balance import from_page as page_balance, from_json as json_balance
from trade_updates import observe

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
    def __init__(self, code, stage=None, status=None, field=None):
        self.code = code
        self.stage, self.status = stage, status
        # Only fixed stage labels and integer HTTP statuses can reach the UI.
        stages = {'/login': 'login page', '/api/auth/login': 'account login',
                  '/': 'account page', '/api/session-alive': 'session check',
                  '/api/bet/history?size=500': 'Real history',
                  '/api/demo/history?size=500': 'Demo history',
                  'token': 'account page token'}
        detail = stages.get(stage)
        if detail:
            suffix = f' (HTTP {status})' if type(status) is int and 100 <= status <= 599 else ''
            message = f'TRXChart {detail} failed{suffix}. ' + MESSAGES[code]
        else:
            message = MESSAGES[code]
        if field in ('time', 'issue', 'side', 'state', 'amount', 'payout', 'number', 'order ID'):
            message += ' Check provider history field: ' + field + '.'
        super().__init__(message)


class HistorySync:
    def __init__(self, store, session_factory=requests.Session):
        self.store = store
        self.session_factory = session_factory
        self.operation = threading.Lock()
        self.thread_lock = threading.Lock()
        self.wake = threading.Event()
        self.thread = None
        self.failures = 0
        self.follow_until = 0
        self.last_full_sync = 0
        self.last_wallet_sync = 0
        self.last_fetch_ms = None
        self.trade_view_until = 0
        self.full_refresh_requested = False

    def follow_orders(self):
        # Faster read-only checks for three minutes; never resubmit a bet.
        self.follow_until = time.monotonic() + 180
        self.wake.set()

    def order_sent(self, client, token, config, expected, outcome):
        with self.store.lock:
            if self.store.private_get('trxchart_account')['revision'] != expected:
                return  # A disconnect must win over this in-flight POST.
            config.update(cookies=self.cookies(client), token=token)
            if getattr(client, 'trxchart_order_reason', None) == 'session_expired':
                config.update(active=False, status='expired', balance_current=False, error=MESSAGES['expired'])
            elif outcome != 'rejected':
                config['balance_current'] = False
            self.save(config, expected, 'order_session_updated')

    def watch_trade(self):
        was_fast = self.fast()
        self.trade_view_until = time.monotonic() + 20
        if not was_fast:
            self.wake.set()

    def fast(self):
        return time.monotonic() < max(self.follow_until, self.trade_view_until)

    def poll_delay(self):
        if self.fast():
            return min(15, 2 * 2 ** min(self.failures, 3))
        return min(900, 60 * 2 ** min(self.failures, 4))

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
                'worker_alive': bool(self.thread and self.thread.is_alive()),
                'balance': value.get('balance'), 'balance_at': value.get('balance_at'),
                'balance_current': bool(value.get('active') and value.get('balance_current')),
                'balance_currency': 'MMK'}

    def timing(self):
        public = self.public()
        return {'last_sync': public['last_sync'], 'status': public['status'],
                'active': public['active'], 'error': public['error'],
                'worker_alive': public['worker_alive'], 'interval_seconds': self.poll_delay(),
                'provider_fetch_ms': self.last_fetch_ms}

    @staticmethod
    def provider_rows(data, mode):
        rows = data.get('list')
        if data.get('success') is not True or not isinstance(rows, list) or len(rows) > 5000:
            raise ProviderError('invalid_data')
        clean = []
        for row in rows:
            if not isinstance(row, dict):
                raise ProviderError('invalid_data')
            item = {key: row[key] for key in FIELDS if key in row}
            for key in ('issueNumber', 'orderId', 'orderNumber', 'id'):
                if type(item.get(key)) is int:
                    item[key] = str(item[key])
            if item.get('state') in ('-1', '0', '1'):
                item['state'] = int(item['state'])
            # An unclosed round has no published draw number. Providers may send
            # -1, empty strings or other placeholders while an order is pending.
            if type(item.get('state')) is int and item['state'] == -1:
                item['number'] = None
            elif item.get('number') in (-1, '-1', '', '-'):
                item['number'] = None
            clean.append(item)
        try:
            return normalize(clean, mode, 'Asia/Yangon') if clean else []
        except (ValueError, TypeError) as exc:
            reasons = {'addTime': 'time', 'issueNumber': 'issue', 'BIG / SMALL': 'side',
                       'state must': 'state', 'Stake': 'amount', 'monetary': 'payout',
                       'Result number': 'number', 'order identifier': 'order ID',
                       'Duplicate or ambiguous': 'order ID'}
            field = next((value for key, value in reasons.items() if key in str(exc)), None)
            raise ProviderError('invalid_data', field=field) from None

    def fast_history(self, client, config):
        token = config.get('token')
        if not token:
            token = self.token(client)
        started = time.monotonic()
        try:
            data = self.request(client, 'GET', '/api/bet/history?size=500', headers={'X-API-Token': token})
        except ProviderError as exc:
            if exc.status not in (401, 403):
                raise
            # One read-only token refresh. A POST is never repeated here.
            token = self.token(client)
            data = self.request(client, 'GET', '/api/bet/history?size=500', headers={'X-API-Token': token})
        config['token'] = token
        incoming = self.provider_rows(data, 'real')
        self.last_fetch_ms = round((time.monotonic() - started) * 1000)
        return incoming

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
                   'GET': {'/', '/login', '/api/session-alive', '/api/bet/history?size=500',
                           '/api/demo/history?size=500', '/api/user/info'}}
        if path not in allowed.get(method, set()):
            raise ValueError('Read-only endpoint is not allowed.')
        try:
            response = client.request(method, ORIGIN + path, timeout=(3, 8),
                                      allow_redirects=False, stream=True, **kwargs)
            with response:
                if response.status_code == 403:
                    raise ProviderError('unavailable', path, 403)
                if response.status_code == 401 or 300 <= response.status_code < 400:
                    raise ProviderError('login_failed' if path == '/api/auth/login' else 'expired', path, response.status_code)
                if response.status_code != 200:
                    raise ProviderError('login_failed' if path == '/api/auth/login' and response.status_code == 400 else 'unavailable', path, response.status_code)
                parts, size = [], 0
                for chunk in response.iter_content(65536):
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ProviderError('invalid_data')
                    parts.append(chunk)
                text = b''.join(parts).decode('utf-8')
                if path in ('/', '/login'):
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
            raise ProviderError('unavailable', path) from None

    def token(self, client):
        page = self.request(client, 'GET', '/')
        found = re.search(r"(?:const|let|var)\s+_AT\s*=\s*(['\"])([a-zA-Z0-9_.=-]{16,4096})\1", page)
        if not found:
            raise ProviderError('expired', 'token')
        client.trxchart_balance = page_balance(page)
        return found[2]

    def check_login_page(self):
        # Credential-free reachability check; no login or session mutation.
        with self.session() as client:
            self.request(client, 'GET', '/login')
        return {'ok': True, 'stage': 'login page', 'http_status': 200}

    def histories(self, client, token, modes=('real', 'demo')):
        alive = self.request(client, 'GET', '/api/session-alive')
        if alive.get('logged_out'):
            raise ProviderError('expired', '/api/session-alive')
        balance = json_balance(alive)
        if balance is not None:
            client.trxchart_balance = balance
        incoming, completed, warnings = [], [], {}
        last_failure = None
        for mode in modes:
            path = '/api/bet/history?size=500' if mode == 'real' else '/api/demo/history?size=500'
            try:
                # Page tokens may change after a provider request. Obtain the current
                # token in this same session before reading the second history mode.
                # Keep the current account balance if the second page omits it.
                known_balance = getattr(client, 'trxchart_balance', None)
                mode_token = token if mode == 'real' else self.token(client)
                if getattr(client, 'trxchart_balance', None) is None:
                    client.trxchart_balance = known_balance
                data = self.request(client, 'GET', path, headers={'X-API-Token': mode_token})
            except ProviderError as exc:
                if exc.code != 'unavailable':
                    raise  # Expiry and malformed data must not produce a partial save.
                warnings[mode] = str(exc)
                last_failure = exc
                continue
            incoming.extend(self.provider_rows(data, mode))
            completed.append(mode)
        if not completed:
            raise last_failure or ProviderError('unavailable')
        # The provider's rendered REAL balance uses GET /api/user/info. Read it
        # after histories so an optional wallet outage cannot discard trade rows.
        known_balance = getattr(client, 'trxchart_balance', None)
        try:
            balance_token = self.token(client)
            wallet = self.request(client, 'GET', '/api/user/info', headers={'X-API-Token': balance_token})
            balance = json_balance(wallet) if wallet.get('success') is True else None
            client.trxchart_balance = balance if balance is not None else known_balance
            if balance is None and known_balance is None:
                warnings['balance'] = 'TRXChart account balance is unavailable; existing history is preserved.'
        except ProviderError as exc:
            if exc.code == 'expired':
                raise  # A genuine expired session must never keep order buttons active.
            client.trxchart_balance = None
            warnings['balance'] = 'TRXChart account balance could not be refreshed; existing history is preserved.'
        return incoming, completed, warnings

    def commit(self, client, config, expected, incoming, action, completed, warnings, wallet=True):
        with self.store.lock:
            if self.store.private_get('trxchart_account')['revision'] != expected:
                raise RuntimeError('Connection changed. Reconnect if needed.')
            state = self.store.private_get('trade_journal')
            try:
                journal = json.loads(self.store.vault.cipher.decrypt(state['value'].encode())) if state['value'] else {'rows': [], 'limits': copy.deepcopy(DEFAULT_LIMITS)}
            except Exception:
                raise ProviderError('storage') from None
            previous = journal['rows']
            try:
                journal['rows'], counts = merge(previous, incoming)
            except ValueError as exc:
                if 'conflict' not in str(exc).lower():
                    raise
                # Hold disputed historical rows; an old conflict must not freeze
                # unrelated new orders or overwrite a previously confirmed result.
                kept, counts, held = previous, {'added': 0, 'updated': 0, 'unchanged': 0}, 0
                for row in incoming:
                    try:
                        kept, change = merge(kept, [row])
                        for key in counts:
                            counts[key] += change[key]
                    except ValueError as conflict:
                        if 'conflict' not in str(conflict).lower():
                            raise
                        held += 1
                journal['rows'] = kept
                warnings['records'] = f'{held} conflicting historical record(s) held for review; other results updated.'
            now = stamp()
            observe(journal, previous, now, 'real' in completed)
            journal['imported_at'] = now
            synced_at = journal.setdefault('synced_at', {})
            for mode in completed:
                synced_at[mode] = now
            self.store.private_save('trade_journal', self.store.vault.cipher.encrypt(json.dumps(journal).encode()).decode(),
                                    state['revision'], {'action': 'server_history_synced', **counts})
            config.update(cookies=self.cookies(client), active=True, status='connected',
                          last_sync=now, error=' '.join(warnings.values()) or None)
            if wallet:
                balance = getattr(client, 'trxchart_balance', None)
                config['balance_current'] = balance is not None
                if balance is not None:
                    config.update(balance=balance, balance_at=now)
            self.save(config, expected, action)
            self.failures = 0

    def fast_wallet(self, client):
        # REAL rows have already committed. Wallet work cannot hold their result
        # hostage, and its independent cadence avoids five requests on every poll.
        if time.monotonic() - self.last_wallet_sync < 15:
            return
        self.last_wallet_sync = time.monotonic()
        expected, config = self.read()
        try:
            data = self.request(client, 'GET', '/api/user/info', headers={'X-API-Token': config['token']})
            balance = json_balance(data) if data.get('success') is True else None
        except ProviderError:
            balance = None  # History is the authenticated session authority.
        config['cookies'] = self.cookies(client)
        config['balance_current'] = balance is not None
        if balance is not None:
            config.update(balance=balance, balance_at=stamp())
        self.save(config, expected, 'balance_refreshed')

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
                # Match the normal login flow, including any initial session cookie.
                self.request(client, 'GET', '/login')
                result = self.request(client, 'POST', '/api/auth/login',
                                      json={'phone': phone.strip(), 'password': password, 'twofa': twofa or None})
                if result.get('success') is not True:
                    raise ProviderError('login_failed', '/api/auth/login')
                token = self.token(client)
                incoming, completed, warnings = self.histories(client, token)
                self.commit(client, {'token': token, 'account_tag': tag, 'connected_at': stamp()},
                            expected, incoming, 'connected', completed, warnings)
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
            with self.thread_lock:
                full_refresh = self.full_refresh_requested
                self.full_refresh_requested = False
            with self.session(config) as client:
                if self.fast() and not full_refresh:
                    incoming = self.fast_history(client, config)
                    self.commit(client, config, expected, incoming, 'synced', ['real'], {}, wallet=False)
                    self.fast_wallet(client)
                    return
                # Refresh the CSRF/API token in this same session, never log in automatically.
                config['token'] = self.token(client)
                modes = ('real', 'demo')
                incoming, completed, warnings = self.histories(client, config['token'], modes)
                self.commit(client, config, expected, incoming, 'synced', completed, warnings)
                if len(modes) == 2:
                    self.last_full_sync = time.monotonic()
        except (ProviderError, ValueError) as exc:
            self.failures += 1
            with self.store.lock:
                current, config = self.read()
                if current == expected and config.get('active'):
                    config['balance_current'] = False
                    code = exc.code if isinstance(exc, ProviderError) else 'invalid_data'
                    if code == 'expired':
                        config = {k: config[k] for k in ('account_tag', 'last_sync', 'connected_at') if k in config}
                        config['active'] = False
                    config.update(status=code, error=str(exc) if isinstance(exc, ProviderError) else MESSAGES[code])
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
                    delay = self.poll_delay()
                    self.wake.wait(delay)
                    self.wake.clear()
            self.thread = threading.Thread(target=loop, name='trxchart-history-sync', daemon=True)
            self.thread.start()

    def refresh(self, mode='real'):
        if mode not in ('real', 'demo'):
            raise ValueError('Choose real or demo history.')
        if not self.public()['active']:
            raise ValueError('Connect TRXChart first.')
        if mode == 'demo':
            with self.thread_lock:
                self.full_refresh_requested = True
        else:
            self.watch_trade()
        self.last_wallet_sync = 0
        self.wake.set()
        return self.public()
