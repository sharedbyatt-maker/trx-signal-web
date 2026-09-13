from pathlib import Path

p=Path('static/js/chart.js')
s=p.read_text()

old='''  let curBars = [];           // [{time,o,h,l,c}]\n  let curLabels = [];\n'''
new='''  let curBars = [];           // [{time,o,h,l,c}]\n  let curCloses = [];         // hot-path close cache; kept in lockstep with curBars\n  let curLabels = [];\n'''
if old not in s: raise SystemExit('curBars anchor missing')
s=s.replace(old,new,1)

old='''    const hist = macd.map((v, i) => (v == null || signal[i] == null) ? null : v - signal[i]);\n    return { macd, signal, hist };\n  }\n'''
new='''    const hist = macd.map((v, i) => (v == null || signal[i] == null) ? null : v - signal[i]);\n    return { macd, signal, hist, emaFast: ef, emaSlow: es };\n  }\n'''
if old not in s: raise SystemExit('calcMacd return block missing')
s=s.replace(old,new,1)

old='''  function seedLiveIndicators(closes) {\n    if (!closes.length) { liveInd = null; return; }\n    const ema5 = calcEma(closes, 5), ema15 = calcEma(closes, 15), ema100 = calcEma(closes, 100);\n    const rsi = calcRsi(closes, 14);\n    const macd = calcMacd(closes, 12, 26, 9);\n    const st = calcStoch(closes, 14, 3, 3);\n'''
new='''  function seedLiveIndicators(closes, computed = null) {\n    if (!closes.length) { liveInd = null; return; }\n    const ema5 = computed?.ema5 || calcEma(closes, 5);\n    const ema15 = computed?.ema15 || calcEma(closes, 15);\n    const ema100 = computed?.ema100 || calcEma(closes, 100);\n    const rsi = computed?.rsi || calcRsi(closes, 14);\n    const macd = computed?.macd || calcMacd(closes, 12, 26, 9);\n    const st = computed?.stoch || calcStoch(closes, 14, 3, 3);\n'''
if old not in s: raise SystemExit('seedLiveIndicators header missing')
s=s.replace(old,new,1)

old='''      ema5: ema5.at(-1), ema15: ema15.at(-1), ema100: ema100.at(-1),\n      ema12: calcEma(closes, 12).at(-1), ema26: calcEma(closes, 26).at(-1),\n'''
new='''      ema5: ema5.at(-1), ema15: ema15.at(-1), ema100: ema100.at(-1),\n      ema12: macd.emaFast.at(-1), ema26: macd.emaSlow.at(-1),\n'''
if old not in s: raise SystemExit('live EMA seed missing')
s=s.replace(old,new,1)

old='''  function updateLiveIndicators(close, time) {\n    if (!liveInd || group !== 1) return false;\n    const closes = curBars.map((b)=>b.c);\n    const before = liveInd.count;\n'''
new='''  function updateLiveIndicators(close, time) {\n    if (!liveInd || group !== 1) return false;\n    const closes = curCloses;\n    const before = liveInd.count;\n'''
if old not in s: raise SystemExit('updateLiveIndicators map missing')
s=s.replace(old,new,1)

old='''  function paneCrosshairTargets() {\n    return [\n      { chart, series: candleSeries, values: curBars.map((b) => b.c), enabled: true },\n      { chart: rsiChart, series: rsiSeries, values: curRsiValues, enabled: opts.rsi },\n'''
new='''  function paneCrosshairTargets() {\n    return [\n      { chart, series: candleSeries, values: curCloses, enabled: true },\n      { chart: rsiChart, series: rsiSeries, values: curRsiValues, enabled: opts.rsi },\n'''
if old not in s: raise SystemExit('crosshair map missing')
s=s.replace(old,new,1)

old='''  function syncRanges() {\n    // N-way visible-range sync (main <-> rsi <-> macd <-> stoch), feedback-guarded\n    const charts = [chart, rsiChart, macdChart, stochChart].filter(Boolean);\n'''
new='''  let drawRedrawRaf = 0;\n  function scheduleDrawRedraw() {\n    if (drawRedrawRaf || !window.TRXDraw || !window.TRXDraw.redraw) return;\n    drawRedrawRaf = requestAnimationFrame(() => {\n      drawRedrawRaf = 0;\n      try { window.TRXDraw.redraw(); } catch (e) { /* noop */ }\n    });\n  }\n\n  function syncRanges() {\n    // N-way visible-range sync (main <-> rsi <-> macd <-> stoch), feedback-guarded\n    const charts = [chart, rsiChart, macdChart, stochChart].filter(Boolean);\n'''
if old not in s: raise SystemExit('syncRanges anchor missing')
s=s.replace(old,new,1)
s=s.replace('''        if (window.TRXDraw && window.TRXDraw.redraw) window.TRXDraw.redraw();\n''','''        scheduleDrawRedraw();\n''',1)

old='''    new ResizeObserver(() => {\n      if (!chart || !containerEl) return;\n      chart.applyOptions({ width: containerEl.clientWidth, height: containerEl.clientHeight });\n      if (rsiChart && rsiEl) rsiChart.applyOptions({ width: rsiEl.clientWidth, height: rsiEl.clientHeight });\n      if (macdChart && macdEl) macdChart.applyOptions({ width: macdEl.clientWidth, height: macdEl.clientHeight });\n      if (stochChart && stochEl) stochChart.applyOptions({ width: stochEl.clientWidth, height: stochEl.clientHeight });\n    }).observe(container);\n'''
new='''    let resizeRaf = 0;\n    new ResizeObserver(() => {\n      if (resizeRaf) return;\n      resizeRaf = requestAnimationFrame(() => {\n        resizeRaf = 0;\n        if (!chart || !containerEl) return;\n        chart.applyOptions({ width: containerEl.clientWidth, height: containerEl.clientHeight });\n        if (rsiChart && rsiEl) rsiChart.applyOptions({ width: rsiEl.clientWidth, height: rsiEl.clientHeight });\n        if (macdChart && macdEl) macdChart.applyOptions({ width: macdEl.clientWidth, height: macdEl.clientHeight });\n        if (stochChart && stochEl) stochChart.applyOptions({ width: stochEl.clientWidth, height: stochEl.clientHeight });\n      });\n    }).observe(container);\n'''
if old not in s: raise SystemExit('ResizeObserver block missing')
s=s.replace(old,new,1)

