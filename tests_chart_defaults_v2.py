from tests_admin_dashboard import render_terminal_defaults
from pathlib import Path

def test_chart_defaults():
    html=render_terminal_defaults()
    js=Path("static/js/chart.js").read_text()
    app=Path("static/js/app.js").read_text()
    assert '<option value="30" selected>30D</option>' in html
    assert 'hist-range-btn active" data-days="1"' not in html
    assert 'id="sig-btn"' in html and 'active" id="sig-btn"' not in html
    assert 'id="sr-toggle">' in html and 'id="sr-toggle" checked' not in html
    assert 'sig: document.body?.dataset.adminSignals' in js
    assert 'pat: false, sr: false, tl: false' in js
    assert 'function setHistoryRange(days = 30)' in js
    assert 'group === 1 ? 320' in js
    assert 'srBtn.classList.remove("active")' in app


