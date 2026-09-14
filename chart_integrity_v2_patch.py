from pathlib import Path
import re


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'pattern not found in {path}: {old[:180]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# --- Standard H/L/C Stochastic 14,3,3 ------------------------------------
replace_once(
    'static/js/chart.js',
    '''  function calcStoch(closes, period = 14, kSmooth = 3, dSmooth = 3) {\n    const raw = new Array(closes.length).fill(null);\n    for (let i = period - 1; i < closes.length; i++) {\n      let hh = -Infinity, ll = Infinity;\n      for (let j = i - period + 1; j <= i; j++) {\n        if (closes[j] > hh) hh = closes[j];\n        if (closes[j] < ll) ll = closes[j];\n      }\n      raw[i] = hh === ll ? 50 : ((closes[i] - ll) / (hh - ll)) * 100;\n    }\n    const k = smaArr(raw, kSmooth);\n    const d = smaArr(k, dSmooth);\n    return { k, d };\n  }\n''',
    '''  function calcStoch(bars, period = 14, kSmooth = 3, dSmooth = 3) {\n    // Standard Stochastic Oscillator: current close relative to the highest\n    // HIGH / lowest LOW over the lookback. This replaces the old close-only\n    // walk oscillator while preserving 14,3,3 smoothing.\n    const raw = new Array(bars.length).fill(null);\n    for (let i = period - 1; i < bars.length; i++) {\n      let hh = -Infinity, ll = Infinity;\n      for (let j = i - period + 1; j <= i; j++) {\n        if (bars[j].h > hh) hh = bars[j].h;\n        if (bars[j].l < ll) ll = bars[j].l;\n      }\n      const close = bars[i].c;\n      raw[i] = hh === ll ? 50 : ((close - ll) / (hh - ll)) * 100;\n    }\n    const k = smaArr(raw, kSmooth);\n    const d = smaArr(k, dSmooth);\n    return { raw, k, d };\n  }\n'''
)
replace_once('static/js/chart.js','    const st = computed?.stoch || calcStoch(closes, 14, 3, 3);','    const st = computed?.stoch || calcStoch(curBars, 14, 3, 3);')
replace_once(
    'static/js/chart.js',
    '''    const raw = new Array(closes.length).fill(null);\n    for (let i = 13; i < closes.length; i++) {\n      let hh=-Infinity,ll=Infinity;\n      for (let j=i-13;j<=i;j++){ if(closes[j]>hh)hh=closes[j]; if(closes[j]<ll)ll=closes[j]; }\n      raw[i]=hh===ll?50:((closes[i]-ll)/(hh-ll))*100;\n    }\n    liveInd.stochRaw = raw.slice(-3).filter((v)=>v!=null);\n''',
    '''    liveInd.stochRaw = (st.raw || []).slice(-3).filter((v)=>v!=null);\n'''
)
replace_once(
    'static/js/chart.js',
    '''    let raw=null,kVal=null,dVal=null;\n    if (closes.length>=14) {\n      const tail=closes.slice(-14), hh=Math.max(...tail), ll=Math.min(...tail);\n      raw=hh===ll?50:((close-ll)/(hh-ll))*100;\n''',
    '''    let raw=null,kVal=null,dVal=null;\n    if (curBars.length>=14) {\n      const tail=curBars.slice(-14);\n      const hh=Math.max(...tail.map((b)=>b.h)), ll=Math.min(...tail.map((b)=>b.l));\n      raw=hh===ll?50:((close-ll)/(hh-ll))*100;\n'''
)
replace_once('static/js/chart.js','    const stochCalc = calcStoch(closes, 14, 3, 3);','    const stochCalc = calcStoch(curBars, 14, 3, 3);')

# --- Adaptive structural lookback -----------------------------------------
replace_once(
    'static/js/chart.js',
    '  function structureScale(bars, lookback = 180) {\n',
    '''  function structuralLookbackBars(available, tfMinutes = group) {\n    const tf = Math.max(1, Number(tfMinutes) || 1);\n    // 1m: use 3 days (4,320 bars) to deepen structure context without\n    // rescanning all ~14,400 ten-day bars every authoritative refresh.\n    // 5m/15m/1h: the full 10-day buffer is small enough to analyze directly.\n    const days = tf === 1 ? 3 : 10;\n    const wanted = Math.ceil(days * 1440 / tf);\n    return Math.max(0, Math.min(Number(available) || 0, wanted));\n  }\n\n  function structureScale(bars, lookback = 180) {\n'''
)
replace_once('static/js/chart.js','    const from = Math.max(0, n - 500);','    const from = Math.max(0, n - structuralLookbackBars(n));')
replace_once('static/js/chart.js','    const lim = bars.slice(-2500);','    const lim = bars.slice(-structuralLookbackBars(bars.length));')
replace_once(
    'static/js/chart.js',
    '''    // FIX: compute fractal pivots on a tail window only — full-history scans\n    // (up to ~30k bars) made every refresh sluggish without adding signals.\n    const TAIL = Math.min(curBars.length, 1500);\n    const tailStart = curBars.length - TAIL;\n''',
    '''    // Analysis Integrity v2: adaptive structural window. 1m uses the latest\n    // 3 days; higher timeframes can safely use the full 10-day chart buffer.\n    const TAIL = structuralLookbackBars(curBars.length);\n    const tailStart = curBars.length - TAIL;\n'''
)
replace_once(
    'static/js/chart.js',
    '''    _view: () => {\n      try { const r = chart.timeScale().getVisibleLogicalRange(); return { from: r.from, to: r.to }; }\n      catch (e) { return null; }\n    },\n''',
    '''    _view: () => {\n      try { const r = chart.timeScale().getVisibleLogicalRange(); return { from: r.from, to: r.to }; }\n      catch (e) { return null; }\n    },\n    _qa: { calcStoch, structuralLookbackBars },\n'''
)

