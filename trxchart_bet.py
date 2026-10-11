"""Explicit, disabled-by-default REAL orders; never called by signal engines.

The known /api/bet endpoint is not a demo endpoint. Each attempt is durably
reserved before POST, is never retried, and has a client-generated request ID.
Limits survive worker restarts while the admin SQLite database survives.
"""
import json
import math
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from uuid import UUID

import requests

from trxchart_account_sync import ORIGIN, ProviderError

ENDPOINT = '/api/bet'
BANGKOK = timezone(timedelta(hours=7))
MAX_RESPONSE_BYTES = 65536
UNKNOWN_MESSAGE = 'Order outcome is unknown. Check REAL history before placing another order. This request will not be resent.'


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
    def __init__(self, history_sync, store, now=None):
        self.sync, self.store = history_sync, store
        self.now = now or (lambda: datetime.now(BANGKOK))
        self.lock = threading.Lock()
        with store.lock, store.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS trxchart_orders('
                       'request_id TEXT PRIMARY KEY, day TEXT NOT NULL, at REAL NOT NULL, '
                       'direction TEXT NOT NULL, amount INTEGER NOT NULL, '
                       'outcome TEXT NOT NULL, http_status INTEGER)')
            db.execute('CREATE INDEX IF NOT EXISTS trxchart_orders_day ON trxchart_orders(day)')

    @staticmethod
    def limits():
        return {'enabled': os.environ.get('TRX_ORDER_ENABLED') == '1', 'mode': 'real',
                'max_amount': _env_int('TRX_ORDER_MAX_AMOUNT', 100, 1, 1000000),
                'daily_max_count': _env_int('TRX_ORDER_DAILY_MAX_COUNT', 30, 1, 1000),
                'daily_max_total': _env_int('TRX_ORDER_DAILY_MAX_TOTAL', 3000, 1, 100000000),
                'min_interval_sec': _env_int('TRX_ORDER_MIN_INTERVAL_SEC', 30, 10, 3600)}

    def _time(self):
        value = self.now()
        if value.tzinfo is None:
            value = value.replace(tzinfo=BANGKOK)
        value = value.astimezone(BANGKOK)
        return value.date().isoformat(), value.timestamp()

    @staticmethod
    def _usage(db, day, at, cfg):
        count, total = db.execute('SELECT COUNT(*),COALESCE(SUM(amount),0) FROM trxchart_orders WHERE day=?', (day,)).fetchone()
        last = db.execute('SELECT MAX(at) FROM trxchart_orders').fetchone()[0]
        wait = max(0, math.ceil(cfg['min_interval_sec'] - (at - last))) if last is not None else 0
        return {'today_count': count, 'today_total': total, 'retry_after_sec': wait}

    def status(self):
        cfg = self.limits()
        day, at = self._time()
        with self.store.lock, self.store.connect() as db:
            usage = self._usage(db, day, at, cfg)
        return {**cfg, **usage}

    def _existing(self, db, request_id, direction, amount):
        row = db.execute('SELECT direction,amount,outcome,http_status FROM trxchart_orders WHERE request_id=?', (request_id,)).fetchone()
        if not row:
            return None
        if row[:2] != (direction, amount):
            raise OrderError('This request ID already belongs to a different order.', 409)
        outcome = 'unknown' if row[2] == 'pending' else row[2]
        return self._result(request_id, outcome, row[3], replayed=True)

    @staticmethod
    def _result(request_id, outcome, status, replayed=False):
        message = {'accepted': 'TRXChart confirmed the REAL order. Check REAL history for its result.',
                   'rejected': 'TRXChart rejected the order. Check the connection and REAL history.',
                   'unknown': UNKNOWN_MESSAGE}[outcome]
        return {'ok': outcome == 'accepted', 'outcome': outcome, 'http_status': status,
                'request_id': request_id, 'replayed': replayed, 'message': message, 'mode': 'real'}

    @staticmethod
    def _audit(db, request_id, direction, amount, outcome, status, at):
        detail = {'request_id': request_id, 'mode': 'real', 'direction': direction,
                  'amount': amount, 'outcome': outcome, 'http_status': status}
        db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',
                   (datetime.fromtimestamp(at, timezone.utc).isoformat(timespec='seconds'),
                    'trxchart_order', json.dumps(detail)))
        db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')

    def place(self, direction, amount, confirmed, mode, request_id):
        cfg = self.limits()
        if not cfg['enabled']:
            raise OrderError('Real orders are disabled on this server.', 403)
        if mode != 'real':
            raise OrderError('Only explicitly confirmed REAL orders are supported. Demo order placement is unavailable.')
        if confirmed is not True:
            raise OrderError('Confirm that this order uses your REAL balance.')
        if direction not in ('BIG', 'SMALL'):
            raise OrderError('Direction must be BIG or SMALL.')
        if type(amount) is not int or not 1 <= amount <= cfg['max_amount']:
            raise OrderError(f'Amount must be a whole number from 1 to {cfg["max_amount"]}.')
        try:
            if not isinstance(request_id, str) or len(request_id) != 36:
                raise ValueError()
            request_id = str(UUID(request_id))
        except (ValueError, AttributeError):
            raise OrderError('A valid order request ID is required.') from None
        with self.store.lock, self.store.connect() as db:
            existing = self._existing(db, request_id, direction, amount)
        if existing:
            return {**existing, **self.status()}
        if not self.lock.acquire(blocking=False):
            raise OrderError('Another order is in progress.', 409)
        if not self.sync.operation.acquire(blocking=False):
            self.lock.release()
            raise OrderError('History sync or account login is running. Try again shortly.', 409)
        try:
            revision, config = self.sync.read()
            if not config.get('active'):
                raise ProviderError('expired')
            # Obtain the token before reserving: failures here cannot send an order.
            with self.sync.session(config) as client:
                token = self.sync.token(client)
                with self.store.lock, self.store.connect() as db:
                    db.execute('BEGIN IMMEDIATE')
                    existing = self._existing(db, request_id, direction, amount)
                    if existing:
                        return {**existing, **self.status()}
                    if self.store.private_get('trxchart_account')['revision'] != revision:
                        raise OrderError('Connection changed. Refresh before ordering.', 409)
                    cfg = self.limits()
                    if not cfg['enabled']:
                        raise OrderError('Real orders are disabled on this server.', 403)
                    day, at = self._time()
                    usage = self._usage(db, day, at, cfg)
                    if usage['retry_after_sec']:
                        raise OrderError('Too soon after the previous attempt. Wait before ordering again.', 429)
                    if usage['today_count'] >= cfg['daily_max_count'] or usage['today_total'] + amount > cfg['daily_max_total']:
                        raise OrderError('Daily order limit reached.', 429)
                    if amount > cfg['max_amount']:
                        raise OrderError('The per-order limit changed. Refresh before ordering.')
                    # Keep a bounded ledger; today's limits and the latest cooldown survive.
                    cutoff = (datetime.fromtimestamp(at, BANGKOK) - timedelta(days=90)).date().isoformat()
                    db.execute('DELETE FROM trxchart_orders WHERE day<?', (cutoff,))
                    db.execute('INSERT INTO trxchart_orders VALUES(?,?,?,?,?,?,?)',
                               (request_id, day, at, direction, amount, 'pending', None))
                    self._audit(db, request_id, direction, amount, 'pending', None, at)
                outcome, status = self._send(client, token, direction, amount)
            # If persistence fails after POST, the durable pending reservation stays unknown.
            with self.store.lock, self.store.connect() as db:
                db.execute('UPDATE trxchart_orders SET outcome=?,http_status=? WHERE request_id=?',
                           (outcome, status, request_id))
                self._audit(db, request_id, direction, amount, outcome, status, self._time()[1])
            return {**self._result(request_id, outcome, status), **self.status()}
        finally:
            self.sync.operation.release()
            self.lock.release()

    @staticmethod
    def _send(client, token, direction, amount):
        status = None
        try:
            # No retries, redirects, alternate endpoints, or provider text in the UI.
            with client.post(ORIGIN + ENDPOINT, json={'direction': direction, 'amount': amount},
                             headers={'X-API-Token': token}, timeout=(3, 8),
                             allow_redirects=False, stream=True) as response:
                status = response.status_code
                if 400 <= status < 500 and status != 408 or 300 <= status < 400:
                    return 'rejected', status
                if status != 200:
                    return 'unknown', status
                chunks, size, started = [], 0, time.monotonic()
                for chunk in response.iter_content(8192):
                    size += len(chunk)
                    if size > MAX_RESPONSE_BYTES or time.monotonic() - started > 12:
                        return 'unknown', status
                    chunks.append(chunk)
                data = json.loads(b''.join(chunks).decode('utf-8'))
                if not isinstance(data, dict) or type(data.get('success')) is not bool:
                    return 'unknown', status
                if data['success'] is False:
                    return 'rejected', status
                if data.get('error'):
                    return 'unknown', status
                return 'accepted', status
        except (requests.RequestException, ValueError, UnicodeError):
            return 'unknown', status