old='''    curBars = bars.map((b) => ({ time: b.time, o: b.open, h: b.high, l: b.low, c: b.close }));\n    curLabels = labels;\n'''
new='''    curBars = bars.map((b) => ({ time: b.time, o: b.open, h: b.high, l: b.low, c: b.close }));\n    curCloses = curBars.map((b) => b.c);\n    curLabels = labels;\n'''
if old not in s: raise SystemExit('curBars assignment missing')
s=s.replace(old,new,1)

old='''    areaSeries.setData(linePoints(curBars.map((b) => b.c)));\n    areaSeries.applyOptions({ visible: viewMode === "line" });\n\n    const closes = curBars.map((b) => b.c);\n    seedLiveIndicators(closes);\n\n    const emaFpts = linePoints(calcEma(closes, 5));\n    const emaSpts = linePoints(calcEma(closes, 15));\n    emaFastSeries.setData(emaFpts);\n    emaSlowSeries.setData(emaSpts);\n    emaLongSeries.setData(linePoints(calcEma(closes, 100)));\n'''
new='''    areaSeries.setData(linePoints(curCloses));\n    areaSeries.applyOptions({ visible: viewMode === "line" });\n\n    const closes = curCloses;\n    const ema5 = calcEma(closes, 5);\n    const ema15 = calcEma(closes, 15);\n    const ema100 = calcEma(closes, 100);\n    const rsiArr = calcRsi(closes, 14);\n    const macdCalc = calcMacd(closes, 12, 26, 9);\n    const stochCalc = calcStoch(closes, 14, 3, 3);\n    seedLiveIndicators(closes, { ema5, ema15, ema100, rsi: rsiArr, macd: macdCalc, stoch: stochCalc });\n\n    emaFastSeries.setData(linePoints(ema5));\n    emaSlowSeries.setData(linePoints(ema15));\n    emaLongSeries.setData(linePoints(ema100));\n'''
if old not in s: raise SystemExit('full refresh indicator header missing')
s=s.replace(old,new,1)

old='''    if (rsiSeries) {\n      const rsiArr = calcRsi(closes, 14);\n      curRsiValues = rsiArr.slice();\n'''
new='''    if (rsiSeries) {\n      curRsiValues = rsiArr.slice();\n'''
if old not in s: raise SystemExit('RSI duplicate calc missing')
s=s.replace(old,new,1)

old='''    if (macdLineSeries) {\n      const m = calcMacd(closes, 12, 26, 9);\n      curMacdValues = m.macd.slice();\n'''
new='''    if (macdLineSeries) {\n      const m = macdCalc;\n      curMacdValues = m.macd.slice();\n'''
if old not in s: raise SystemExit('MACD duplicate calc missing')
s=s.replace(old,new,1)

old='''    if (stochKSeries) {\n      const st = calcStoch(closes, 14, 3, 3);\n      curStochValues = st.k.slice();\n'''
new='''    if (stochKSeries) {\n      const st = stochCalc;\n      curStochValues = st.k.slice();\n'''
if old not in s: raise SystemExit('Stoch duplicate calc missing')
s=s.replace(old,new,1)

old='''        const diff = calcEma(closes, 5).at(-1) - calcEma(closes, 15).at(-1);\n'''
new='''        const diff = (ema5.at(-1) ?? 0) - (ema15.at(-1) ?? 0);\n'''
if old not in s: raise SystemExit('legend EMA duplicate calc missing')
s=s.replace(old,new,1)

old='''    curBars.push({ time, o: open, h: raw.high, l: raw.low, c: close });\n    curLabels.push(row.short_issue || issue.slice(-6));\n'''
new='''    curBars.push({ time, o: open, h: raw.high, l: raw.low, c: close });\n    curCloses.push(close);\n    curLabels.push(row.short_issue || issue.slice(-6));\n'''
if old not in s: raise SystemExit('append curBars push missing')
s=s.replace(old,new,1)

p.write_text(s)

Path('tests_chart_performance_v2.py').write_text(r'''from pathlib import Path
s=Path("static/js/chart.js").read_text()
for token in [
    "let curCloses = []",
    "values: curCloses",
    "const closes = curCloses;",
    "curCloses.push(close)",
    "function seedLiveIndicators(closes, computed = null)",
    "ema12: macd.emaFast.at(-1)",
    "const macdCalc = calcMacd(closes, 12, 26, 9)",
    "const stochCalc = calcStoch(closes, 14, 3, 3)",
    "seedLiveIndicators(closes, { ema5, ema15, ema100, rsi: rsiArr, macd: macdCalc, stoch: stochCalc })",
    "function scheduleDrawRedraw()",
    "let resizeRaf = 0",
]: assert token in s, token
assert "values: curBars.map((b) => b.c)" not in s
assert "const closes = curBars.map((b)=>b.c);" not in s
assert "const diff = calcEma(closes, 5).at(-1) - calcEma(closes, 15).at(-1);" not in s
for f in ["decision.py","robust_engine.py","app_core.py","drawings_persistence.py"]: assert Path(f).exists()
print("Chart Performance v2 contract OK")
''')
