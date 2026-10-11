"""Manual practice-order client for TRXChart (POST /api/bet).

Deliberately separate from HistorySync, whose allowlist stays read-only.
Every order needs an explicit button press plus server-side limits:
kill switch, per-order cap, daily count/total caps, minimum spacing.
Orders are never retried automatically; an ambiguous outcome is reported
as 'unknown' and still counts against the limits.
"""
import os
import threading
import time
from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from trxchart_account_sync import ORIGIN, ProviderError

ENDPOINT = '/api/bet'
SIDES = ('BIG', 'SMALL')


class OrderError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status


def _env_int(name, default, low, high):
    try:
        value = int(os.environ.get(name, default))
    except (TypeError, ValueError):
        value = default
    return max(low, min(value, high))


class OrderService:
    def __init__(self, history_sync, store, clock=time.monotonic, now=None):
        self.sync = history_sync
        self.store = store
        self.clock = clock
        self.now = now or (lambda: datetime.now(ZoneInfo('Asia/Bangkok')))
        self.lock = threading.Lock()
        self.day = None
        self.count = 0
        self.total = 0
        self.last = None  # monotonic time of the last attempt

    @staticmethod
    def limits():
        return {'enabled': os.environ.get('TRX_ORDER_ENABLED') == '1',
                'max_amount': _env_int('TRX_ORDER_MAX_AMOUNT', 100, 1, 1000000),
                'daily_max_count': _env_int('TRX_ORDER_DAILY_MAX_COUNT', 30, 1, 1000),
                'daily_max_total': _env_int('TRX_ORDER_DAILY_MAX_TOTAL', 3000, 1, 100000000),
                'min_interval_sec': _env_int('TRX_ORDER_MIN_INTERVAL_SEC', 30, 10, 3600)}

    def _roll_day(self):
        today = self.now().date().isoformat()
        if today != self.day:
            self.day, self.count, self.total = today, 0, 0

    def status(self):
        with self.lock:
            self._roll_day()
            return {**self.limits(), 'today_count': self.count, 'today_total': self.total}

    def place(self, direction, amount, confirmed):
        cfg = self.limits()
        if not cfg['enabled']:
            raise OrderError('Orders are disabled. Set TRX_ORDER_ENABLED=1 on the server to enable.', 403)
        if confirmed is not True:
            raise OrderError('Order needs explicit confirmation.')
        if direction not in SIDES:
            raise OrderError('Direction must be BIG or SMALL.')
        if type(amount) is not int or not 1 <= amount <= cfg['max_amount']:
            raise OrderError(f'Amount must be a whole number from 1 to {cfg["max_amount"]}.')
        if not self.lock.acquire(blocking=False):
            raise OrderError('Another order is in progress.', 409)
        try:
            self._roll_day()
            now = self.clock()
            if self.last is not None and now - self.last < cfg['min_interval_sec']:
                raise OrderError('Too soon after the previous order. Wait for the next round.', 429)
            if self.count >= cfg['daily_max_count'] or self.total + amount > cfg['daily_max_total']:
                raise OrderError('Daily order limit reached.', 429)
            _, config = self.sync.read()
            if not config.get('active'):
                raise ProviderError('expired')
            # Reserve before sending: an ambiguous failure may still have placed the order.
            self.last, self.count, self.total = now, self.count + 1, self.total + amount
            outcome, status, message = self._send(config, direction, amount)
            self.store.event('trxchart_order', {'direction': direction, 'amount': amount,
                                                'outcome': outcome, 'http_status': status})
            return {'ok': outcome == 'accepted', 'outcome': outcome, 'http_status': status,
                    'message': message, **{k: v for k, v in self.status_unlocked().items()
                                           if k in ('today_count', 'today_total')}}
        finally:
            self.lock.release()

    def status_unlocked(self):
        return {'today_count': self.count, 'today_total': self.total}

    def _send(self, config, direction, amount):
        with self.sync.session(config) as client:
            token = self.sync.token(client)
            try:
                response = client.post(ORIGIN + ENDPOINT, json={'direction': direction, 'amount': amount},
                                       headers={'X-API-Token': token}, timeout=(3, 8), allow_redirects=False)
            except requests.RequestException:
                return 'unknown', None, 'No clear answer from TRXChart. Check your history before trying again.'
        code = response.status_code
        if code in (401, 403) or 300 <= code < 400:
            return 'rejected', code, 'TRXChart session expired or was refused. Reconnect and check history.'
        if code != 200:
            return 'rejected', code, f'TRXChart returned HTTP {code}.'
        try:
            data = response.json()
        except ValueError:
            return 'unknown', code, 'TRXChart answered 200 with a non-JSON body. Check history.'
        if not isinstance(data, dict):
            return 'unknown', code, 'Unexpected TRXChart response. Check history.'
        text = str(data.get('message') or data.get('msg') or '')[:200]
        if data.get('success') is False:
            return 'rejected', code, text or 'TRXChart did not accept the order.'
        return 'accepted', code, text or 'Order sent.'