# --- Clear chart semantics in the UI --------------------------------------
replace_once(
    'templates/index.html',
    '''      <div class="card-title">CHART</div>\n      <div class="chart-toolbar">\n''',
    '''      <div class="card-title">CHART <span class="tb-group-label orange" id="chart-model-note" title="This chart is built from BIG/SMALL round outcomes, not TRX exchange price candles.">SYNTHETIC BIG/SMALL WALK · NOT TRX MARKET PRICE</span></div>\n      <div class="chart-toolbar">\n'''
)
replace_once(
    'templates/index.html',
    '<div class="tv-rsi-legend mono"><span class="lg-dim">STOCH 14·3·3</span><span id="lg-stoch"></span></div>',
    '<div class="tv-rsi-legend mono"><span class="lg-dim">STOCH H/L/C 14·3·3</span><span id="lg-stoch"></span></div>'
)
p = Path('templates/index.html')
s = p.read_text(encoding='utf-8')
s = re.sub(r"(filename='js/chart\.js'\) \}\}\?v=)\d+", r"\g<1>47", s, count=1)
p.write_text(s, encoding='utf-8')

# Browser QA: disclosure and standard Stoch label are visible in DOM.
p = Path('e2e/chart.spec.js')
s = p.read_text(encoding='utf-8')
anchor = "test('history range presets expose the full-history navigation controls', async ({ page }) => {"
idx = s.find(anchor)
if idx < 0:
    raise SystemExit('E2E anchor not found')
insert = '''test('chart clearly discloses synthetic model and HLC stochastic', async ({ page }) => {\n  await waitForChart(page);\n  await expect(page.locator('#chart-model-note')).toContainText('NOT TRX MARKET PRICE');\n  await page.locator('#ind-toggle-btn').click();\n  await page.locator('#stoch-toggle').check();\n  await expect(page.locator('#stoch-pane')).not.toHaveClass(/off/);\n  await expect(page.locator('#stoch-pane')).toContainText('STOCH H/L/C 14·3·3');\n});\n\n'''
s = s[:idx] + insert + s[idx:]
p.write_text(s, encoding='utf-8')

Path('tests_chart_integrity_v2.js').write_text(r'''global.window = {};\nglobal.document = { getElementById: () => null, querySelectorAll: () => [] };\nrequire('./static/js/chart.js');\nconst qa = window.TRXChart._qa;\nif (!qa) throw new Error('QA helpers unavailable');\n\nfunction bars(wick) {\n  const out = [];\n  for (let i = 0; i < 18; i++) {\n    const c = 10 + i;\n    out.push({time:i+1,o:c-1,h:c+wick,l:c-wick,c});\n  }\n  return out;\n}\nconst tight = qa.calcStoch(bars(1), 14, 3, 3);\nconst wide = qa.calcStoch(bars(6), 14, 3, 3);\nconst kt = tight.k.at(-1), kw = wide.k.at(-1);\nif (!(Number.isFinite(kt) && Number.isFinite(kw))) throw new Error('Stoch did not produce finite K');\nif (Math.abs(kt - kw) < 1) throw new Error('Stoch is not responding to candle high/low wicks');\nif (!Number.isFinite(wide.d.at(-1))) throw new Error('Stoch D smoothing missing');\n\nconst cases = [[20000,1,4320],[20000,5,2880],[20000,15,960],[20000,60,240],[100,1,100]];\nfor (const [avail, tf, want] of cases) {\n  const got = qa.structuralLookbackBars(avail, tf);\n  if (got !== want) throw new Error(`lookback ${tf}m expected ${want}, got ${got}`);\n}\nconsole.log('Chart Analysis Integrity v2 QA passed');\n'''.replace('\\n','\n'), encoding='utf-8')

Path('tests_chart_integrity_v2.py').write_text(r'''from pathlib import Path\n\n\ndef test_integrity_v2_contracts():\n    js = Path('static/js/chart.js').read_text(encoding='utf-8')\n    html = Path('templates/index.html').read_text(encoding='utf-8')\n    assert 'function calcStoch(bars, period = 14' in js\n    assert 'bars[j].h' in js and 'bars[j].l' in js\n    assert 'calcStoch(curBars, 14, 3, 3)' in js\n    assert 'structuralLookbackBars(curBars.length)' in js\n    assert 'const days = tf === 1 ? 3 : 10;' in js\n    assert 'bars.slice(-structuralLookbackBars(bars.length))' in js\n    assert 'n - structuralLookbackBars(n)' in js\n    assert 'NOT TRX MARKET PRICE' in html\n    assert 'STOCH H/L/C 14·3·3' in html\n'''.replace('\\n','\n'), encoding='utf-8')
