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

from strategy_settings import MONEY_DEFAULTS, STRATEGY_INFO, validate_money, ladder
from telegram_controls import TELEGRAM_DEFAULTS, validate_telegram, CredentialVault, validate_credentials

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
        with self.connect() as db:
            db.executescript('CREATE TABLE IF NOT EXISTS controls(name TEXT PRIMARY KEY, revision INTEGER, value TEXT);'
                             'CREATE TABLE IF NOT EXISTS money_changes(engine TEXT, revision INTEGER, after_issue TEXT, value TEXT, PRIMARY KEY(engine,revision));'
                             'CREATE TABLE IF NOT EXISTS issued_stakes(issue TEXT PRIMARY KEY, stake INTEGER);')
            for name, value in {**MONEY_DEFAULTS, 'telegram': TELEGRAM_DEFAULTS}.items():
                db.execute('INSERT OR IGNORE INTO controls VALUES(?,0,?)', (name,json.dumps(value)))
        self.vault = CredentialVault(self.path)
        self.refresh_controls()

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
            db.commit()
            self.cached = {'revision': rev, 'settings': value}
            return copy.deepcopy(self.cached)

    def refresh_controls(self):
        with self.lock, self.connect() as db:
            self.controls = {name: {'revision':rev,'settings':json.loads(value)} for name,rev,value in db.execute('SELECT name,revision,value FROM controls')}
            self.timelines = {name: [{'revision':r,'after_issue':int(i),'settings':json.loads(v)} for r,i,v in db.execute('SELECT revision,after_issue,value FROM money_changes WHERE engine=? ORDER BY revision',(name,))] for name in MONEY_DEFAULTS}
            self.issued = dict(db.execute('SELECT issue,stake FROM issued_stakes'))

    def control(self,name):
        with self.lock:
            return copy.deepcopy(self.controls[name])

    def money_history(self,name):
        with self.lock:
            return copy.deepcopy(self.timelines[name])

    def save_control(self,name,value,revision,after_issue=None):
        value = validate_telegram(value) if name=='telegram' else validate_money(name,value)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT revision,value FROM controls WHERE name=?',(name,)).fetchone()
            if type(revision) is not int or revision!=old[0]:
                raise RuntimeError('Settings changed in another session. Reload before saving.')
            rev=old[0]+1
            if name!='telegram':
                if type(after_issue) is not int or after_issue<=0:raise ValueError('A live source issue is required.')
                db.execute('INSERT INTO money_changes VALUES(?,?,?,?)',(name,rev,str(after_issue),json.dumps(value)))
            db.execute('UPDATE controls SET revision=?,value=? WHERE name=?',(rev,json.dumps(value),name))
            db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',(utcnow(),name+'_settings_saved',json.dumps({'before':json.loads(old[1]),'after':value,'revision':rev,'after_issue':after_issue})))
            db.commit()
            self.refresh_controls()
            return self.control(name)

    def lock_stake(self,issue,stake):
        with self.lock, self.connect() as db:
            if str(issue) not in self.issued:
                db.execute('INSERT OR IGNORE INTO issued_stakes VALUES(?,?)',(str(issue),int(stake)))
                self.issued[str(issue)]=int(stake)
            return self.issued[str(issue)]

    def money_snapshot(self,name):
        with self.lock:
            return copy.deepcopy(self.timelines[name]),dict(self.issued),copy.deepcopy(self.controls[name]["settings"])

    def credential_override(self):
        with self.lock:
            return self.vault.read()



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
                      PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=8 * 1024 * 1024)
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

    def live_boundary():
        rows=core.STATE.get('history') or []
        if not rows or not core.STATE.get('connected'):
            raise ValueError('Wait for a live data connection before changing money settings.')
        if hasattr(core,'public_feed_health') and core.public_feed_health(core.STATE)['status'] not in ('LIVE','DEGRADED'):
            raise ValueError('Wait for a live data connection before changing money settings.')
        values=[rows[-1]['issue'],getattr(core,'last_issue',None),getattr(core,'_money_processing_issue',None)]
        source=getattr(l1_service,'snapshot',{}).get('source_issue')
        return max(int(x) for x in values+[source] if x)

    @app.route('/api/admin/strategies/<name>', methods=['GET','PUT'])
    @protect
    def strategies(name):
        if name not in MONEY_DEFAULTS:return jsonify(error='Unknown strategy.'),404
        if request.method=='PUT':
            data=request.get_json(silent=True)
            data=data if isinstance(data,dict) else {}
            try:
                with core.LOCK:
                    boundary=live_boundary()
                    result=store.save_control(name,data.get('settings'),data.get('revision'),boundary)
            except ValueError as exc:return jsonify(error=str(exc)),400
            except RuntimeError as exc:return jsonify(error=str(exc)),409
        else:result=store.control(name)
        return jsonify(**result, defaults=MONEY_DEFAULTS[name], info=STRATEGY_INFO[name], ladder=ladder(result['settings']),
                       effective='New stakes use settings after the current completed source issue. Already issued stakes stay fixed.',
                       changes=store.money_history(name)[-20:])

    @app.route('/api/admin/telegram', methods=['GET','PUT'])
    @protect
    def telegram_controls():
        if request.method=='PUT':
            data=request.get_json(silent=True)
            data=data if isinstance(data,dict) else {}
            try:store.save_control('telegram',data.get('settings'),data.get('revision'))
            except ValueError as exc:return jsonify(error=str(exc)),400
            except RuntimeError as exc:return jsonify(error=str(exc)),409
        cfg=core.load_tg_config()
        return jsonify(**store.control('telegram'),defaults=TELEGRAM_DEFAULTS,
                       credentials={'configured':bool(cfg),'source':'Admin override' if store.credential_override() else 'Server configuration',
                                    'chat_mask':('…'+str(cfg[1])[-4:]) if cfg else '', 'token_set':bool(cfg)},timezone='Asia/Bangkok')

    @app.route('/api/admin/telegram/credentials',methods=['PUT','DELETE'])
    @protect
    def credentials():
        try:
            with store.lock:
                if request.method=='DELETE':store.vault.clear()
                else:
                    data=request.get_json(silent=True)
                    data=data if isinstance(data,dict) else {}
                    cfg=core.load_tg_config()
                    token=data.get('token') or (cfg[0] if cfg else '')
                    token,chat=validate_credentials(token,data.get('chat'))
                    store.vault.save(token,chat)
            store.event('telegram_credentials_changed',{'action':'use_server_config' if request.method=='DELETE' else 'override_saved'})
            return jsonify(ok=True)
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.post('/api/admin/telegram/check')
    @protect
    def check_bot():
        cfg=core.load_tg_config()
        if not cfg:return jsonify(error='Telegram is not configured.'),409
        try:
            import requests
            response=requests.get('https://api.telegram.org/bot'+cfg[0]+'/getMe',timeout=10)
            data=response.json()
            if response.status_code!=200 or not data.get('ok'):return jsonify(error='Telegram HTTP '+str(response.status_code)),502
            return jsonify(ok=True,username=data['result'].get('username'),note='Bot token verified. Use Send test to verify chat delivery.')
        except Exception:return jsonify(error='Telegram connection unavailable.'),502

    @app.get('/api/admin/events')
    @protect
    def events():
        return jsonify(events=store.events(500))

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
        events = store.events(2000)
        monetary_size=len(json.dumps({"controls":store.controls,"money_changes":store.timelines,"issued_stakes":store.issued}).encode("utf-8"))
        event_budget=max(0,800000-monetary_size)
        kept, size = [], 0
        for event in events:
            event_size = len(json.dumps(event).encode('utf-8')) + 2
            if size + event_size > event_budget:
                break
            kept.append(event)
            size += event_size
        response = jsonify(schema=1, exported_at=utcnow(), **store.read(), events=kept,
                           events_truncated=len(kept) < len(events), controls=store.controls, money_changes=store.timelines, issued_stakes=store.issued)
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
            controls=data.get('controls',{})
            if controls and (not isinstance(controls,dict) or set(controls)!={'l1','twelve','telegram'}):raise ValueError('Invalid control backup.')
            for name,item in controls.items():
                if not isinstance(item,dict) or type(item.get('revision')) is not int or item['revision']<0:raise ValueError('Invalid control revision.')
                (validate_telegram if name=='telegram' else lambda v:validate_money(name,v))(item.get('settings'))
            timelines=data.get('money_changes',{})
            issued=data.get('issued_stakes',{})
            if controls:
                if not isinstance(timelines,dict) or set(timelines)!=set(MONEY_DEFAULTS) or not isinstance(issued,dict):raise ValueError('Invalid monetary history.')
                for name,changes in timelines.items():
                    if not isinstance(changes,list):raise ValueError('Invalid monetary history.')
                    seen=set()
                    for c in changes:
                        if not isinstance(c,dict):raise ValueError('Invalid monetary history.')
                        if type(c.get('revision')) is not int:raise ValueError('Invalid monetary revision.')
                        if c.get('revision') in seen:raise ValueError('Duplicate monetary revision.')
                        seen.add(c.get('revision'))
                        if type(c.get('revision')) is not int or c['revision']<=0 or type(c.get('after_issue')) is not int or c['after_issue']<=0:raise ValueError('Invalid monetary boundary.')
                        validate_money(name,c.get('settings'))
                    if changes and (max(c['revision'] for c in changes)!=controls[name]['revision'] or max(changes,key=lambda c:c['revision'])['settings']!=controls[name]['settings']):raise ValueError('Control and monetary history disagree.')
                    if not changes and (controls[name]['revision'] or controls[name]['settings']!=MONEY_DEFAULTS[name]):raise ValueError('Missing monetary history.')
                if any(not str(i).isdigit() or type(v) is not int or not 0<v<=1000000000 for i,v in issued.items()):raise ValueError('Invalid issued stake history.')
                # Historical timelines may be restored only into a fresh install.
                # On an active install, changes apply causally after the live issue.
                with core.LOCK:
                    boundary=live_boundary() if any(store.control(n)['revision'] for n in MONEY_DEFAULTS) else None
            result = store.save(value, data.get('expected_revision'), 'backup_restored')
            if controls:
                with core.LOCK, store.lock, store.connect() as db:
                    if boundary is None:
                        for name,item in controls.items():
                            db.execute('UPDATE controls SET revision=?,value=? WHERE name=?',(item['revision'],json.dumps(item['settings']),name))
                        for name,changes in timelines.items():
                            for c in changes:db.execute('INSERT INTO money_changes VALUES(?,?,?,?)',(name,c['revision'],str(c['after_issue']),json.dumps(c['settings'])))
                        for issue,amount in issued.items():db.execute('INSERT OR IGNORE INTO issued_stakes VALUES(?,?)',(issue,amount))
                        db.commit();store.refresh_controls()
                    else:
                        for name,item in controls.items():store.save_control(name,item['settings'],store.control(name)['revision'],boundary)

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
                    if not store.cached['settings']['telegram']:
                        finish(False,'Telegram was disabled before the test started.')
                        return
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
