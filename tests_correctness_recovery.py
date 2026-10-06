"""Protect the owner's existing strategy while repairing transport/recovery."""
import copy
import hashlib
import json
import os
import random
import statistics
from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

os.environ['TRX_NO_ENGINE'] = '1'
import app
import app_core as core
import l1_capital as l1
from admin_dashboard import AdminStore
from decision import decide_signal
from engine_checkpoint import EngineCheckpoint
from feed_utils import feed_delay_seconds, next_issue_number, source_age_seconds
from tests_l1_capital import FakeCore


def test_signed_future_age_and_nonnegative_display_delay():
    now = datetime(2026, 10, 6, tzinfo=timezone.utc)
    stamp = (now + timedelta(days=1)).isoformat()
    assert source_age_seconds(stamp, now) == -86400
    assert feed_delay_seconds(stamp, now) == 0
    assert source_age_seconds('invalid', now) is None


def test_rolling_rsi_matches_existing_live_rsi_every_prefix():
    rng = random.Random(19)
    nums = [rng.randrange(10) for _ in range(400)]
    values = core.rolling_rsi_series(nums)
    for i in range(core.RSI_PERIOD, len(nums)):
        assert values[i] == core.rsi(nums[:i + 1])


def test_backtest_decisions_match_live_on_correlated_history(monkeypatch):
    # This fixture previously included SMALL backtest trades where live skipped.
    rng = random.Random(2026)
    rows, number = [], 5
    for i in range(1200):
        drift = 1 if (i // 60) % 2 == 0 else -1
        number = max(0, min(9, number + rng.choice([drift, drift, drift, -drift, 2 * drift, -2 * drift])))
        if rng.random() < .08:
            number = rng.randrange(10)
        rows.append({'issue':str(20261005103010001 + i), 'number':number,
                     'type':'BIG' if number >= 5 else 'SMALL'})
    recorded = []
    def capture(*args):
        decision = decide_signal(*args)
        recorded.append((args, decision))
        return decision
    monkeypatch.setattr(app, 'decide_signal', capture)
    app.run_backtest(rows)
    backtest = list(recorded)
    monkeypatch.setattr(app, 'decide_signal', decide_signal)
    index = 0
    for i in range(102, len(rows)):
        if statistics.pstdev([r['number'] for r in rows[i - core.VOL_WINDOW:i]]) < core.VOL_MIN:
            continue
        args, decision = backtest[index]
        live = app.analyze_all_in_one(rows[:i])
        assert live['score'] == args[0]
        assert live['signal'] == decision['signal'], i
        index += 1
    assert index == len(backtest) and index > 300


@pytest.mark.parametrize('seed,digest', [
    (7, '4012d98b045c03b15b628bef83ef3c099a3750e89a691aa8b34b31d361e7ec96'),
    (19, '996d5af6f482489c5a00cd30f72e52420983a07b7abcf8eca0431d9be9df7a29'),
    (88, 'fd38fd60b66f0471519fbeb89a0100a8e9dd680f755cd724d2ab4589ca456fba'),
    (2026, '728a7e4caa0e8055d44ce696474427b3176b7781111c6a9775d81c838fdc6661'),
])
def test_complete_l1_history_preserves_upstream_strategy(seed, digest):
    # Golden outputs from upstream 1286466, including the midnight issue rollover.
    rng = random.Random(seed)
    rows, issue = [], '20261005103010001'
    for _ in range(1500):
        rows.append({'issue':issue, 'type':rng.choice(['BIG','SMALL']),
                     'block_time':'2026-10-05 12:00:00'})
        issue = next_issue_number(issue)
    def normalize(value):
        if isinstance(value, dict):
            return {k:normalize(v) for k,v in value.items() if k != 'enter_issue'}
        if isinstance(value, list):
            return [normalize(v) for v in value]
        return value
    payload = json.dumps(normalize(l1.replay_l1(rows)), sort_keys=True, separators=(',',':'))
    assert hashlib.sha256(payload.encode()).hexdigest() == digest


@pytest.mark.parametrize('count', [17, 18])
def test_l1_missing_target_never_settles_against_later_round(count):
    rows = [{'issue':str(20261005103010001 + i), 'type':'SMALL',
             'block_time':'2026-10-05 12:00:00'} for i in range(count)]
    rows[15]['type'] = 'BIG'
    for row in rows[16:]:
        row['issue'] = str(int(row['issue']) + 1)
        row['type'] = 'BIG'
    rsi = [50.0] * count
    rsi[14] = 31.0
    with patch.object(l1, '_rsi', return_value=rsi):
        snap = l1.replay_l1(rows)
    assert snap['trades'] == []
    assert snap['today_pnl'] == 0


def test_l1_skip_counts_calendar_rounds_across_history_gap():
    rows = [{'issue':str(20261005103010001 + i), 'type':'SMALL',
             'block_time':'2026-10-05 12:00:00'} for i in range(18)]
    rows[15]['type'] = 'BIG'
    # Loss at index 16, R02 skips 3 rounds; only the boundary row is available.
    rows[17]['issue'] = str(int(rows[16]['issue']) + 3)
    rsi = [50.0] * 18
    rsi[14], rsi[16] = 31.0, 75.0
    with patch.object(l1, '_rsi', return_value=rsi):
        snap = l1.replay_l1(rows)
    assert len(snap['trades']) == 1 and snap['trades'][0]['pnl'] == -500
    assert snap['pending']['stake'] == 1000 and snap['pending']['step'] == 2
    assert snap['pending']['rule'] == 'R02'


def test_l1_replay_cache_preserves_freshness_and_invalidates_on_publication(tmp_path):
    rows = [{'issue':str(20261005103010001 + i), 'type':'BIG',
             'block_time':'2026-10-05 12:00:00'} for i in range(18)]
    fake = FakeCore(rows, next_issue_number(rows[-1]['issue']))
    fake._admin_store = AdminStore(tmp_path / 'admin.sqlite3')
    service = l1.L1CapitalService(fake, state_file='')
    with patch.object(l1, 'replay_l1', wraps=l1.replay_l1) as replay:
        first = service.refresh_once()
        assert service.refresh_once() == first
        assert replay.call_count == 1
        fake.STATE['connected'] = False
        assert service.refresh_once()['ready'] is False
        assert replay.call_count == 1
        fake.STATE['full_history'] = list(rows)
        service.refresh_once()
        assert replay.call_count == 2


def _reset_engine(monkeypatch):
    state = copy.deepcopy(core.STATE)
    state.update(history=[], full_history=[], connected=False, backtest=None,
                 strat_log=[], log=[], equity=[], next_issue=None)
    monkeypatch.setattr(core, 'STATE', state)
    values = {'last_issue':None, 'pending':None, 'strat_pending':None,
              'unresolved_signal':None, 'signal_history':[], 'stats':{'w':0,'l':0},
              'recent_results':deque(maxlen=20), 'units':0,'lose_streak':0,'cooldown':0,
              'strat_daily_reports':{}, '_bt_day':None,
              'strat_state':{'tier':0,'step':0,'signals':0,'busts':0,'last_result':None,'pending':None}}
    for name,value in values.items():
        monkeypatch.setattr(core, name, value)


def _engine_polls(monkeypatch, batches):
    index = [0]
    def fetch(*_):
        rows = batches[index[0]]
        index[0] += 1
        return SimpleNamespace(status_code=200, json=lambda:rows)
    def sleep(_):
        if index[0] == len(batches):
            raise SystemExit
    monkeypatch.setattr(core, 'fetch_feed', fetch)
    monkeypatch.setattr(core.time, 'sleep', sleep)
    with pytest.raises(SystemExit):
        core.engine_loop()
    core._notification_context.historical = False


def test_real_twelve_restart_matches_uninterrupted_settlement(monkeypatch, tmp_path):
    monkeypatch.setattr(core, '_admin_store', AdminStore(tmp_path / 'admin.sqlite3'), raising=False)
    monkeypatch.setattr(core, 'STRAT_DAILY_FILE', str(tmp_path / 'daily.json'))
    monkeypatch.setattr(core, 'rsi_series', lambda values,*_: [31.0] * len(values))
    monkeypatch.setattr(core, 'analyze_all_in_one', lambda *_: {'signal':'SKIP','score':0})
    monkeypatch.setattr(core, 'run_backtest', lambda *_: None)
    monkeypatch.setattr(core, 'feed_delay_seconds', lambda *_: 0)
    monkeypatch.setattr(core, 'tg_notify', lambda *_,**__: True)
    for name in ('append_signal_history', 'log_signal', '_send_previous_strat_daily_if_needed'):
        monkeypatch.setattr(core, name, lambda *_,**__: None)
    boot = [{'issueNumber':str(20261005103010001 + i),'number':8,
             'blockTime':'2026-10-05 12:00:00'} for i in range(18)]
    loss = [{**boot[-1], 'issueNumber':'20261005103010019', 'number':2}]
    win = [{**boot[-1], 'issueNumber':'20261005103010020', 'number':8}]
    _reset_engine(monkeypatch)
    monkeypatch.setattr(core, '_runtime_checkpoint', None)
    _engine_polls(monkeypatch, [boot, loss, win])
    expected_pending = copy.deepcopy(core.strat_pending)
    expected_state = copy.deepcopy(core.strat_state)
    expected_report = copy.deepcopy(core.strat_daily_reports)
    for report in expected_report.values():
        report.pop('updated_at', None)

    _reset_engine(monkeypatch)
    checkpoint = EngineCheckpoint(tmp_path / 'runtime.sqlite3')
    monkeypatch.setattr(core, '_runtime_checkpoint', checkpoint)
    _engine_polls(monkeypatch, [boot, loss])
    assert core.strat_pending['stake'] == 400
    saved = checkpoint.load()
    invalid = copy.deepcopy(saved)
    invalid['strat_pending']['issue'] = '20261005103010021'
    with pytest.raises(ValueError, match='pending target'):
        checkpoint.save(invalid)
    assert checkpoint.load() == saved
    # Simulate a report write from an interrupted, uncheckpointed round.
    core._strat_daily_event('2026-10-05', 'partial-crash-event', settled_bets=99)
    _reset_engine(monkeypatch)
    assert core._restore_engine_checkpoint(checkpoint)
    assert core.strat_pending['stake'] == 400
    # Fetching the same source after restart must publish, not settle/rearm.
    _engine_polls(monkeypatch, [boot + loss])
    assert core.strat_pending['stake'] == 400
    assert core.STATE['next_issue'] == '20261005103010020'
    _engine_polls(monkeypatch, [boot + loss + win])
    assert core.strat_pending == expected_pending
    assert core.strat_state == expected_state
    report = copy.deepcopy(core.strat_daily_reports)
    for item in report.values():
        item.pop('updated_at', None)
    assert report == expected_report
    assert next(iter(report.values()))['settled_bets'] == 2


def test_checkpoint_corruption_fails_closed(tmp_path):
    checkpoint = EngineCheckpoint(tmp_path / 'admin.sqlite3')
    with checkpoint.connect() as db:
        db.execute("INSERT INTO engine_checkpoint VALUES(1,'{}','bad-digest')")
    with pytest.raises(ValueError, match='unreadable'):
        checkpoint.load()
