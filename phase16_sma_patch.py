from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'pattern not found in {path}: {old[:140]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# ---- template: add SMA toggle + user-facing label, bump chart asset version ----
replace_once(
    'templates/index.html',
    'EMA 5/15 · BB 20·2 · RSI 14 · MACD · Trendlines · S/R · Patterns · 10-Day History',
    'EMA 5/15 · SMA 20/50 · BB 20·2 · RSI 14 · MACD · Trendlines · S/R · Patterns · 10-Day History'
)
replace_once(
    'templates/index.html',
    '<label class="chart-toggle"><input type="checkbox" id="ema-toggle" checked> EMA</label>\n      <label class="chart-toggle"><input type="checkbox" id="bb-toggle"> BB</label>',
    '<label class="chart-toggle"><input type="checkbox" id="ema-toggle" checked> EMA</label>\n      <label class="chart-toggle" title="SMA 20 = short trend · SMA 50 = medium trend"><input type="checkbox" id="sma-toggle"> SMA 20/50</label>\n      <label class="chart-toggle"><input type="checkbox" id="bb-toggle"> BB</label>'
)
replace_once(
    'templates/index.html',
    "<script src=\"{{ url_for('static', filename='js/chart.js') }}?v=41\"></script>",
    "<script src=\"{{ url_for('static', filename='js/chart.js') }}?v=42\"></script>"
)

# ---- chart series / state ----
replace_once(
    'static/js/chart.js',
    '   Features: Candles/Area · TF grouping ×1..×50 · EMA 5/15 · Bollinger Bands',
    '   Features: Candles/Area · TF grouping ×1..×50 · EMA 5/15 · SMA 20/50 · Bollinger Bands'
)
replace_once(
    'static/js/chart.js',
    '  let emaLongSeries = null;\n  let bbUpperSeries = null;',
    '  let emaLongSeries = null;\n  let sma20Series = null;\n  let sma50Series = null;\n  let bbUpperSeries = null;'
)
replace_once(
    'static/js/chart.js',
    '  let opts = {\n    ema: true, bb: false, rsi: true, sig: true,',
    '  let opts = {\n    ema: true, sma: false, bb: false, rsi: true, sig: true,'
)

# ---- live path: share SMA20 with BB middle, add SMA50 ----
replace_once(
    'static/js/chart.js',
    '''    if (closes.length >= 20) {\n      const tail20 = closes.slice(-20);\n      const mean20 = tail20.reduce((a,b)=>a+b,0) / 20;\n      let var20 = 0;\n      for (const v of tail20) var20 += (v - mean20) ** 2;\n      const sd20 = Math.sqrt(var20 / 20);\n      bbUpperSeries.update({time,value:mean20 + 2 * sd20});\n      bbMidSeries.update({time,value:mean20});\n      bbLowerSeries.update({time,value:mean20 - 2 * sd20});\n    }''',
    '''    if (closes.length >= 20) {\n      const tail20 = closes.slice(-20);\n      const mean20 = tail20.reduce((a,b)=>a+b,0) / 20;\n      let var20 = 0;\n      for (const v of tail20) var20 += (v - mean20) ** 2;\n      const sd20 = Math.sqrt(var20 / 20);\n      // SMA20 and BB middle are mathematically identical: compute once, fan out.\n      sma20Series.update({time,value:mean20});\n      bbUpperSeries.update({time,value:mean20 + 2 * sd20});\n      bbMidSeries.update({time,value:mean20});\n      bbLowerSeries.update({time,value:mean20 - 2 * sd20});\n    }\n    if (closes.length >= 50) {\n      const tail50 = closes.slice(-50);\n      const mean50 = tail50.reduce((a,b)=>a+b,0) / 50;\n      sma50Series.update({time,value:mean50});\n    }'''
)

