"""Notification delivery policy and write-only local credential overrides."""
import copy
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from cryptography.fernet import Fernet

TELEGRAM_DEFAULTS={'engines':{'l1':True,'twelve':True,'market':True},
 'types':{'signal':True,'result':True,'wait':True,'withdrawal':True,'daily':True,'radar':True,'rsi':True,'streak':True},
 'quiet':{'enabled':False,'start':'22:00','end':'07:00'}}

def validate_telegram(value):
    if not isinstance(value,dict) or set(value)!=set(TELEGRAM_DEFAULTS):raise ValueError('Invalid Telegram settings.')
    for group in ('engines','types'):
        if not isinstance(value[group],dict) or set(value[group])!=set(TELEGRAM_DEFAULTS[group]) or any(type(v) is not bool for v in value[group].values()):
            raise ValueError('Invalid engine / message controls.')
    q=value['quiet']
    if not isinstance(q,dict) or set(q)!={'enabled','start','end'} or type(q['enabled']) is not bool:
        raise ValueError('Invalid quiet hours.')
    for key in ('start','end'):
        if not isinstance(q[key],str) or not re.fullmatch(r'(?:[01]\d|2[0-3]):[0-5]\d',q[key]):raise ValueError('Use HH:MM for quiet hours.')
    if q['enabled'] and q['start']==q['end']:raise ValueError('Quiet-hour start and end must differ.')
    return copy.deepcopy(value)

def classify(text):
    title=str(text).split('\n')[0].upper()
    engine='l1' if 'L1 CAPITAL' in title else 'twelve' if any(x in title for x in ('12-STEP','12 STEP','BET WON','TIER FAILED','STEP LOST')) else 'market'
    if 'WITHDRAWAL' in title:kind='withdrawal'
    elif 'DAILY' in title:kind='daily'
    elif 'RADAR' in title:kind='radar'
    elif 'STREAK' in title:kind='streak'
    elif any(x in title for x in ('RESULT','WON','LOST','FAILED','BUST')):kind='result'
    elif 'WAIT' in title:kind='wait'
    elif 'RSI' in title:kind='rsi'
    else:kind='signal'
    return engine,kind

def allowed(policy,engine,kind,now=None):
    if not policy['engines'].get(engine,False) or not policy['types'].get(kind,False):return False
    q=policy['quiet']
    if q['enabled']:
        now=now or datetime.now(ZoneInfo('Asia/Bangkok'))
        hhmm=now.astimezone(ZoneInfo('Asia/Bangkok')).strftime('%H:%M')
        within=q['start']<=hhmm<q['end'] if q['start']<q['end'] else hhmm>=q['start'] or hhmm<q['end']
        if within:return False
    return True

class CredentialVault:
    def __init__(self,db_path):
        self.path=Path(db_path).with_suffix('.credentials')
        key_path=Path(db_path).with_suffix('.key')
        if not key_path.exists():
            fd,tmp=tempfile.mkstemp(dir=key_path.parent,prefix='.vault-key-')
            try:
                with os.fdopen(fd,'wb') as f:f.write(Fernet.generate_key())
                try:os.link(tmp,key_path)
                except FileExistsError:pass
            finally:os.unlink(tmp)
        self.cipher=Fernet(key_path.read_bytes())
    def read(self):
        if not self.path.exists():return None
        try:
            value=json.loads(self.cipher.decrypt(self.path.read_bytes()))
            validate_credentials(value['token'],value['chat'])
            return value
        except Exception:
            raise ValueError('Telegram credential override is unreadable. Replace credentials or use server configuration.') from None
    def save(self,token,chat):
        fd,tmp=tempfile.mkstemp(dir=self.path.parent,prefix='.vault-write-')
        try:
            with os.fdopen(fd,'wb') as f:f.write(self.cipher.encrypt(json.dumps({'token':token,'chat':chat}).encode()))
            os.replace(tmp,self.path)
        finally:
            if os.path.exists(tmp):os.unlink(tmp)
    def clear(self):
        self.path.unlink(missing_ok=True)

def validate_credentials(token,chat):
    if not isinstance(token,str) or not re.fullmatch(r'\d{5,20}:[A-Za-z0-9_-]{20,100}',token):raise ValueError('Enter a valid bot token from BotFather.')
    if not isinstance(chat,str) or not re.fullmatch(r'(?:-?\d{1,20}|@[A-Za-z0-9_]{5,64})',chat):raise ValueError('Enter a numeric chat ID or @channel username.')
    return token,chat
