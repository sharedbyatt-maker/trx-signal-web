"""Atomic restart checkpoints for the existing manual-execution engines.

The checkpoint shares the admin SQLite database so a persistent ADMIN_DB_PATH
also preserves engine progress. It never contains credentials or monotonic ages.
"""
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from feed_utils import next_issue_number


class EngineCheckpoint:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS engine_checkpoint '
                       '(id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT, digest TEXT)')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    @staticmethod
    def validate(value):
        if not isinstance(value, dict) or value.get('schema') != 1:
            raise ValueError('Unsupported engine checkpoint.')
        issue = value.get('last_issue')
        if not isinstance(issue, str) or not issue.isascii() or not issue.isdigit():
            raise ValueError('Invalid checkpoint source issue.')
        state = value.get('strat_state')
        if not isinstance(state, dict):
            raise ValueError('Invalid checkpoint strategy state.')
        for key, maximum in (('tier', 2), ('step', 3)):
            if type(state.get(key)) is not int or not 0 <= state[key] <= maximum:
                raise ValueError('Invalid checkpoint ladder position.')
        for key in ('signals', 'busts'):
            if type(state.get(key)) is not int or state[key] < 0:
                raise ValueError('Invalid checkpoint strategy counters.')
        target = next_issue_number(issue)
        for name, direction in (('pending', 'signal'), ('strat_pending', 'target')):
            pending = value.get(name)
            if pending is None:
                continue
            if (not isinstance(pending, dict) or pending.get('issue') != target
                    or pending.get(direction) not in ('BIG', 'SMALL')
                    or type(pending.get('stake')) is not int or pending['stake'] <= 0):
                raise ValueError('Invalid checkpoint pending target.')
            if name == 'strat_pending':
                for key, maximum in (('tier', 2), ('step', 3), ('bets', 3)):
                    if type(pending.get(key)) is not int or not 0 <= pending[key] <= maximum:
                        raise ValueError('Invalid checkpoint pending ladder.')
                for key in ('staked', 'returned', 'net'):
                    if type(pending.get(key)) is not int:
                        raise ValueError('Invalid checkpoint pending accounting.')
                if pending['tier'] != state['tier'] or pending['step'] != state['step']:
                    raise ValueError('Checkpoint pending/state positions disagree.')
        for key in ('units', 'lose_streak', 'cooldown'):
            if type(value.get(key)) is not int:
                raise ValueError('Invalid checkpoint risk counters.')
        stats = value.get('stats')
        if not isinstance(stats, dict) or any(type(stats.get(k)) is not int or stats[k] < 0 for k in ('w', 'l')):
            raise ValueError('Invalid checkpoint statistics.')
        recent = value.get('recent_results')
        if not isinstance(recent, list) or len(recent) > 20 or any(type(x) is not int or x not in (0, 1) for x in recent):
            raise ValueError('Invalid checkpoint recent outcomes.')
        reports = value.get('strat_daily_reports')
        if not isinstance(reports, dict) or any(not isinstance(r, dict) for r in reports.values()):
            raise ValueError('Invalid checkpoint daily reports.')
        if not isinstance(value.get('policy'), dict):
            raise ValueError('Missing checkpoint policy signature.')
        # Reject NaN/Infinity and non-JSON values before touching SQL.
        json.dumps(value, allow_nan=False)
        return value

    def save(self, value):
        self.validate(value)
        payload = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        digest = hashlib.sha256(payload.encode()).hexdigest()
        with self.connect() as db:
            db.execute('INSERT OR REPLACE INTO engine_checkpoint VALUES(1,?,?)', (payload, digest))

    def load(self):
        with self.connect() as db:
            row = db.execute('SELECT payload,digest FROM engine_checkpoint WHERE id=1').fetchone()
        if row is None:
            return None
        if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
            raise ValueError('Engine checkpoint is unreadable; restore a database backup before starting.')
        try:
            return self.validate(json.loads(row[0]))
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError('Engine checkpoint is invalid; restore a database backup before starting.') from exc
