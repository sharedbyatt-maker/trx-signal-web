from pathlib import Path

def test_clean_overlay_defaults_and_readable_10d_start():
    html=Path('templates/index.html').read_text(encoding='utf-8')
    js=Path('static/js/chart.js').read_text(encoding='utf-8')
    assert 'id="tl-toggle">' in html and 'id="tl-toggle" checked' not in html
    assert 'id="pat-toggle"' in html and 'id="pat-toggle" checked' not in html
    assert 'pat: false, sr: false, tl: false' in js
    assert 'group === 1 ? 320' in js
    assert 'setHistoryRange(days = 10)' in js

def test_multi_tf_fast_append_and_compact_font_guard():
    js=Path('static/js/chart.js').read_text(encoding='utf-8')
    css=Path('static/css/style.css').read_text(encoding='utf-8')
    assert 'group !== 1' not in js[js.index('function appendLatest'):js.index('function toggleSignals')]
    assert 'Math.floor(curMin / group)' in js
    assert 'curBars[curBars.length - 1] =' in js
    assert 'body { font-size: 12px; }' in css
    assert '.tf-btn { font-size: 10px; }' in css
