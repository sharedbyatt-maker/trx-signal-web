"""Durable, provider-confirmed REAL settlements in the encrypted journal."""
from uuid import uuid4

MAX_EVENTS = 100


def record(row):
    return {key: row[key] for key in ('id', 'at', 'issue', 'side', 'state', 'number')} | {
        'stake': row['stake_minor'] / 100,
        'pnl': None if row['pnl_minor'] is None else row['pnl_minor'] / 100,
    }


def observe(journal, previous, now, real_complete):
    """Commit alongside history. The first sync establishes a silent baseline."""
    journal.setdefault('alert_stream', str(uuid4()))
    journal.setdefault('alert_sequence', 0)
    events = journal.setdefault('alerts', [])
    if real_complete:
        journal.setdefault('alert_baseline_at', journal.get('synced_at', {}).get('real') or now)
    if not real_complete or not journal.get('synced_at', {}).get('real'):
        return
    known = {row['id']: row for row in previous if row['mode'] == 'real'}
    for row in sorted(journal['rows'], key=lambda item: (item['at'], item['id'])):
        if row['mode'] != 'real' or row['state'] not in (0, 1):
            continue
        old = known.get(row['id'])
        # Historical backfills older than the first account baseline are silent.
        # A provider can expose an order late, after intervening successful polls.
        # Previously pending rows always report their confirmed settlement.
        if old and old['state'] != -1:
            continue
        if old is None and row['at'] < journal['alert_baseline_at']:
            continue
        journal['alert_sequence'] += 1
        events.append({'sequence': journal['alert_sequence'], 'observed_at': now,
                       'trade': record(row)})
    journal['alerts'] = events[-MAX_EVENTS:]


def feed(journal, after=None, stream=None):
    cursor = journal.get('alert_sequence', 0)
    current = journal.get('alert_stream')
    events = journal.get('alerts', [])
    matches = current is not None and stream == current and after is not None
    # Never replay an old account/reset stream or historical results on first open.
    updates = [event for event in events if event['sequence'] > after] if matches else []
    rows = sorted((row for row in journal['rows'] if row['mode'] == 'real'),
                  key=lambda row: (row['at'], row['id']), reverse=True)[:20]
    return {'stream': current, 'cursor': cursor, 'events': updates,
            'recent': [record(row) for row in rows],
            'gap': bool(matches and events and after < events[0]['sequence'] - 1)}