# ---- series creation ----
replace_once(
    'static/js/chart.js',
    '''    emaLongSeries = chart.addLineSeries({\n      color: "#00bcd4", lineWidth: 1.5, lineStyle: LightweightCharts.LineStyle.Dashed,\n      priceLineVisible: false, lastValueVisible: false,\n      crosshairMarkerVisible: false, visible: opts.ema, priceFormat: fmt,\n    });\n\n    bbUpperSeries = chart.addLineSeries({''',
    '''    emaLongSeries = chart.addLineSeries({\n      color: "#00bcd4", lineWidth: 1.5, lineStyle: LightweightCharts.LineStyle.Dashed,\n      priceLineVisible: false, lastValueVisible: false,\n      crosshairMarkerVisible: false, visible: opts.ema, priceFormat: fmt,\n    });\n\n    sma20Series = chart.addLineSeries({\n      color: "#e91e63", lineWidth: 1.5,\n      priceLineVisible: false, lastValueVisible: false,\n      crosshairMarkerVisible: false, visible: opts.sma, priceFormat: fmt,\n    });\n    sma50Series = chart.addLineSeries({\n      color: "#ffd54f", lineWidth: 1.5, lineStyle: LightweightCharts.LineStyle.Dashed,\n      priceLineVisible: false, lastValueVisible: false,\n      crosshairMarkerVisible: false, visible: opts.sma, priceFormat: fmt,\n    });\n\n    bbUpperSeries = chart.addLineSeries({'''
)

# ---- toolbar binding ----
replace_once(
    'static/js/chart.js',
    '    bindOpt("ema-toggle", "ema");\n    bindOpt("bb-toggle", "bb");',
    '    bindOpt("ema-toggle", "ema");\n    bindOpt("sma-toggle", "sma");\n    bindOpt("bb-toggle", "bb");'
)

# ---- full update: one SMA20 computation shared with BB middle ----
replace_once(
    'static/js/chart.js',
    '''    const ema100 = calcEma(closes, 100);\n    const rsiArr = calcRsi(closes, 14);''',
    '''    const ema100 = calcEma(closes, 100);\n    const sma20 = smaArr(closes, 20);\n    const sma50 = smaArr(closes, 50);\n    const rsiArr = calcRsi(closes, 14);'''
)
replace_once(
    'static/js/chart.js',
    '''    emaLongSeries.applyOptions({ visible: opts.ema });\n\n    const bb = calcBB(closes, 20, 2);\n    bbUpperSeries.setData(linePoints(bb.up));\n    bbMidSeries.setData(linePoints(bb.mid));\n    bbLowerSeries.setData(linePoints(bb.lo));\n    bbUpperSeries.applyOptions({ visible: opts.bb });\n    bbMidSeries.applyOptions({ visible: opts.bb });\n    bbLowerSeries.applyOptions({ visible: opts.bb });''',
    '''    emaLongSeries.applyOptions({ visible: opts.ema });\n\n    sma20Series.setData(linePoints(sma20));\n    sma50Series.setData(linePoints(sma50));\n    sma20Series.applyOptions({ visible: opts.sma });\n    sma50Series.applyOptions({ visible: opts.sma });\n\n    const bb = calcBB(closes, 20, 2);\n    bbUpperSeries.setData(linePoints(bb.up));\n    // BB middle === SMA20; reuse the already-computed SMA20 array.\n    bbMidSeries.setData(linePoints(sma20));\n    bbLowerSeries.setData(linePoints(bb.lo));\n    bbUpperSeries.applyOptions({ visible: opts.bb });\n    bbMidSeries.applyOptions({ visible: opts.bb });\n    bbLowerSeries.applyOptions({ visible: opts.bb });'''
)

# ---- E2E: prove SMA control works on desktop/mobile ----
replace_once(
    'e2e/chart.spec.js',
    '''  await page.locator('#macd-toggle').check();\n  await expect(page.locator('#macd-pane')).toBeVisible();''',
    '''  await expect(page.locator('#sma-toggle')).not.toBeChecked();\n  await page.locator('#sma-toggle').check();\n  await expect(page.locator('#sma-toggle')).toBeChecked();\n\n  await page.locator('#macd-toggle').check();\n  await expect(page.locator('#macd-pane')).toBeVisible();'''
)

# ---- focused regression contract ----
Path('tests_sma_indicator.py').write_text(r'''from pathlib import Path

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
''', encoding='utf-8')
