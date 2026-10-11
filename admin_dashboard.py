"""Private operations console with opt-in manual real orders; no automated orders."""
import copy
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import OrderedDict
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from functools import wraps
from pathlib import Path

from strategy_settings import MONEY_DEFAULTS, STRATEGY_INFO, validate_money, ladder
from telegram_controls import TELEGRAM_DEFAULTS, validate_telegram, validate_streak, CredentialVault, validate_credentials
from feed_connection import DEFAULT_FEED, validate_feed, public_feed, request_feed, masked_key
from trongrid_feed import DEFAULT_TRONGRID, validate_trongrid, public_trongrid, TronGridFeed
from feed_utils import source_age_seconds
from core_notifications import format_streak_telegram
from telegram_messages import MESSAGE_DEFAULTS, VARIABLES, ENGINES, KINDS, validate_messages, render_message

from flask import jsonify, redirect, render_template, request, session
from werkzeug.security import check_password_hash, generate_password_hash

DEFAULTS = {'timeframe': 1, 'range': 30, 'telegram': True, 'alerts': True,
            'indicators': {'ema': True, 'sma': False, 'bb': False, 'rsi': True,
                           'macd': False, 'stoch': False, 'tl': False, 'sr': False,
                           'pat': False, 'hss': False, 'sig': False}}

def utcnow():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')

