"""Private accounting for imported completed activity; no network or order execution."""
import copy
import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

DEFAULT_LIMITS = {'tp': 0, 'sl': 0, 'timezone': 'Asia/Bangkok'}
ZONES = ('Asia/Bangkok', 'Asia/Yangon', 'UTC')
MAX_ROWS = 5000


def money(value, positive=False):
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise ValueError('Amounts must be numeric with at most two decimal places.')
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or abs(amount) > 1000000000 or amount * 100 != (amount * 100).to_integral_value():
            raise ValueError('Amounts must be finite, at most 1 billion, and have at most two decimal places.')
        if amount < 0 or (positive and amount <= 0):
            raise ValueError('Stake must be positive; limits and payouts cannot be negative.')
        return int(amount * 100)
    except (InvalidOperation, OverflowError):
        raise ValueError('Invalid monetary amount.') from None


def limits(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULT_LIMITS) or value['timezone'] not in ZONES:
        raise ValueError('Provide TP, SL and a supported day timezone.')
    return {'tp': money(value['tp']) / 100, 'sl': money(value['sl']) / 100, 'timezone': value['timezone']}


def normalize(payload, mode, source_zone):
    if mode not in ('real', 'demo') or source_zone not in ZONES:
        raise ValueError('Choose real/demo and the source timestamp timezone.')
    if isinstance(payload, dict):
        if payload.get('mode', mode) != mode:
            raise ValueError('Exported history mode differs from the selected import mode.')
        if payload.get('success') is not True:
            raise ValueError('Import a successful history response with a list of records.')
        payload = payload.get('list')
    if not isinstance(payload, list) or not payload or len(payload) > MAX_ROWS:
        raise ValueError('Import between 1 and 5,000 history records.')
    out, seen = [], set()
    for index, item in enumerate(payload, 1):
        try:
            if not isinstance(item, dict):
                raise ValueError('Each history record must be an object.')
            stamp = item.get('addTime')
            if not isinstance(stamp, str) or not re.match(r'^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}', stamp):
                raise ValueError('A full addTime date and time is required; time-only table copies cannot identify today.')
            dt = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=ZoneInfo(source_zone))
            stamp = dt.astimezone(timezone.utc).isoformat()
            issue = item.get('issueNumber')
            if not isinstance(issue, str) or not re.fullmatch(r'\d{17}', issue):
                raise ValueError('A full 17-digit issueNumber string is required (numeric JSON may lose precision).')
            side = str(item.get('selectType', '')).upper()
            if side not in ('BIG', 'SMALL'):
                raise ValueError('Only BIG / SMALL history records are supported.')
            state = item.get('state')
            if type(state) is not int or state not in (-1, 0, 1):
                raise ValueError('state must be -1 (pending), 0 (loss) or 1 (win).')
            stake = money(item.get('amount'), positive=True)
            pnl = money(item.get('profitAmount')) - stake if state == 1 else -stake if state == 0 else None
            number = item.get('number')
            if number is not None:
                if isinstance(number, str) and re.fullmatch(r'[0-9]', number):
                    number = int(number)
                if type(number) is not int or not 0 <= number <= 9:
                    raise ValueError('Result number must be 0–9 or absent.')
            external = next((item[k] for k in ('orderId', 'orderNumber', 'id') if item.get(k) is not None), None)
            if external is not None:
                if (type(external) is int and abs(external) > 9007199254740991) or isinstance(external, bool) or not isinstance(external, (str, int)) or not re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', str(external)):
                    raise ValueError('Invalid order identifier.')
                external = str(external)
            identity = external or json.dumps([stamp, issue, side, stake], separators=(',', ':'))
            key = mode + ':' + hashlib.sha256(identity.encode()).hexdigest()
            if key in seen:
                raise ValueError('Duplicate or ambiguous order in this file. Preserve unique order IDs for same-time orders.')
            seen.add(key)
            out.append({'id': key, 'external_id': external, 'mode': mode, 'at': stamp, 'issue': issue,
                        'side': side, 'stake_minor': stake, 'pnl_minor': pnl, 'state': state, 'number': number})
        except (ValueError, TypeError, OverflowError) as exc:
            raise ValueError(f'Record {index}: {exc}') from None
    return out


