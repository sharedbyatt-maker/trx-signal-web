"""Read-only TronGrid adapter. No wallet operations or strategy rules."""
import copy
import os
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests

ENDPOINT = 'https://api.trongrid.io/wallet/getblock'
DEFAULT_TRONGRID = {'mode': 'disabled', 'key': ''}


def validate_trongrid(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_TRONGRID):
        raise ValueError('Invalid TronGrid settings.')
    if value['mode'] not in ('disabled', 'backup', 'live'):
        raise ValueError('Choose disabled, backup or live rounds.')
    key = value['key']
    if not isinstance(key, str) or len(key) > 512 or not key.isascii() or any(ord(c) < 33 or ord(c) == 127 for c in key):
        raise ValueError('Use an ASCII API key without spaces.')
    if value['mode'] != 'disabled' and not key:
        raise ValueError('A TronGrid API key is required.')
    return dict(value)


def public_trongrid(value):
    return {'mode': value['mode'], 'key_set': bool(value['key']), 'endpoint': ENDPOINT}


def block_record(block, target):
    raw = block.get('block_header', {}).get('raw_data', {})
    digest = block.get('blockID', '')
    if raw.get('timestamp') != target or not isinstance(digest, str) or len(digest) != 64 or any(c not in '0123456789abcdefABCDEF' for c in digest):
        raise ValueError('TronGrid block timestamp/hash did not match the requested round.')
    digits = [c for c in digest[16:] if c in '0123456789']
    if not digits:
        raise ValueError('TronGrid block has no decimal result digit.')
    stamp = datetime.fromtimestamp(target / 1000, timezone.utc)
    issue = stamp.strftime('%Y%m%d') + '10301' + f'{stamp.hour * 60 + stamp.minute + 1:04d}'
    local = stamp.astimezone(ZoneInfo(os.environ.get('TRX_SOURCE_TIMEZONE', 'Asia/Yangon')))
    return {'issueNumber': issue, 'number': int(digits[-1]), 'blockTime': local.strftime('%Y-%m-%d %H:%M:%S')}


class RoundResponse:
    status_code = 200

    def __init__(self, rows):
        self.rows = copy.deepcopy(rows)

    def json(self):
        return copy.deepcopy(self.rows)


class TronGridFeed:
    def __init__(self):
        self.lock = threading.RLock()
        self.key = None
        self.rows = {}
        self.head = None
        self.checked_at = 0
        self.retry_after = 0

    def clear(self):
        with self.lock:
            self.key = None
            self.rows = {}
            self.head = None
            self.checked_at = self.retry_after = 0

    def fetch(self, key, live, post=None, probe=False):
        post = post or requests.post
        with self.lock:
            if key != self.key:
                self.clear()
                self.key = key
            if time.monotonic() < self.retry_after:
                raise ValueError('TronGrid is cooling down after a rate limit. Try again later.')
            deadline = time.monotonic() + (40 if probe else 16)

            def call(payload):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ValueError('TronGrid verification timed out. Try again.')
                try:
                    response = post(ENDPOINT, json=payload, headers={'TRON-PRO-API-KEY': key},
                                    timeout=(2.5, min(6, remaining)), allow_redirects=False)
                    if response.status_code in (429, 403):
                        self.retry_after = time.monotonic() + 60
                    if response.status_code != 200:
                        raise ValueError('TronGrid check failed: HTTP ' + str(response.status_code))
                    data = response.json()
                except requests.RequestException as exc:
                    raise ValueError('TronGrid unavailable: ' + type(exc).__name__) from None
                except (TypeError, ValueError) as exc:
                    if isinstance(exc, ValueError) and str(exc).startswith('TronGrid'):
                        raise
                    raise ValueError('TronGrid returned invalid JSON.') from None
                if not isinstance(data, dict) or data.get('Error'):
                    raise ValueError('TronGrid rejected the block request. Check the API key and quota.')
                return data

            # Head refresh is throttled independently of the 0.5s engine poll.
            if probe or not self.head or time.monotonic() - self.checked_at >= 3:
                head = call({'detail': False})
                raw = head.get('block_header', {}).get('raw_data', {})
                if type(raw.get('number')) is not int or type(raw.get('timestamp')) is not int:
                    raise ValueError('TronGrid returned an invalid block header.')
                age = time.time() - raw['timestamp'] / 1000
                if age > 80 or age < -10:
                    raise ValueError('TronGrid latest block is stale or in the future.')
                self.head, self.checked_at = raw, time.monotonic()
            h = self.head
            latest = (h['timestamp'] // 60000) * 60000 + 54000
            if latest > h['timestamp']:
                latest -= 60000
            targets = [latest - i * 60000 for i in range(3, -1, -1)]
            # Include every missing round between the existing live cursor and head.
            # Bound catch-up; never leap over unverified intermediate rounds.
            if live:
                from feed_utils import source_time_utc
                stamp = source_time_utc(live[-1].get('block_time'))
                if stamp:
                    previous = int(stamp.timestamp() * 1000)
                    if latest - previous > 8 * 60000:
                        raise ValueError('TronGrid catch-up exceeds 8 minutes. Restore the primary history source first.')
                    targets = sorted(set(targets + list(range(previous - 2 * 60000, latest + 1, 60000))))
            additions = {}
            for target in targets:
                if target in self.rows:
                    continue
                height = h['number'] + round((target - h['timestamp']) / 3000)
                block = call({'id_or_num': str(height), 'detail': False})
                # Skipped blocks shift the height estimate; search near it, but
                # accept only the exact :54 timestamp, never a neighbouring block.
                for _ in range(3):
                    actual = block.get('block_header', {}).get('raw_data', {}).get('timestamp')
                    if type(actual) is not int or actual == target:
                        break
                    height += max(1, abs(round((target - actual) / 3000))) * (1 if target > actual else -1)
                    block = call({'id_or_num': str(height), 'detail': False})
                additions[target] = block_record(block, target)
            candidate = {**self.rows, **additions}
            recent = {r['issue']: r['number'] for r in live[-50:]}
            overlap = [r for r in candidate.values() if r['issueNumber'] in recent]
            if len(overlap) < 3 or any(recent[r['issueNumber']] != r['number'] for r in overlap):
                self.rows = {}
                raise ValueError('TronGrid results do not match at least 3 recent live rounds.')
            self.rows = {t: r for t, r in sorted(candidate.items())[-64:]}
            return RoundResponse([self.rows[t] for t in sorted(self.rows)])


LIVE_TRONGRID = TronGridFeed()
