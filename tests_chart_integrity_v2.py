from pathlib import Path


def test_integrity_v2_contracts():
    js = Path('static/js/chart.js').read_text(encoding='utf-8')
    html = Path('templates/index.html').read_text(encoding='utf-8')
    assert 'function calcStoch(bars, period = 14' in js
    assert 'bars[j].h' in js and 'bars[j].l' in js
    assert 'calcStoch(curBars, 14, 3, 3)' in js
    assert 'structuralLookbackBars(curBars.length)' in js
    assert 'const days = tf === 1 ? 3 : 30;' in js
    assert 'bars.slice(-structuralLookbackBars(bars.length))' in js
    assert 'n - structuralLookbackBars(n)' in js
    assert 'Trend model: BIG -> +1 step, SMALL -> -1 step' in js
    assert 'id="chart-model-note"' not in html
    assert 'STOCH H/L/C 14·3·3' in html


