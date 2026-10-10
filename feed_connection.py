"""Private, write-only feed credentials and compatible TRX history connections."""
import ipaddress
import re
import socket
from urllib.parse import urlsplit, urlencode
import requests

DEFAULT_FEED={'url':'https://trxchart.com/api/trx-data','auth':'none','key_name':'X-API-Key','key':''}

def validate_feed(value,resolve=True):
    if not isinstance(value,dict) or set(value)!=set(DEFAULT_FEED):raise ValueError('Invalid API connection settings.')
    url=value['url']
    if not isinstance(url,str) or len(url)>1000:raise ValueError('Invalid endpoint URL.')
    p=urlsplit(url)
    if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment or p.port not in (None,443):
        raise ValueError('Use an HTTPS endpoint without query parameters, credentials or a custom port.')
    if p.hostname.lower()=='localhost' or '.' not in p.hostname:raise ValueError('Use a public API hostname.')
    if resolve:
        try:addresses={r[4][0] for r in socket.getaddrinfo(p.hostname,443,type=socket.SOCK_STREAM)}
        except OSError:raise ValueError('API hostname could not be resolved.') from None
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):raise ValueError('Private network endpoints are not allowed.')
    if value['auth'] not in ('none','bearer','header','query'):raise ValueError('Choose an authentication method.')
    name=value['key_name']
    if not isinstance(name,str) or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,60}',name):raise ValueError('Invalid API key field name.')
    if value['auth']=='header' and name.lower() in ('host','cookie','connection','content-length','authorization','proxy-authorization'):
        raise ValueError('Use Bearer token for Authorization, or a dedicated API key header.')
    if value['auth']=='query' and name.lower()=='limit':raise ValueError('The limit parameter is reserved for history requests.')
    key=value['key']
    if not isinstance(key,str) or len(key)>512 or any(ord(c)<32 or ord(c)==127 for c in key):raise ValueError('Invalid API key.')
    if value['auth'] in ('bearer','header') and not key.isascii():raise ValueError('Header / bearer keys must use ASCII characters.')
    if value['auth']!='none' and not key:raise ValueError('An API key is required for this authentication method.')
    return dict(value)

def public_feed(config):
    return {k:v for k,v in config.items() if k!='key'} | {'key_set':bool(config['key'])}

def masked_key(key):
    """Admin-only identity hint; never disclose an entire short credential."""
    return '••••' + key[-4:] if len(key)>4 else 'Stored (hidden)' if key else 'No API key'

def feed_request_parts(config,limit,extra_query=None):
    headers={'Cache-Control':'no-cache','Pragma':'no-cache'}
    query={'limit':limit} if limit is not None else {}
    query.update(extra_query or {})
    if config['auth']=='bearer':headers['Authorization']='Bearer '+config['key']
    elif config['auth']=='header':headers[config['key_name']]=config['key']
    elif config['auth']=='query':query[config['key_name']]=config['key']
    return config['url']+'?'+urlencode(query),headers

def request_feed(http,config,limit,timeout):
    url,headers=feed_request_parts(config,limit)
    try:
        return http.get(url,timeout=timeout,headers=headers,allow_redirects=False)
    except requests.RequestException as exc:
        raise ValueError('Feed connection unavailable: '+type(exc).__name__) from None

