from pathlib import Path


def rep(path, old, new):
    p=Path(path); s=p.read_text(encoding='utf-8')
    if old not in s: raise SystemExit(f'not found: {old}')
    p.write_text(s.replace(old,new,1),encoding='utf-8')

rep('static/js/chart.js','ema: true, sma: false, bb: false, rsi: true, sig: true,\n    pat: true, sr: true, tl: true, macd: false, stoch: false,','ema: true, sma: false, bb: false, rsi: true, sig: false,\n    pat: true, sr: false, tl: true, macd: false, stoch: false,')
rep('static/js/chart.js','function setHistoryRange(days = 1) {','function setHistoryRange(days = 10) {')
rep('static/js/chart.js','const wanted = Math.max(1, Math.ceil((Number(days) || 1) * 1440 / Math.max(1, group)));','const wanted = Math.max(1, Math.ceil((Number(days) || 10) * 1440 / Math.max(1, group)));')
rep('static/js/chart.js','// Default analytical view: one full day, not the old ~320-bar (~5h) slice.\n    setHistoryRange(1);','// Default analytical view: full loaded 10-day history.\n    setHistoryRange(10);')
rep('static/js/app.js','  srBtn.classList.add("active");   // S/R checkbox defaults to ON\n','  srBtn.classList.remove("active"); // Auto S/R defaults to OFF\n')
# Remove duplicate comment while touching this block.
rep('static/js/app.js','/* Auto S/R toggle (find & show / hide) + signal arrows toggle */\n/* Auto S/R toggle (find & show / hide) + signal arrows toggle */','/* Auto S/R toggle (find & show / hide) + signal arrows toggle */')

Path('tests_chart_defaults_v2.py').write_text('''from pathlib import Path\n\ndef test_chart_defaults():\n    html=Path("templates/index.html").read_text()\n    js=Path("static/js/chart.js").read_text()\n    app=Path("static/js/app.js").read_text()\n    assert 'hist-range-btn active" data-days="10"' in html\n    assert 'hist-range-btn active" data-days="1"' not in html\n    assert 'id="sig-btn"' in html and 'active" id="sig-btn"' not in html\n    assert 'id="sr-toggle">' in html and 'id="sr-toggle" checked' not in html\n    assert 'rsi: true, sig: false' in js\n    assert 'pat: true, sr: false' in js\n    assert 'function setHistoryRange(days = 10)' in js\n    assert 'setHistoryRange(10);' in js\n    assert 'srBtn.classList.remove("active")' in app\n''')
