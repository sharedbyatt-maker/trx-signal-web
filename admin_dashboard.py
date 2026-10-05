"""Private operations console. No betting or strategy mutation controls."""
import copy
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from flask import jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash

DEFAULTS = {'timeframe': 1, 'range': 30, 'telegram': True, 'alerts': True,
            'indicators': {'ema': True, 'sma': False, 'bb': False, 'rsi': True,
                           'macd': False, 'stoch': False, 'tl': False, 'sr': False,
                           'pat': False, 'hss': False, 'sig': False}}

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def validate_settings(value):
    if not isinstance(value, dict) or set(value) != set(DEFAULTS):
        raise ValueError('Provide all chart and alert settings.')
    if type(value['timeframe']) is not int or value['timeframe'] not in (1, 5, 15, 60):
        raise ValueError('Timeframe must be 1, 5, 15 or 60 minutes.')
    if type(value['range']) is not int or value['range'] not in (1, 3, 10, 30):
        raise ValueError('Range must be 1, 3, 10 or 30 days.')
    if any(type(value[k]) is not bool for k in ('telegram', 'alerts')):
        raise ValueError('Alert settings must be on or off.')
    ind = value['indicators']
    if not isinstance(ind, dict) or set(ind) != set(DEFAULTS['indicators']) or any(type(x) is not bool for x in ind.values()):
        raise ValueError('Invalid indicator settings.')
    return copy.deepcopy(value)

class AdminStore:
    def __init__(self, path=None):
        self.path = Path(path or os.environ.get('ADMIN_DB_PATH', 'instance/admin.sqlite3'))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY, revision INTEGER, value TEXT);'
                             'CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT, kind TEXT, detail TEXT);')
            db.execute('INSERT OR IGNORE INTO settings VALUES(1,0,?)', (json.dumps(DEFAULTS),))
        self.cached = self.read()

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def read(self):
        with self.lock, self.connect() as db:
            rev, value = db.execute('SELECT revision,value FROM settings WHERE id=1').fetchone()
            return {'revision': rev, 'settings': json.loads(value)}

    def event(self, kind, detail):
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)', (utcnow(), kind, json.dumps(detail)))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')

    def events(self, limit=100):
        with self.lock, self.connect() as db:
            return [{'id': i, 'at': at, 'kind': kind, 'detail': json.loads(detail)} for i, at, kind, detail in
                    db.execute('SELECT id,at,kind,detail FROM events ORDER BY id DESC LIMIT ?', (limit,))]

    def save(self, value, revision, action='settings_saved'):
        value = validate_settings(value)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT revision,value FROM settings WHERE id=1').fetchone()
            if type(revision) is not int or revision != current[0]:
                raise RuntimeError('Settings changed in another session. Reload before saving.')
            rev = current[0] + 1
            db.execute('UPDATE settings SET revision=?,value=? WHERE id=1', (rev, json.dumps(value)))
            db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',
                       (utcnow(), action, json.dumps({'before': json.loads(current[1]), 'after': value, 'revision': rev})))
        self.cached = {'revision': rev, 'settings': value}
        return self.cached


