import os
os.environ['TRX_NO_ENGINE'] = '1'

import time
import requests
import app


class Resp:
    def __init__(self, issue, status=200):
        self.status_code = status
        self._issue = issue
    def json(self):
        return {'data': [{'issueNumber': self._issue, 'number': 5, 'blockTime': '2026-09-06 16:00:00'}]}


def test_cache_busting_and_advancement():
    seen = []
    seq = [Resp('20260906000100'), Resp('20260906000101')]
    def fake(url, *a, **kw):
        seen.append(url)
        return seq.pop(0)
    old = app._original_session_get
    try:
        app._original_session_get = fake
        app._feed_cache.clear()
        app._feed_health.update({'last_issue':'', 'last_advance':0.0, 'last_http_ok':0.0})
        app._resilient_session_get(app.core.URL_DATA + '?limit=50')
        first = app._feed_health['last_issue']
        app._resilient_session_get(app.core.URL_DATA + '?limit=50')
        assert first == '20260906000100'
        assert app._feed_health['last_issue'] == '20260906000101'
        assert all('_trx_nonce=' in u for u in seen), seen
        assert seen[0] != seen[1]
    finally:
        app._original_session_get = old


def test_stale_200_does_not_look_live_forever():
    old = app._original_session_get
    old_stale = app.FEED_STALE_SEC
    try:
        app.FEED_STALE_SEC = 0.01
        app._original_session_get = lambda *a, **kw: Resp('20260906000200')
        app._feed_cache.clear()
        app._feed_health.update({'last_issue':'', 'last_advance':0.0, 'last_http_ok':0.0})
        app._resilient_session_get(app.core.URL_DATA + '?limit=50')
        time.sleep(0.02)
        app._resilient_session_get(app.core.URL_DATA + '?limit=50')
        assert app.core.STATE['feed_health']['status'] == 'STALE'
    finally:
        app._original_session_get = old
        app.FEED_STALE_SEC = old_stale


def test_timeout_grace_requires_recent_data():
    old = app._original_session_get
    try:
        app._feed_cache.clear()
        now = time.monotonic()
        cached = Resp('20260906000300')
        app._feed_cache[app.core.URL_DATA + '?limit=50'] = (now, cached)
        app._feed_health.update({'last_issue':'20260906000300', 'last_advance':now, 'last_http_ok':now})
        def boom(*a, **kw):
            raise requests.ReadTimeout('x')
        app._original_session_get = boom
        got = app._resilient_session_get(app.core.URL_DATA + '?limit=50')
        assert got is cached
        assert app.core.STATE['feed_health']['status'] == 'DEGRADED'
        app._feed_health['last_advance'] = now - app.FEED_STALE_SEC - 5
        try:
            app._resilient_session_get(app.core.URL_DATA + '?limit=50')
        except requests.ReadTimeout:
            pass
        else:
            raise AssertionError('stale cache must not mask timeout')
        assert app.core.STATE['feed_health']['status'] == 'OFFLINE'
    finally:
        app._original_session_get = old


if __name__ == '__main__':
    test_cache_busting_and_advancement()
    test_stale_200_does_not_look_live_forever()
    test_timeout_grace_requires_recent_data()
    print('LIVE FEED DEEP TESTS: ALL PASSED')
