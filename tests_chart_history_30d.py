import os
os.environ['TRX_NO_ENGINE'] = '1'
from datetime import datetime, timedelta
import app_core as core

def test_full_thirty_days_survive_memory_cap_and_api():
    assert core.FULL_HISTORY_DAYS == 30
    assert core.MAX_FULL_ROWS >= 30 * 1440
    start = datetime(2026, 9, 1)
    rows = []
    for i in range(35 * 1440):
        stamp = start + timedelta(minutes=i)
        issue = stamp.strftime('%Y%m%d') + f'10301{i % 1440 + 1:04d}'
        rows.append({'issue': issue, 'day_int': int(stamp.strftime('%Y%m%d')), 'number': i % 10, 'block_time': stamp.strftime('%Y-%m-%d %H:%M:%S')})
    kept = core.trim_full_history(rows)
    assert len(kept) == 43200
    assert kept[0]['day_int'] == 20260906
    with core.LOCK:
        old = core.STATE['full_history']
        core.STATE['full_history'] = kept
    try:
        client = core.app.test_client()
        body = client.get('/api/history').get_json()
        assert body['days'] == 30 and body['count'] == 43200
        assert len(client.get('/api/history?days=10').get_json()['history']) == 14400
        tail = client.get('/api/history?since=' + kept[-2]['issue']).get_json()
        assert tail['incremental'] and tail['count'] == 1
    finally:
        with core.LOCK:
            core.STATE['full_history'] = old
