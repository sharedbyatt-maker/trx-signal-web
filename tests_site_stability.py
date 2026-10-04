import copy
import os
import time
from unittest.mock import patch

os.environ['TRX_NO_ENGINE'] = '1'
import app as composed
import app_core as core


def live_state():
    return {'connected': True, 'error': None, 'history': [{'issue':'20261004103010001','number':5,'type':'BIG','block_time':'2026-10-04 06:30:00'}], 'full_history': [], 'next_issue':'20261004103010002', 'last_result_received_mono':time.monotonic(), 'feed_delay':0, 'feed_health':{'status':'LIVE','seconds_since_advance':0}, 'strat':{'tier':0,'step':0,'pending':{'issue':'20261004103010002','target':'BIG','stake':200}}, 'strat_pending':{'issue':'20261004103010002','target':'BIG','stake':200}, 'log':[], 'last_update':None}


def test_public_state_expires_pending_without_mutating_engine():
    with patch.dict(core.STATE, live_state(), clear=True):
        core.STATE['last_result_received_mono'] -= 100
        before=copy.deepcopy(core.STATE)
        data=core.app.test_client().get('/api/state').get_json()
        assert data['feed_health']['status']=='STALE'
        assert data['strat_pending'] is None
        assert data['strat']['pending'] is None
        assert core.STATE==before


def test_health_ages_even_when_engine_and_health_publisher_stop():
    with patch.dict(core.STATE, live_state(), clear=True):
        core.STATE['last_result_received_mono'] -= 100
        response=core.app.test_client().get('/api/health')
        assert response.status_code==503
        assert response.get_json()['status']=='STALE'


def test_daily_report_does_not_publish_offline_pending():
    with patch.dict(core.STATE, live_state(), clear=True):
        core.STATE['connected']=False
        data=core.app.test_client().get('/api/12step/daily-report').get_json()
        assert data['report']['engine']['pending'] is None
        assert data['report']['engine']['status']=='OFFLINE'
        assert core.STATE['strat_pending'] is not None


def test_daily_report_defaults_to_round_calendar_not_host_date():
    with patch.dict(core.STATE, live_state(), clear=True):
        data=core.app.test_client().get('/api/12step/daily-report').get_json()
        assert data['report']['date']=='2026-10-04'
        assert core.app.test_client().get('/api/12step/daily-report?date=bad').status_code==400


def test_telemetry_and_live_snapshots_are_not_cacheable():
    with patch.dict(core.STATE,live_state(),clear=True):
        for path in ['/api/state','/api/latest','/api/history','/api/l1-capital','/api/12step/daily-report','/api/health']:
            assert 'no-store' in core.app.test_client().get(path).headers.get('Cache-Control','')


def test_parse_history_discards_invalid_values_without_dropping_good_rows():
    raw=[{'issue':'100','number':{}},{'issue':'101','number':float('inf')},{'issue':'102','number':5}]
    assert [x['issue'] for x in core.parse_history(raw)]==['102']


def test_drawing_json_array_and_nonfinite_revision_are_client_errors():
    client=core.app.test_client()
    with patch.dict(os.environ,{'DRAWINGS_SYNC_TOKEN':'test-local-only'}):
        for path, method, body in [('/api/drawings','put',[1]),('/api/drawings/restore','post',[1]),('/api/drawings','put',{'expected_revision':float('inf')}),('/api/drawings/restore','post',{'revision':float('inf'),'expected_revision':0})]:
            assert getattr(client,method)(path,json=body,headers={'X-Drawings-Token':'test-local-only'}).status_code==400


def test_telegram_error_does_not_expose_bot_token():
    with patch.object(core,'load_tg_config',return_value=('secret-test-token','test-chat',60,40,300)), patch.object(core,'_allow_browser_action',return_value=True), patch.object(core.requests,'post',side_effect=core.requests.ConnectionError('https://api.telegram.org/botsecret-test-token/sendMessage')):
        data=core.app.test_client().post('/api/telegram-test').get_json()
        assert 'secret-test-token' not in str(data)
