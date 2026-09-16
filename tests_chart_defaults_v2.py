from pathlib import Path

def test_chart_defaults():
    html=Path("templates/index.html").read_text()
    js=Path("static/js/chart.js").read_text()
    app=Path("static/js/app.js").read_text()
    assert 'hist-range-btn active" data-days="10"' in html
    assert 'hist-range-btn active" data-days="1"' not in html
    assert 'id="sig-btn"' in html and 'active" id="sig-btn"' not in html
    assert 'id="sr-toggle">' in html and 'id="sr-toggle" checked' not in html
    assert 'rsi: true, sig: false' in js
    assert 'pat: true, sr: false' in js
    assert 'function setHistoryRange(days = 10)' in js
    assert 'setHistoryRange(10);' in js
    assert 'srBtn.classList.remove("active")' in app
