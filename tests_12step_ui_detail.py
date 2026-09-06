from pathlib import Path

def test_template_ids_and_assets():
    h=Path('templates/index.html').read_text(encoding='utf-8')
    for x in ('st-status','st-trigger','st-source','d12-episode-wr','d12-roi','d12-activity','d12-edge'):
        assert f'id="{x}"' in h, x

def test_js_detail_wiring():
    app=Path('static/js/app.js').read_text(encoding='utf-8')
    daily=Path('static/js/daily12.js').read_text(encoding='utf-8')
    assert 'pend.trigger_rsi' in app and 'pend.trigger_rule' in app
    for x in ('roi_pct','episode_win_rate','edge_vs_break_even','recent_events','next_eligible_stake'):
        assert x in daily, x

def test_strategy_constants_untouched():
    s=Path('app_core.py').read_text(encoding='utf-8')
    assert 'RSI_STRAT_OVERSOLD = 32.0' in s
    assert 'RSI_STRAT_OVERBOUGHT = 68.0' in s
    assert '[200, 400, 600, 1200]' in s
    assert '[2500, 5000, 10000, 20000]' in s
    assert '[40000, 80000, 160000, 320000]' in s

if __name__=='__main__':
    test_template_ids_and_assets(); test_js_detail_wiring(); test_strategy_constants_untouched()
    print('12-STEP UI DETAIL TESTS: ALL PASSED')
