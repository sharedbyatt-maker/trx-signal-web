"""Offline settlement event delivery, history baselines and cursor regressions."""
import copy

from trade_updates import observe, feed, MAX_EVENTS
from tests_admin_dashboard import admin, login, headers
from tests_trxchart_account_sync import setup, connect_body, decoded, TOKEN, COOKIE, PASSWORD


def row(ident='real:one', state=-1, at='2026-10-11T10:00:01+00:00', mode='real'):
    return {'id': ident, 'external_id': 'provider-one', 'mode': mode, 'at': at,
            'issue': '20261011103010115', 'side': 'BIG', 'stake_minor': 10000,
            'pnl_minor': None if state == -1 else 9600 if state == 1 else -10000,
            'state': state, 'number': None if state == -1 else 8 if state == 1 else 2}


def test_first_sync_is_silent_then_pending_settlement_is_exact_and_deduplicated():
    pending = row(at='2020-01-01T00:00:00+00:00')
    journal = {'rows': [pending, row('real:old', 1)]}
    observe(journal, [], '2026-10-11T10:00:00+00:00', True)
    assert journal['alerts'] == []
    journal['synced_at'] = {'real': '2026-10-11T10:00:00+00:00'}
    previous = copy.deepcopy(journal['rows'])
    journal['rows'][0] = row(at=pending['at'], state=0)
    observe(journal, previous, '2026-10-11T10:00:05+00:00', True)
    event = feed(journal, 0, journal['alert_stream'])['events'][0]
    assert event['sequence'] == 1
    assert event['trade']['id'] == pending['id']
    assert event['trade']['state'] == 0 and event['trade']['pnl'] == -100
    assert event['trade']['issue'] == '20261011103010115'
    observe(journal, copy.deepcopy(journal['rows']), 'later', True)
    assert journal['alert_sequence'] == 1
    assert feed(journal, 1, journal['alert_stream'])['events'] == []
    assert feed(journal)['events'] == []
    assert feed(journal, 0, 'a-different-account')['events'] == []


def test_new_confirmed_orders_alert_but_demo_and_backfilled_history_do_not():
    journal = {'rows': [], 'synced_at': {'real': '2026-10-11T10:00:00+00:00'}}
    # Same amount/side/time, distinct provider IDs remain distinct events.
    journal['rows'] = [row('real:a', 1), row('real:b', 0), row('demo:c', 1, mode='demo'),
                       row('real:backfill', 1, at='2020-01-01T00:00:00+00:00')]
    observe(journal, [], 'now', True)
    assert [e['trade']['id'] for e in journal['alerts']] == ['real:a', 'real:b']
    assert len(feed(journal)['recent']) == 3
    before = copy.deepcopy(journal)
    observe(journal, [], 'now', False)
    assert journal == before


def test_event_retention_cursor_gap_and_restart():
    journal = {'rows': [], 'synced_at': {'real': '2026-10-11T10:00:00+00:00'}}
    journal['rows'] = [row('real:' + str(n).zfill(3), n % 2) for n in range(MAX_EVENTS + 5)]
    observe(journal, [], 'now', True)
    restored = copy.deepcopy(journal)
    data = feed(restored, 0, restored['alert_stream'])
    assert data['gap'] and len(data['events']) == MAX_EVENTS
    assert data['cursor'] == MAX_EVENTS + 5 and data['events'][0]['sequence'] == 6
    assert len(data['recent']) == 20
    assert feed(restored, data['cursor'], restored['alert_stream'])['events'] == []


def test_late_provider_row_still_alerts_after_intervening_successful_polls():
    journal = {'rows': [], 'synced_at': {'real': '2026-10-11T10:00:00+00:00'}}
    observe(journal, [], '2026-10-11T10:00:05+00:00', True)
    journal['synced_at']['real'] = '2026-10-11T10:00:30+00:00'
    journal['rows'] = [row(state=1)]  # Created before latest poll, exposed afterward.
    observe(journal, [], '2026-10-11T10:00:35+00:00', True)
    assert len(journal['alerts']) == 1


def test_private_feed_confirmed_transition_is_atomic_encrypted_and_read_only(admin):
    client, store, provider = setup(admin)
    assert client.get('/api/admin/trade-feed').status_code == 401
    login(client)
    for cursor in ('-1', '1.5', 'nan', '1e3', '9' * 16, '\u0661'):
        assert client.get('/api/admin/trade-feed', query_string={'after': cursor}).status_code == 400
    assert client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client)).status_code == 200
    first = client.get('/api/admin/trade-feed').json
    assert first['events'] == [] and first['recent'][0]['state'] == -1
    provider.pending = False
    store.history_sync.sync_once()
    calls = len(provider.calls)
    result = client.get('/api/admin/trade-feed', query_string={'after': 0, 'stream': first['stream']})
    assert result.status_code == 200 and len(result.json['events']) == 1
    assert result.json['events'][0]['trade']['state'] == 1
    assert result.json['events'][0]['trade']['pnl'] == 96
    assert len(provider.calls) == calls  # Feed makes no network/order requests.
    encrypted = store.private_get('trade_journal')['value']
    assert first['stream'] not in encrypted
    for secret in (TOKEN, COOKIE, PASSWORD, 'fixture@example.invalid'):
        assert secret not in result.text
    store.history_sync.sync_once()
    assert decoded(store, 'trade_journal')['alert_sequence'] == 1


def test_fast_order_follow_is_bounded_real_only_and_keeps_failure_backoff(admin, monkeypatch):
    client, store, provider = setup(admin)
    login(client)
    assert client.post('/api/admin/trxchart-account', json=connect_body(), headers=headers(client)).status_code == 200
    clock = [1000.0]
    monkeypatch.setattr('trxchart_account_sync.time.monotonic', lambda: clock[0])
    sync = store.history_sync
    assert sync.poll_delay() == 60
    sync.last_full_sync = clock[0]
    sync.follow_orders()
    assert sync.wake.is_set() and sync.poll_delay() == 2
    provider.calls.clear()
    sync.sync_once()
    assert ('GET', '/api/bet/history?size=500') in [c[:2] for c in provider.calls]
    assert ('GET', '/api/demo/history?size=500') not in [c[:2] for c in provider.calls]
    clock[0] += 61
    provider.calls.clear()
    sync.sync_once()
    assert ('GET', '/api/demo/history?size=500') not in [c[:2] for c in provider.calls]
    sync.failures = 1
    assert sync.poll_delay() == 4
    sync.failures = 0
    clock[0] += 180
    assert sync.poll_delay() == 60