def merge(existing, incoming):
    records = {r['id']: copy.deepcopy(r) for r in existing}
    added = updated = unchanged = 0
    for row in incoming:
        old = records.get(row['id'])
        if old is None:
            added += 1
        else:
            immutable = ('mode', 'at', 'issue', 'side', 'stake_minor')
            if any(old[k] != row[k] for k in immutable):
                raise ValueError('An existing order ID has conflicting trade details. No records were imported.')
            if old['state'] in (0, 1):
                if row['state'] == -1:
                    unchanged += 1
                    continue
                if (old['state'], old['pnl_minor'], old['number']) != (row['state'], row['pnl_minor'], row['number']):
                    raise ValueError('A settled order conflicts with an existing result. No records were imported.')
            if old == row:
                unchanged += 1
                continue
            updated += 1
        records[row['id']] = copy.deepcopy(row)
    if len(records) > MAX_ROWS:
        raise ValueError('Journal capacity is 5,000 records. No records were imported.')
    return sorted(records.values(), key=lambda r: (r['at'], r['id'])), {'added': added, 'updated': updated, 'unchanged': unchanged}


def snapshot(value, revision, mode='real', day=None, now=None):
    if mode not in ('real', 'demo'):
        raise ValueError('Choose real or demo history.')
    cfg = value['limits']
    tz = ZoneInfo(cfg['timezone'])
    today = (now or datetime.now(timezone.utc)).astimezone(tz).date().isoformat()
    day = day or today
    try:
        if datetime.strptime(day, '%Y-%m-%d').date().isoformat() != day:
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Choose a valid YYYY-MM-DD date.') from None
    selected = [r for r in value['rows'] if r['mode'] == mode and datetime.fromisoformat(r['at']).astimezone(tz).date().isoformat() == day]
    settled = [r for r in selected if r['state'] in (0, 1)]
    pnl = sum(r['pnl_minor'] for r in settled)
    tp, sl = money(cfg['tp']), money(cfg['sl'])
    status = 'sl_reached' if sl and pnl <= -sl else 'tp_reached' if tp and pnl >= tp else 'within_limits' if tp or sl else 'limits_disabled'
    return {'revision': revision, 'limits': cfg, 'today': today, 'date': day, 'mode': mode,
            'summary': {'pnl': pnl / 100, 'staked': sum(r['stake_minor'] for r in selected) / 100,
                        'trades': len(selected), 'wins': sum(r['state'] == 1 for r in selected),
                        'losses': sum(r['state'] == 0 for r in selected), 'pending': sum(r['state'] == -1 for r in selected),
                        'status': status},
            'rows': [{**{k: r[k] for k in ('at', 'issue', 'side', 'state', 'number')},
                      'stake': r['stake_minor'] / 100, 'pnl': r['pnl_minor'] / 100 if r['pnl_minor'] is not None else None}
                     for r in reversed(selected[-500:])],
            'display_truncated': len(selected) > 500, 'stored_records': len(value['rows']),
            'imported_at': value.get('imported_at'),
            'coverage': 'Imported records only; this is not a verified complete account-day total. Pending records are excluded from P/L.'}


def export_rows(value, mode):
    if mode not in ('real', 'demo'):
        raise ValueError('Choose real or demo history.')
    out = []
    for r in value['rows']:
        if r['mode'] != mode:
            continue
        row = {'addTime': r['at'], 'issueNumber': r['issue'], 'selectType': r['side'].lower(),
               'amount': r['stake_minor'] / 100, 'state': r['state'], 'number': r['number'],
               'profitAmount': (r['stake_minor'] + r['pnl_minor']) / 100 if r['state'] == 1 else 0}
        if r['external_id'] is not None:
            row['orderId'] = r['external_id']
        out.append(row)
    return {'success': True, 'list': out, 'mode': mode, 'coverage': 'Imported records only', 'limits': value['limits']}