def install_admin(core, health_fn, l1_service, cache_clear, password_hash=None, store=None):
    app = core.app
    store = store or AdminStore()
    if password_hash is None:
        password_hash = os.environ.get('ADMIN_PASSWORD_HASH', '')
        if not password_hash:
            config = Path(__file__).with_name('admin_bootstrap.json')
            if config.exists():
                password_hash = json.loads(config.read_text()).get('password_hash', '')
    app.secret_key = os.environ.get('ADMIN_SESSION_SECRET') or secrets.token_hex(32)
    app.config.update(SESSION_COOKIE_NAME='trx_admin', SESSION_COOKIE_HTTPONLY=True,
                      SESSION_COOKIE_SAMESITE='Strict', SESSION_COOKIE_SECURE=os.environ.get('ADMIN_COOKIE_SECURE', '1' if os.environ.get('RENDER') else '0') == '1',
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=1024 * 1024)
    attempts = OrderedDict()
    auth_lock = threading.Lock()
    maintenance_lock = threading.Lock()
    maintenance = {'status': 'idle', 'action': None, 'updated': None}
    action_times = {}
    csrf = lambda: session.setdefault('csrf', secrets.token_urlsafe(32))

    def authorized():
        return bool(session.get('admin') and time.time() - session.get('authenticated_at', 0) < 8 * 3600)

    def protect(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not authorized():
                return jsonify(error='Admin login required.'), 401
            if request.method != 'GET':
                supplied = request.headers.get('X-CSRF-Token', '')
                if not supplied or not hmac.compare_digest(supplied, session.get('csrf', '')):
                    return jsonify(error='Session verification failed. Reload the dashboard.'), 403
            return fn(*args, **kwargs)
        return wrapped

    @app.after_request
    def private_headers(response):
        if request.path.startswith(('/admin', '/api/admin')):
            response.headers.update({'Cache-Control': 'no-store', 'X-Frame-Options': 'DENY',
                                     'X-Content-Type-Options': 'nosniff', 'Referrer-Policy': 'same-origin',
                                     'Content-Security-Policy': "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-ancestors 'none'; form-action 'self'"})
        return response

    @app.route('/admin/login', methods=['GET', 'POST'])
    def admin_login():
        error = None
        if request.method == 'POST':
            if not hmac.compare_digest(request.form.get('csrf', ''), session.get('csrf', '')) or not session.get('csrf'):
                return render_template('admin_login.html', csrf=csrf(), error='Reload and try again.'), 403
            key = request.remote_addr or 'unknown'
            now = time.monotonic()
            with auth_lock:
                recent = [t for t in attempts.get(key, []) if now - t < 300]
                if len(recent) >= 5:
                    return render_template('admin_login.html', csrf=csrf(), error='Too many attempts. Try again in five minutes.'), 429
                attempts[key] = recent + [now]
                attempts.move_to_end(key)
                while len(attempts) > 1000:
                    attempts.popitem(last=False)
            password = request.form.get('password', '')
            if password_hash and len(password) <= 256 and check_password_hash(password_hash, password):
                with auth_lock:
                    attempts.pop(key, None)
                session.clear()
                session.update(admin=True, authenticated_at=time.time(), csrf=secrets.token_urlsafe(32))
                session.permanent = True
                store.event('login', {'result': 'success'})
                return redirect('/admin')
            error = 'Incorrect password.'
        return render_template('admin_login.html', csrf=csrf(), error=error, configured=bool(password_hash))

    @app.get('/admin')
    def admin_page():
        if not authorized():
            return redirect('/admin/login')
        return render_template('admin.html', csrf=csrf())

    @app.post('/api/admin/logout')
    @protect
    def logout():
        session.clear()
        return jsonify(ok=True)

    @app.get('/api/admin/status')
    @protect
    def status():
        result = health_fn()
        response = result[0] if isinstance(result, tuple) else result
        with maintenance_lock:
            job = dict(maintenance)
        health = response.get_json()
        health.setdefault('engine', {})['l1_thread_alive'] = bool(getattr(l1_service, '_thread', None) and l1_service._thread.is_alive())
        return jsonify(health=health, maintenance=job,
                       telegram_configured=bool(core.load_tg_config()),
                       storage={'persistent': bool(os.environ.get('ADMIN_PERSISTENT_STORAGE') == '1'),
                                'note': 'Export a backup before redeploying. Local settings and logs can reset on free hosting.'})

    @app.route('/api/admin/settings', methods=['GET', 'PUT'])
    @protect
    def settings():
        if request.method == 'GET':
            return jsonify(store.read())
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        try:
            result = store.save(data.get('settings'), data.get('revision'))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(result)

    @app.get('/api/admin/events')
    @protect
    def events():
        return jsonify(events=store.events())

    @app.get('/api/admin/reports')
    @protect
    def reports():
        report = core.api_strat_daily_report()
        if isinstance(report, tuple):
            return report
        l1 = l1_service.public_snapshot()
        with core.LOCK:
            signals = copy.deepcopy(list(core.signal_history)[-200:])
            steps = copy.deepcopy(list(core.STATE.get('strat_log') or [])[:200])
        return jsonify(l1=l1, twelve_step=report.get_json(), signals=list(reversed(signals)), step_signals=steps,
                       coverage={'l1_trades': 'Latest 100 retained trades; daily summary is today only.',
                                 'signals': 'Latest 200 retained signal entries.'})

    @app.get('/api/admin/backup')
    @protect
    def backup():
        response = jsonify(schema=1, exported_at=utcnow(), **store.read(), events=store.events(2000))
        response.headers['Content-Disposition'] = 'attachment; filename="trx-admin-backup.json"'
        return response

    @app.post('/api/admin/restore')
    @protect
    def restore():
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        if data.get('schema') != 1 or not isinstance(data.get('events', []), list) or len(data.get('events', [])) > 2000:
            return jsonify(error='Invalid backup file.'), 400
        try:
            value = validate_settings(data.get('settings'))
            imported = []
            for e in data.get('events', []):
                if not isinstance(e, dict) or not isinstance(e.get('at'), str) or not isinstance(e.get('kind'), str) or not isinstance(e.get('detail'), dict):
                    raise ValueError('Invalid backup event.')
                if len(e['at']) > 40 or len(e['kind']) > 80 or len(json.dumps(e['detail'])) > 16000:
                    raise ValueError('Backup event is too large.')
                imported.append(e)
            result = store.save(value, data.get('expected_revision'), 'backup_restored')
            for e in reversed(imported):
                store.event(e['kind'], {**e['detail'], 'imported_from_backup_at': e['at']})
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        return jsonify(result)

    @app.post('/api/admin/maintenance')
    @protect
    def run_maintenance():
        data = request.get_json(silent=True)
        action = data.get('action') if isinstance(data, dict) else None
        if action not in ('history_refresh', 'cache_refresh', 'telegram_test'):
            return jsonify(error='Unknown maintenance action.'), 400
        if action == 'telegram_test' and not store.cached['settings']['telegram']:
            return jsonify(error='Telegram is disabled. Enable it before testing.'), 409
        if action == 'telegram_test' and not core.load_tg_config():
            return jsonify(error='Telegram is not configured on the server.'), 409
        if action == 'history_refresh' and not (core._engine_thread and core._engine_thread.is_alive()):
            return jsonify(error='The data engine is not running.'), 503
        with maintenance_lock:
            if maintenance['status'] in ('queued', 'running'):
                return jsonify(error='Another maintenance job is running.'), 409
            now = time.monotonic()
            if now - action_times.get(action, -1000) < 30:
                return jsonify(error='Wait 30 seconds before repeating this action.'), 429
            action_times[action] = now
            maintenance.update(status='queued', action=action, updated=utcnow(), error=None)
        store.event('maintenance_queued', {'action': action})
        def finish(ok, error=None):
            with maintenance_lock:
                maintenance.update(status='complete' if ok else 'failed', updated=utcnow(), error=error)
            store.event('maintenance_complete' if ok else 'maintenance_failed', {'action': action, 'error': error})
        def work():
            try:
                with maintenance_lock:
                    maintenance['status'] = 'running'
                if action == 'cache_refresh':
                    cache_clear()
                    with core.LOCK:
                        core.STATE['backtest'] = None
                    finish(True)
                elif action == 'telegram_test':
                    result = core._send_telegram('✅ TRX Admin — Telegram Test OK', core.load_tg_config())
                    store.event('telegram', {'message': 'Admin connection test', 'result': result})
                    finish(result.startswith('sent'), None if result.startswith('sent') else result)
                else:
                    core._admin_history_refresh_requested.set()
                    deadline = time.monotonic() + 75
                    while core._admin_history_refresh_requested.is_set() and time.monotonic() < deadline:
                        time.sleep(.25)
                    if core._admin_history_refresh_requested.is_set():
                        finish(False, 'Refresh timed out. Check data feed status; the engine will retry.')
                    else:
                        result = core._admin_history_refresh_result
                        finish(bool(result.get('ok')), result.get('error'))
            except Exception as exc:
                finish(False, type(exc).__name__)
        threading.Thread(target=work, name='admin-maintenance', daemon=True).start()
        return jsonify(ok=True, status='queued'), 202

    app.context_processor(lambda: {'admin_defaults': store.cached['settings']})
    core._admin_store = store
    return store