def csrf_matches(supplied, expected):
    return bool(isinstance(supplied, str) and isinstance(expected, str) and supplied and
                expected and supplied.isascii() and expected.isascii() and hmac.compare_digest(supplied, expected))

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
                             'CREATE TABLE IF NOT EXISTS issued_stakes(issue TEXT PRIMARY KEY, stake INTEGER);'
                             'CREATE TABLE IF NOT EXISTS private_state(name TEXT PRIMARY KEY, revision INTEGER, value TEXT);')
            for name, value in {**MONEY_DEFAULTS, 'telegram': TELEGRAM_DEFAULTS, 'messages': MESSAGE_DEFAULTS}.items():
                db.execute('INSERT OR IGNORE INTO controls VALUES(?,0,?)', (name,json.dumps(value)))
        self.vault = CredentialVault(self.path)
        self.refresh_controls()

    @contextmanager
    def connect(self):
        # sqlite's own context manager commits/rolls back but does not close.
        # Feed reads happen continuously, so waiting for cyclic GC can retain
        # thousands of native page caches and descriptors on a 512 MB host.
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def read(self):
        with self.lock, self.connect() as db:
            rev, value = db.execute('SELECT revision,value FROM settings WHERE id=1').fetchone()
            return {'revision': rev, 'settings': json.loads(value)}

    def event(self, kind, detail):
        with self.lock, self.connect() as db:
            db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)', (utcnow(), kind, json.dumps(detail)))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')

    def events(self, limit=100, kind=None, before=None, search=''):
        with self.lock, self.connect() as db:
            clauses, args = [], []
            if kind in ('audit', 'telegram'):
                clauses.append('kind != ?' if kind == 'audit' else 'kind = ?'); args.append('telegram')
            if before is not None:
                clauses.append('id < ?'); args.append(before)
            if search:
                # Literal substring matching: SQL wildcard characters are not search syntax.
                clauses.append('(instr(lower(kind || detail), lower(?)) > 0 OR instr(detail, ?) > 0)'); args.extend((search,json.dumps(search)[1:-1]))
            where = ' WHERE ' + ' AND '.join(clauses) if clauses else ''
            return [{'id': i, 'at': at, 'kind': kind, 'detail': json.loads(detail)} for i, at, kind, detail in
                    db.execute('SELECT id,at,kind,detail FROM events' + where + ' ORDER BY id DESC LIMIT ?', (*args, limit))]

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
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')
            db.commit()
            self.cached = {'revision': rev, 'settings': value}
            return copy.deepcopy(self.cached)

    def refresh_controls(self):
        with self.lock, self.connect() as db:
            self.controls = {name: {'revision':rev,'settings':json.loads(value)} for name,rev,value in db.execute('SELECT name,revision,value FROM controls')}
            self.controls['telegram']['settings']=validate_telegram(self.controls['telegram']['settings'])
            self.timelines = {name: [{'revision':r,'after_issue':int(i),'settings':json.loads(v)} for r,i,v in db.execute('SELECT revision,after_issue,value FROM money_changes WHERE engine=? ORDER BY revision',(name,))] for name in MONEY_DEFAULTS}
            self.issued = dict(db.execute('SELECT issue,stake FROM issued_stakes'))

    def control(self,name):
        with self.lock:
            return copy.deepcopy(self.controls[name])

    def money_history(self,name):
        with self.lock:
            return copy.deepcopy(self.timelines[name])

    def save_control(self,name,value,revision,after_issue=None):
        value = validate_telegram(value) if name=='telegram' else validate_messages(value) if name=='messages' else validate_money(name,value)
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT revision,value FROM controls WHERE name=?',(name,)).fetchone()
            if type(revision) is not int or revision!=old[0]:
                raise RuntimeError('Settings changed in another session. Reload before saving.')
            rev=old[0]+1
            if name in MONEY_DEFAULTS:
                if type(after_issue) is not int or after_issue<=0:raise ValueError('A live source issue is required.')
                db.execute('INSERT INTO money_changes VALUES(?,?,?,?)',(name,rev,str(after_issue),json.dumps(value)))
            db.execute('UPDATE controls SET revision=?,value=? WHERE name=?',(rev,json.dumps(value),name))
            detail = {'before':json.loads(old[1]),'after':value,'revision':rev,'after_issue':str(after_issue) if after_issue is not None else None}
            if name == 'messages':
                previous=json.loads(old[1])['templates']
                detail={'revision':rev,'changed_templates':[key for key,text in value['templates'].items() if text!=previous[key]]}
            db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',(utcnow(),name+'_settings_saved',json.dumps(detail)))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')
            db.commit()
            self.refresh_controls()
            return self.control(name)

    def restore_bundle(self, value, revision, controls, timelines, issued, imported, boundary, expected_controls=None):
        """Commit the complete validated bundle once; failures leave caches and SQL untouched."""
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old = db.execute('SELECT revision,value FROM settings WHERE id=1').fetchone()
            if type(revision) is not int or revision != old[0]:
                raise RuntimeError('Settings changed in another session. Reload before restoring.')
            if expected_controls is not None:
                for name in controls:
                    current = db.execute('SELECT revision FROM controls WHERE name=?', (name,)).fetchone()[0]
                    if expected_controls.get(name) != current:
                        raise RuntimeError('Control settings changed in another session. Reload before restoring.')
            rev = old[0] + 1
            db.execute('UPDATE settings SET revision=?,value=? WHERE id=1', (rev,json.dumps(value)))
            for name,item in controls.items():
                if boundary is None:
                    current = db.execute('SELECT revision FROM controls WHERE name=?',(name,)).fetchone()[0]
                    newrev = item['revision'] if name in MONEY_DEFAULTS else max(current+1,item['revision'])
                else:
                    newrev = db.execute('SELECT revision FROM controls WHERE name=?',(name,)).fetchone()[0] + 1
                    if name in MONEY_DEFAULTS:
                        db.execute('INSERT INTO money_changes VALUES(?,?,?,?)',(name,newrev,str(boundary),json.dumps(item['settings'])))
                db.execute('UPDATE controls SET revision=?,value=? WHERE name=?',(newrev,json.dumps(item['settings']),name))
            if controls and boundary is None:
                for name,changes in timelines.items():
                    for change in changes:
                        db.execute('INSERT INTO money_changes VALUES(?,?,?,?)',(name,change['revision'],str(change['after_issue']),json.dumps(change['settings'])))
                for issue,amount in issued.items():
                    db.execute('INSERT OR IGNORE INTO issued_stakes VALUES(?,?)',(str(issue),amount))
            for event in reversed(imported):
                db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',(utcnow(),event['kind'],json.dumps({**event['detail'],'imported_from_backup_at':event['at']})))
            db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',(utcnow(),'backup_restored',json.dumps({'revision':rev,'groups':list(controls),'after_issue':str(boundary) if boundary else None})))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')
            db.commit()
            self.cached = {'revision':rev,'settings':copy.deepcopy(value)}
            self.refresh_controls()
            return copy.deepcopy(self.cached)

    def lock_stake(self,issue,stake):
        with self.lock, self.connect() as db:
            if str(issue) not in self.issued:
                db.execute('INSERT OR IGNORE INTO issued_stakes VALUES(?,?)',(str(issue),int(stake)))
                self.issued[str(issue)]=int(stake)
            return self.issued[str(issue)]

    def money_snapshot(self,name):
        with self.lock:
            return copy.deepcopy(self.timelines[name]),dict(self.issued),copy.deepcopy(self.controls[name]["settings"])

    def private_get(self,name):
        with self.lock, self.connect() as db:
            row=db.execute('SELECT revision,value FROM private_state WHERE name=?',(name,)).fetchone()
            return {'revision':row[0],'value':row[1]} if row else {'revision':0,'value':None}

    def private_save(self,name,value,revision,detail):
        with self.lock, self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            old=db.execute('SELECT revision FROM private_state WHERE name=?',(name,)).fetchone()
            current=old[0] if old else 0
            if type(revision) is not int or current!=revision:raise RuntimeError('Settings changed. Reload before saving.')
            db.execute('INSERT OR REPLACE INTO private_state VALUES(?,?,?)',(name,current+1,value))
            db.execute('INSERT INTO events(at,kind,detail) VALUES(?,?,?)',(utcnow(),name+'_changed',json.dumps(detail)))
            db.execute('DELETE FROM events WHERE id NOT IN (SELECT id FROM events ORDER BY id DESC LIMIT 2000)')
            return current+1

    def feed_config(self):
        state=self.private_get('feed')
        if state['value']:
            try:value=json.loads(self.vault.cipher.decrypt(state['value'].encode()))
            except Exception:raise ValueError('API credentials could not be read. Re-enter the connection settings.') from None
        else:value=copy.deepcopy(DEFAULT_FEED)
        return state['revision'],value

    def save_feed(self,value,revision):
        encrypted=self.vault.cipher.encrypt(json.dumps(value).encode()).decode()
        return self.private_save('feed',encrypted,revision,public_feed(value))

    def trongrid_config(self):
        state=self.private_get('trongrid')
        if state['value']:
            try:value=validate_trongrid(json.loads(self.vault.cipher.decrypt(state['value'].encode())))
            except Exception:raise ValueError('TronGrid credentials are unreadable. Re-enter the key or clear the connection.') from None
        else:value=copy.deepcopy(DEFAULT_TRONGRID)
        return state['revision'],value

    def save_trongrid(self,value,revision):
        value=validate_trongrid(value)
        encrypted=self.vault.cipher.encrypt(json.dumps(value).encode()).decode()
        return self.private_save('trongrid',encrypted,revision,public_trongrid(value))

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

    def current_auth():
        state=store.private_get('password')
        return state['revision'],state['value'] or password_hash

    def authorized():
        return bool(session.get('auth_revision',0)==current_auth()[0] and session.get('admin') and time.time() - session.get('authenticated_at', 0) < 8 * 3600)

    def protect(fn):
        @wraps(fn)
        def wrapped(*args, **kwargs):
            if not authorized():
                return jsonify(error='Admin login required.'), 401
            if request.method != 'GET':
                supplied = request.headers.get('X-CSRF-Token', '')
                if not csrf_matches(supplied, session.get('csrf', '')):
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
            if not csrf_matches(request.form.get('csrf', ''), session.get('csrf', '')):
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
            auth_revision,active_hash=current_auth()
            if active_hash and len(password) <= 256 and check_password_hash(active_hash, password):
                with auth_lock:
                    attempts.pop(key, None)
                after_login = session.get('history_sync_after_login')
                session.clear()
                session.update(admin=True, auth_revision=auth_revision, authenticated_at=time.time(), csrf=secrets.token_urlsafe(32))
                session.permanent = True
                store.event('login', {'result': 'success'})
                if isinstance(after_login,str) and re.fullmatch(r'/admin/trxchart-sync\?bridge=[a-f0-9]{48}',after_login):
                    return redirect(after_login)
                return redirect('/admin')
            error = 'Incorrect password.'
        return render_template('admin_login.html', csrf=csrf(), error=error, configured=bool(current_auth()[1]))

    @app.get('/admin')
    def admin_page():
        if not authorized():
            return redirect('/admin/login')
        return render_template('admin.html', csrf=csrf())

    @app.get('/admin/trxchart-sync-open')
    def history_sync_open():
        # A cross-site popup initially withholds SameSite=Strict cookies. Load
        # this inert same-origin document first without changing the session.
        # Its navigation then reaches the authenticated page with normal cookies.
        if not re.fullmatch(r'[a-f0-9]{48}',request.args.get('bridge','')):
            return 'Open browser sync from Trade Results.',400
        return render_template('trxchart_sync_open.html')

    @app.get('/admin/trxchart-sync')
    def history_sync_page():
        bridge=request.args.get('bridge','')
        if not re.fullmatch(r'[a-f0-9]{48}',bridge):
            return 'Open browser sync from Trade Results.',400
        if not authorized():
            session['history_sync_after_login']='/admin/trxchart-sync?bridge='+bridge
            return redirect('/admin/login')
        return render_template('trxchart_sync.html',csrf=csrf())

    @app.post('/api/admin/password')
    @protect
    def change_password():
        data=request.get_json(silent=True)
        data=data if isinstance(data,dict) else {}
        old,new,confirm=data.get('current'),data.get('new'),data.get('confirm')
        if not all(isinstance(v,str) for v in (old,new,confirm)):return jsonify(error='Enter current, new and confirmation passwords.'),400
        if not 12<=len(new)<=128 or new!=confirm:return jsonify(error='Use 12–128 characters and matching confirmation.'),400
        with auth_lock:
            key='change:'+str(request.remote_addr)
            recent=[t for t in attempts.get(key,[]) if time.monotonic()-t<300]
            if len(recent)>=5:return jsonify(error='Too many attempts. Wait five minutes.'),429
            attempts[key]=recent+[time.monotonic()]
            rev,active_hash=current_auth()
            if len(old)>256 or not check_password_hash(active_hash,old):return jsonify(error='Current password is incorrect.'),403
            if new==old:return jsonify(error='Choose a different new password.'),400
            try:store.private_save('password',generate_password_hash(new),rev,{'sessions':'invalidated'})
            except RuntimeError as exc:return jsonify(error=str(exc)),409
        session.clear()
        return jsonify(ok=True,login_required=True)

    def candidate_feed(data):
        try:revision,current=store.feed_config()
        except ValueError:
            if not all(k in data for k in DEFAULT_FEED):raise ValueError('Re-enter the complete API connection to replace unreadable credentials.')
            revision,current=store.private_get('feed')['revision'],copy.deepcopy(DEFAULT_FEED)
        value={key:data.get(key,current[key]) for key in DEFAULT_FEED}
        if not data.get('key') and value['auth']==current['auth'] and value['url']==current['url'] and value['key_name']==current['key_name']:
            value['key']=current['key']
        if value['auth']=='none':value['key']=''
        return revision,validate_feed(value)

    def probe_feed(value):
        import requests
        from types import SimpleNamespace
        response=request_feed(SimpleNamespace(get=getattr(core,'_feed_probe_get',requests.get)),value,50,10)
        if response.status_code!=200:raise ValueError('API check failed: HTTP '+str(response.status_code))
        try:payload=response.json()
        except ValueError:raise ValueError('API must return JSON.') from None
        raw=payload if isinstance(payload,list) else payload.get('data',[]) if isinstance(payload,dict) else []
        if not isinstance(raw,list) or len(raw)>10000:raise ValueError('API check returned an invalid data array.')
        if not hasattr(core,'parse_history'):raise ValueError('Feed parser is unavailable.')
        rows=core.parse_history(raw)
        if len(rows)<14:raise ValueError('At least 14 valid rounds are required. Expected issueNumber/issue, number and blockTime fields.')
        if hasattr(core,'source_time_iso') and not core.source_time_iso(rows[-1].get('block_time')):
            raise ValueError('Candidate API must include a valid blockTime/time for the latest round.')
        age=source_age_seconds(rows[-1].get('block_time'))
        if age is None or age>300 or age< -90:raise ValueError('Candidate API round time is stale or in the future.')
        with core.LOCK:live=copy.deepcopy(core.STATE.get('history') or [])
        if not live:raise ValueError('Wait for a live connection before switching API sources.')
        recent={r['issue']:r['number'] for r in live[-50:]}
        overlap=[r for r in rows if r['issue'] in recent]
        if len(overlap)<3 or any(recent[r['issue']]!=r['number'] for r in overlap):raise ValueError('Candidate API does not match recent live TRX rounds.')
        if int(rows[-1]['issue'])<int(live[-1]['issue']):raise ValueError('Candidate API is behind the live source. Try again after it updates.')
        return {'ok':True,'rows':len(rows),'latest_issue':str(rows[-1]['issue']),'matched_rounds':len(overlap)}

    @app.route('/api/admin/feed',methods=['GET','PUT'])
    @protect
    def feed_settings():
        if request.method=='PUT':
            data=request.get_json(silent=True)
            data=data if isinstance(data,dict) else {}
            try:
                revision,value=candidate_feed(data)
                if type(data.get('revision')) is not int or data['revision']!=revision:raise RuntimeError('API settings changed. Reload before saving.')
                check=probe_feed(value)
                if not authorized():return jsonify(error='Admin session expired during API verification.'),401
                store.save_feed(value,revision)
                if hasattr(core,'_admin_history_refresh_requested'):core._admin_history_refresh_requested.set()
                try:cache_clear()
                except Exception:pass
            except ValueError as exc:return jsonify(error=str(exc)),400
            except RuntimeError as exc:return jsonify(error=str(exc)),409
            except Exception:return jsonify(error='API connection could not be checked. Settings were not changed.'),502
        try:
            revision,value=store.feed_config()
            return jsonify(revision=revision,settings=public_feed(value),defaults=public_feed(DEFAULT_FEED))
        except ValueError as exc:return jsonify(revision=store.private_get('feed')['revision'],settings=public_feed(DEFAULT_FEED),defaults=public_feed(DEFAULT_FEED),error=str(exc))

    @app.post('/api/admin/feed/check')
    @protect
    def check_feed():
        data=request.get_json(silent=True)
        data=data if isinstance(data,dict) else {}
        try:
            _,value=candidate_feed(data)
            return jsonify(probe_feed(value))
        except ValueError as exc:return jsonify(error=str(exc)),400
        except Exception:return jsonify(error='API check unavailable. No settings were changed.'),502

    def candidate_trongrid(data):
        try:revision,current=store.trongrid_config()
        except ValueError:
            revision,current=store.private_get('trongrid')['revision'],DEFAULT_TRONGRID
        key=data.get('key') or current['key']
        return revision,validate_trongrid({'mode':data.get('mode',current['mode']),'key':key})

    def probe_trongrid(value):
        if not value['key']:raise ValueError('Enter a TronGrid API key before checking.')
        with core.LOCK:live=copy.deepcopy(core.STATE.get('history') or [])
        if not live:raise ValueError('Wait for live TRX rounds before checking TronGrid.')
        response=TronGridFeed().fetch(value['key'],live,probe=True)
        rows=response.json()
        recent={r['issue']:r['number'] for r in live[-50:]}
        return {'ok':True,'rows':len(rows),'matched_rounds':sum(r['issueNumber'] in recent for r in rows),
                'latest_issue':rows[-1]['issueNumber'],'note':'No settings changed. No wallet transaction or Telegram message sent.'}

    @app.get('/api/admin/feed/status')
    @protect
    def feed_runtime_status():
        saved={}
        for name,read in [('primary',store.feed_config),('trongrid',store.trongrid_config)]:
            try:
                revision,value=read()
                saved[name]={'revision':revision,'key_hint':masked_key(value['key']),
                             **({'endpoint':value['url'],'auth':value['auth']} if name=='primary' else {'mode':value['mode']})}
            except ValueError:
                saved[name]={'error':'Credentials unreadable. Reload or re-enter settings.'}
        with core.LOCK:runtime=copy.deepcopy(core.STATE.get('feed_runtime') or {})
        age=source_age_seconds(runtime.get('last_success_at'))
        runtime['success_age_sec']=age
        source=runtime.get('source','unknown')
        mode=saved.get('trongrid',{}).get('mode')
        current=saved.get(source,{})
        matches=bool(current and 'revision' in current and current['revision']==runtime.get('revision'))
        if (source=='trongrid' and mode=='disabled') or (source=='primary' and mode=='live'):matches=False
        state='waiting' if not runtime.get('outcome') else 'error' if runtime.get('outcome')=='error' else 'pending' if not matches else 'stale' if age is None or age>80 else 'active'
        return jsonify(saved=saved,runtime=runtime,state=state,settings_applied=matches)

    @app.route('/api/admin/trongrid',methods=['GET','PUT','DELETE'])
    @protect
    def trongrid_settings():
        if request.method!='GET':
            data=request.get_json(silent=True)
            data=data if isinstance(data,dict) else {}
            try:
                revision,value=candidate_trongrid(data)
                if type(data.get('revision')) is not int or data['revision']!=revision:
                    raise RuntimeError('TronGrid settings changed. Reload before saving.')
                if request.method=='DELETE':value=copy.deepcopy(DEFAULT_TRONGRID)
                elif value['mode']!='disabled':probe_trongrid(value)
                if not authorized():return jsonify(error='Admin session expired during TronGrid verification.'),401
                store.save_trongrid(value,revision)
                from trongrid_feed import LIVE_TRONGRID
                LIVE_TRONGRID.clear()
            except ValueError as exc:return jsonify(error=str(exc)),400
            except RuntimeError as exc:return jsonify(error=str(exc)),409
            except Exception:return jsonify(error='TronGrid verification failed. Settings were not changed.'),502
        try:
            revision,value=store.trongrid_config()
            with core.LOCK:source=core.STATE.get('data_source','primary')
            return jsonify(revision=revision,settings=public_trongrid(value),active_source=source)
        except ValueError as exc:
            return jsonify(revision=store.private_get('trongrid')['revision'],settings=public_trongrid(DEFAULT_TRONGRID),error=str(exc))

    @app.post('/api/admin/trongrid/check')
    @protect
    def check_trongrid():
        data=request.get_json(silent=True)
        data=data if isinstance(data,dict) else {}
        try:
            _,value=candidate_trongrid(data)
            return jsonify(probe_trongrid(value))
        except ValueError as exc:return jsonify(error=str(exc)),400
        except Exception:return jsonify(error='TronGrid check unavailable. No settings were changed.'),502

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
                                'note': 'Free Render can lose local settings on deployment, platform restart or spin-down. Export backups; password and API keys require persistent storage.'})

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
                       changes=[{**c,'after_issue':str(c['after_issue'])} for c in store.money_history(name)[-20:]])

    @app.route('/api/admin/telegram', methods=['GET','PUT'])
    @protect
    def telegram_controls():
        if request.method=='PUT':
            data=request.get_json(silent=True)
            data=data if isinstance(data,dict) else {}
            value=data.get('settings')
            if isinstance(value,dict) and 'streak' not in value:
                value={**value,'streak':store.control('telegram')['settings']['streak']}
            try:store.save_control('telegram',value,data.get('revision'))
            except ValueError as exc:return jsonify(error=str(exc)),400
            except RuntimeError as exc:return jsonify(error=str(exc)),409
        cfg=core.load_tg_config()
        try:override=store.credential_override()
        except ValueError:override=None
        return jsonify(**store.control('telegram'),defaults=TELEGRAM_DEFAULTS,
                       credentials={'configured':bool(cfg),'source':'Admin override' if override else 'Server configuration',
                                    'chat_mask':('…'+str(cfg[1])[-4:]) if cfg else '', 'token_set':bool(cfg),'error':getattr(core,'_tg_config_error',None)},timezone='Asia/Bangkok')

    @app.post('/api/admin/telegram/streak/preview')
    @protect
    def streak_preview():
        data=request.get_json(silent=True)
        try:
            cfg=validate_streak(data.get('streak') if isinstance(data,dict) else None)
            side='SMALL' if cfg['side']=='SMALL' else 'BIG'
            sample={'issue':'20261007103010001','block_time':'2026-10-07 12:00:00'}
            original=format_streak_telegram(sample,side,cfg['start'])
            template=store.control('messages')['settings']['templates']['market.streak']
            return jsonify(**render_message(template,original,'market','streak'),sample=True,note='Sample preview only. Nothing is sent to Telegram.')
        except ValueError as exc:return jsonify(error=str(exc)),400

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

    @app.route('/api/admin/telegram/messages', methods=['GET','PUT'])
    @protect
    def message_settings():
        if request.method == 'PUT':
            data = request.get_json(silent=True)
            data = data if isinstance(data,dict) else {}
            try:store.save_control('messages',data.get('settings'),data.get('revision'))
            except ValueError as exc:return jsonify(error=str(exc)),400
            except RuntimeError as exc:return jsonify(error=str(exc)),409
        return jsonify(**store.control('messages'),defaults=MESSAGE_DEFAULTS,variables=VARIABLES,engines=ENGINES,categories=KINDS)

    @app.post('/api/admin/telegram/messages/preview')
    @protect
    def message_preview():
        data = request.get_json(silent=True)
        data = data if isinstance(data,dict) else {}
        engine,category = data.get('engine'),data.get('category')
        if not isinstance(engine,str) or not isinstance(category,str) or engine not in ENGINES or category not in KINDS:return jsonify(error='Unknown message channel.'),400
        base=store.control(engine)['settings']['base'] if engine in MONEY_DEFAULTS else None
        sample = f'{ENGINES[engine]} · {category.upper()} · SAMPLE\nPreview only — no message sent.\nIssue: 20261005103010001\n' + (f'Stake: {base:,} MMK\nTarget: B' if base else 'Market alert example · RSI: 61.0')
        recent=next((e['detail']['original'] for e in store.events(200,'telegram') if e['detail'].get('engine')==engine and e['detail'].get('category')==category and e['detail'].get('original')),None)
        if recent:sample=recent
        try:return jsonify(**render_message(data.get('template'),sample,engine,category),sample=not bool(recent))
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
        try:
            before=int(request.args['before']) if 'before' in request.args else None
            limit=min(500,max(1,int(request.args.get('limit',500))))
        except ValueError:return jsonify(error='Invalid log cursor.'),400
        kind=request.args.get('kind')
        if kind not in (None,'audit','telegram'):return jsonify(error='Unknown log type.'),400
        rows=store.events(limit,kind,before,request.args.get('search','')[:200])
        return jsonify(events=rows,next_before=rows[-1]['id'] if len(rows)==limit else None)

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

    def journal_read():
        from trade_journal import DEFAULT_LIMITS
        state=store.private_get('trade_journal')
        try:
            value=json.loads(store.vault.cipher.decrypt(state['value'].encode())) if state['value'] else {'limits':copy.deepcopy(DEFAULT_LIMITS),'rows':[]}
        except Exception:
            raise ValueError('Trade journal storage is unreadable. Preserve your exported history before replacing storage.') from None
        return state['revision'],value

    from trxchart_account_sync import HistorySync, ProviderError
    store.history_sync = HistorySync(store)

    @app.get('/api/admin/trxchart-account/check')
    @protect
    def check_trxchart_login_page():
        try:
            return jsonify(store.history_sync.check_login_page())
        except ProviderError as exc:
            return jsonify(ok=False, error=str(exc)), 502

    @app.route('/api/admin/trxchart-account', methods=['GET', 'POST', 'DELETE'])
    @protect
    def trxchart_account():
        try:
            if request.method == 'POST':
                store.history_sync.connect(request.get_json(silent=True))
                if os.environ.get('TRX_NO_ENGINE') != '1':
                    store.history_sync.start()
            elif request.method == 'DELETE':
                store.history_sync.disconnect()
            return jsonify(store.history_sync.public())
        except ProviderError as exc:
            return jsonify(error=str(exc)), 502
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409

    @app.post('/api/admin/trxchart-account/refresh')
    @protect
    def refresh_trxchart_account():
        try:
            return jsonify(store.history_sync.refresh())
        except ValueError as exc:
            return jsonify(error=str(exc)), 400

    from trxchart_bet import OrderService, OrderError
    store.orders = OrderService(store.history_sync, store)

    @app.route('/api/admin/trxchart-order', methods=['GET', 'POST'])
    @protect
    def trxchart_order():
        try:
            if request.method == 'GET':
                return jsonify(store.orders.status())
            data = request.get_json(silent=True)
            data = data if isinstance(data, dict) else {}
            return jsonify(store.orders.place(data.get('direction'), data.get('amount'),
                                              data.get('confirm'), data.get('mode'), data.get('request_id')))
        except OrderError as exc:
            return jsonify(error=str(exc)), exc.status
        except ProviderError as exc:
            return jsonify(error=str(exc)), 502
        except sqlite3.Error:
            return jsonify(error='Order storage is unavailable. Check REAL history before another order; a submitted request will not be retried.'), 503

    @app.route('/api/admin/trade-journal',methods=['GET','PUT'])
    @protect
    def trade_journal():
        from trade_journal import limits,snapshot
        try:
            revision,value=journal_read()
            if request.method=='PUT':
                data=request.get_json(silent=True) or {}
                if not isinstance(data,dict):raise ValueError('Invalid journal settings.')
                value['limits']=limits(data.get('limits'))
                snapshot(value,revision,request.args.get('mode','real'),request.args.get('date'))
                revision=store.private_save('trade_journal',store.vault.cipher.encrypt(json.dumps(value).encode()).decode(),data.get('revision'),{'action':'limits_saved'})
            return jsonify(snapshot(value,revision,request.args.get('mode','real'),request.args.get('date')))
        except ValueError as exc:return jsonify(error=str(exc)),400
        except RuntimeError as exc:return jsonify(error=str(exc)),409

    @app.post('/api/admin/trade-journal/import')
    @protect
    def import_trade_journal():
        from trade_journal import normalize,merge,snapshot
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='Invalid history import.'),400
        try:
            revision,value=journal_read()
            if type(data.get('revision')) is not int or data['revision']!=revision:raise RuntimeError('Journal changed. Refresh journal before importing.')
            mode=data.get('mode','real')
            incoming=normalize(data.get('history'),mode,data.get('source_timezone','Asia/Yangon'))
            value['rows'],counts=merge(value['rows'],incoming)
            value['imported_at']=utcnow()
            result=snapshot(value,revision,mode,data.get('date'))
            revision=store.private_save('trade_journal',store.vault.cipher.encrypt(json.dumps(value).encode()).decode(),revision,{'action':'history_imported',**counts})
            result['revision']=revision
            return jsonify(**result,import_result=counts)
        except ValueError as exc:return jsonify(error=str(exc)),400
        except RuntimeError as exc:return jsonify(error=str(exc)),409

    @app.post('/api/admin/trade-journal/sync')
    @protect
    def sync_trade_journal():
        from trade_journal import normalize,merge,snapshot
        data=request.get_json(silent=True)
        if not isinstance(data,dict):return jsonify(error='Invalid history sync.'),400
        try:
            mode=data.get('mode')
            zone=data.get('source_timezone')
            history=data.get('history')
            # Empty successful histories are normal for unused Real/Demo accounts.
            empty=isinstance(history,dict) and history.get('success') is True and history.get('list')==[] and history.get('mode',mode)==mode
            if empty:
                if mode not in ('real','demo') or zone not in ('Asia/Bangkok','Asia/Yangon','UTC'):raise ValueError('Invalid history mode or timezone.')
                incoming=[]
            else:incoming=normalize(history,mode,zone)
            # Merge against current state atomically; a browser refresh cannot
            # overwrite another mode, manual import, or saved target settings.
            with store.lock:
                revision,value=journal_read()
                value['rows'],counts=merge(value['rows'],incoming)
                value['imported_at']=utcnow()
                value.setdefault('synced_at',{})[mode]=value['imported_at']
                revision=store.private_save('trade_journal',store.vault.cipher.encrypt(json.dumps(value).encode()).decode(),revision,{'action':'browser_history_synced','mode':mode,**counts})
                return jsonify(**snapshot(value,revision,mode),import_result=counts)
        except ValueError as exc:return jsonify(error=str(exc)),400
        except RuntimeError as exc:return jsonify(error=str(exc)),409

    @app.get('/api/admin/trade-journal/export')
    @protect
    def export_trade_journal():
        from trade_journal import export_rows
        try:
            _,value=journal_read()
            response=jsonify(export_rows(value,request.args.get('mode','real')))
            response.headers['Content-Disposition']='attachment; filename="trx-private-trade-history.json"'
            return response
        except ValueError as exc:return jsonify(error=str(exc)),400

    @app.get('/api/admin/backup')
    @protect
    def backup():
        with store.lock:
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
            response = jsonify(schema=2, exported_at=utcnow(), **store.read(), events=kept,
                               expected_control_revisions={name:item['revision'] for name,item in store.controls.items()},
                               events_truncated=len(kept) < len(events), controls=store.controls, money_changes={name:[{**c,"after_issue":str(c["after_issue"])} for c in changes] for name,changes in store.timelines.items()}, issued_stakes=store.issued)
            response.headers['Content-Disposition'] = 'attachment; filename="trx-admin-backup.json"'
            return response

    @app.post('/api/admin/restore')
    @protect
    def restore():
        data = request.get_json(silent=True)
        data = data if isinstance(data, dict) else {}
        if type(data.get('schema')) is not int or data['schema'] not in (1,2) or not isinstance(data.get('events', []), list) or len(data.get('events', [])) > 2000:
            return jsonify(error='Invalid backup file.'), 400
        try:
            value = validate_settings(data.get('settings'))
            imported = []
            for e in data.get('events', []):
                if not isinstance(e, dict) or not isinstance(e.get('at'), str) or not isinstance(e.get('kind'), str) or not isinstance(e.get('detail'), dict):
                    raise ValueError('Invalid backup event.')
                if len(e['at']) > 40 or len(e['kind']) > 80 or len(json.dumps(e['detail'])) > 65536:
                    raise ValueError('Backup event is too large.')
                imported.append(e)
            controls=data.get('controls',{})
            if not isinstance(controls,dict) or (controls and set(controls) not in ({'l1','twelve','telegram'}, {'l1','twelve','telegram','messages'})):raise ValueError('Invalid control backup.')
            expected_controls=data.get('expected_control_revisions')
            if expected_controls is not None or (data['schema']==2 and controls):
                if not isinstance(expected_controls,dict) or not set(controls)<=set(expected_controls) or any(type(expected_controls[n]) is not int or expected_controls[n]<0 for n in controls):
                    raise ValueError('Reload control settings before restoring this backup.')
            for name,item in controls.items():
                if not isinstance(item,dict) or type(item.get('revision')) is not int or not 0<=item['revision']<=1000000000:raise ValueError('Invalid control revision.')
                item['settings']=(validate_telegram if name=='telegram' else validate_messages if name=='messages' else lambda v:validate_money(name,v))(item.get('settings'))
            timelines=data.get('money_changes',{})
            issued=data.get('issued_stakes',{})
            if controls:
                if not isinstance(timelines,dict) or set(timelines)!=set(MONEY_DEFAULTS) or not isinstance(issued,dict):raise ValueError('Invalid monetary history.')
                for name,changes in timelines.items():
                    if not isinstance(changes,list):raise ValueError('Invalid monetary history.')
                    seen=set()
                    for c in changes:
                        if not isinstance(c,dict):raise ValueError('Invalid monetary history.')
                        if isinstance(c.get('after_issue'),str) and len(c['after_issue'])<=20 and c['after_issue'].isascii() and c['after_issue'].isdigit():c['after_issue']=int(c['after_issue'])
                        if type(c.get('revision')) is not int:raise ValueError('Invalid monetary revision.')
                        if c.get('revision') in seen:raise ValueError('Duplicate monetary revision.')
                        seen.add(c.get('revision'))
                        if type(c.get('revision')) is not int or not 0<c['revision']<=1000000000 or type(c.get('after_issue')) is not int or c['after_issue']<=0:raise ValueError('Invalid monetary boundary.')
                        validate_money(name,c.get('settings'))
                    if changes and (max(c['revision'] for c in changes)!=controls[name]['revision'] or max(changes,key=lambda c:c['revision'])['settings']!=controls[name]['settings']):raise ValueError('Control and monetary history disagree.')
                    if not changes and (controls[name]['revision'] or controls[name]['settings']!=MONEY_DEFAULTS[name]):raise ValueError('Missing monetary history.')
                if any(not str(i).isascii() or not str(i).isdigit() or len(str(i))>20 or type(v) is not int or not 0<v<=1000000000 for i,v in issued.items()):raise ValueError('Invalid issued stake history.')
                ordered = {name: sorted(changes,key=lambda c:c['revision']) for name,changes in timelines.items()}
                for changes in ordered.values():
                    if any(b['after_issue'] < a['after_issue'] for a,b in zip(changes,changes[1:])):
                        raise ValueError('Monetary boundaries must be chronological.')
            # Hold the engine boundary and store locks across the complete transaction.
            with core.LOCK, store.lock:
                # Default money does not mean a running engine is a fresh install.
                fresh = not (any(store.control(n)['revision'] for n in MONEY_DEFAULTS) or
                             any(store.timelines.values()) or store.issued or
                             core.STATE.get('history') or core.STATE.get('full_history') or
                             getattr(core,'last_issue',None) or getattr(core,'_money_processing_issue',None) or
                             core.STATE.get('pending') or core.STATE.get('strat_pending') or
                             (getattr(core,'_engine_thread',None) and core._engine_thread.is_alive()) or
                             getattr(l1_service,'snapshot',{}).get('source_issue'))
                boundary = live_boundary() if controls and not fresh else None
                result = store.restore_bundle(value,data.get('expected_revision'),controls,timelines,issued,imported,boundary,expected_controls)
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        except RuntimeError as exc:
            return jsonify(error=str(exc)), 409
        except sqlite3.Error:
            return jsonify(error='Backup could not be committed. No settings were changed.'),503
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
        try:
            store.event('maintenance_queued', {'action': action})
        except sqlite3.Error:
            with maintenance_lock:
                maintenance.update(status='failed', updated=utcnow(), error='Audit storage unavailable. No maintenance action was started.')
                action_times.pop(action, None)
            return jsonify(error=maintenance['error']),503
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
