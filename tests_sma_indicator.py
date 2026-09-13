from pathlib import Path

chart = Path('static/js/chart.js').read_text(encoding='utf-8')
tpl = Path('templates/index.html').read_text(encoding='utf-8')
e2e = Path('e2e/chart.spec.js').read_text(encoding='utf-8')

assert 'id="sma-toggle"' in tpl
assert 'SMA 20/50' in tpl
assert 'let sma20Series = null;' in chart
assert 'let sma50Series = null;' in chart
assert 'ema: true, sma: false, bb: false' in chart
assert 'bindOpt("sma-toggle", "sma")' in chart
assert 'const sma20 = smaArr(closes, 20);' in chart
assert 'const sma50 = smaArr(closes, 50);' in chart
assert 'sma20Series.setData(linePoints(sma20));' in chart
assert 'sma50Series.setData(linePoints(sma50));' in chart
assert 'bbMidSeries.setData(linePoints(sma20));' in chart
assert 'sma20Series.update({time,value:mean20});' in chart
assert 'sma50Series.update({time,value:mean50});' in chart
assert "page.locator('#sma-toggle').check()" in e2e
print('SMA 20/50 indicator checks passed')
