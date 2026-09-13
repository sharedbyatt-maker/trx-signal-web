from pathlib import Path

p=Path('static/js/chart.js')
s=p.read_text()

# Shared robust multi-timeframe scale helper.
anchor='''  function findPivots(bars, k = PIVOT_K) {\n    const hi = [], lo = [];\n'''
insert='''  function structureScale(bars, lookback = 180) {\n    const tail = (bars || []).slice(-lookback);\n    if (!tail.length) return 1.0;\n    const ranges = tail.map((b) => Math.max(0.1, Number(b.h) - Number(b.l)))\n      .filter((v) => Number.isFinite(v)).sort((a,b)=>a-b);\n    if (!ranges.length) return 1.0;\n    // Median is deliberately used instead of mean so one unusually long candle\n    // cannot inflate every structural threshold on higher timeframes.\n    const m = Math.floor(ranges.length / 2);\n    const med = ranges.length % 2 ? ranges[m] : (ranges[m-1] + ranges[m]) / 2;\n    return Math.max(0.75, Math.min(8.0, med));\n  }\n\n  function findPivots(bars, k = PIVOT_K) {\n    const hi = [], lo = [];\n'''
if anchor not in s: raise SystemExit('pivot anchor missing')
s=s.replace(anchor,insert,1)

# Trend thresholds.
old='''    const ps = pivs.slice(-48);\n    const lastI = bars.length - 1;\n    const touchTol = 0.8;\n    const hardBreak = 1.35;\n    let best = null;\n'''
new='''    const ps = pivs.slice(-48);\n    const lastI = bars.length - 1;\n    const scale = structureScale(bars);\n    const touchTol = Math.max(0.8, Math.min(4.8, scale * 0.8));\n    const hardBreak = Math.max(1.35, Math.min(8.0, scale * 1.35));\n    const maxAbsSlope = Math.max(0.5, Math.min(3.0, scale * 0.5));\n    let best = null;\n'''
if old not in s: raise SystemExit('trend threshold block missing')
s=s.replace(old,new,1)
s=s.replace('''        if (absSlope > 0.5) continue; // implausibly steep on the ±1 synthetic walk\n''','''        if (absSlope > maxAbsSlope) continue; // normalized to current timeframe range\n''',1)

# Pattern normalization setup.
old='''  function detectPatterns(ph, pl, bars) {\n    const marks = [];\n    const n = bars.length;\n    const from = Math.max(0, n - 450);\n'''
new='''  function detectPatterns(ph, pl, bars) {\n    const marks = [];\n    const n = bars.length;\n    const scale = structureScale(bars);\n    const patternTol = Math.max(PAT_TOL, Math.min(5.0, scale * 0.75));\n    const minSwing = Math.max(2.5, scale * 2.0);\n    const breakoutNear = Math.max(0.3, Math.min(2.5, scale * 0.25));\n    const breakoutClear = Math.max(0.4, Math.min(3.5, scale * 0.45));\n    const from = Math.max(0, n - 450);\n'''
if old not in s: raise SystemExit('pattern setup missing')
s=s.replace(old,new,1)
s=s.replace('Math.max(PAT_TOL, height * 0.18)','Math.max(patternTol, height * 0.18)',1)
s=s.replace('height >= 2.5','height >= minSwing',1)
s=s.replace('Math.max(PAT_TOL, depth * 0.18)','Math.max(patternTol, depth * 0.18)',1)
s=s.replace('depth >= 2.5','depth >= minSwing',1)
s=s.replace('const margin = Math.max(1.0, (M.v - Math.min(L.v, R.v)) * 0.25);','const margin = Math.max(scale * 0.8, (M.v - Math.min(L.v, R.v)) * 0.25);',1)
s=s.replace('Math.abs(L.v - R.v) <= PAT_TOL * 1.5','Math.abs(L.v - R.v) <= patternTol * 1.5',1)
s=s.replace('const margin = Math.max(1.0, (Math.max(L.v, R.v) - M.v) * 0.25);','const margin = Math.max(scale * 0.8, (Math.max(L.v, R.v) - M.v) * 0.25);',1)
s=s.replace('Math.abs(L.v - R.v) <= PAT_TOL * 1.5','Math.abs(L.v - R.v) <= patternTol * 1.5',1)
s=s.replace('pc <= res.v + 0.3 && c.c > res.v + 0.4','pc <= res.v + breakoutNear && c.c > res.v + breakoutClear',1)
s=s.replace('pc >= sup.v - 0.3 && c.c < sup.v - 0.4','pc >= sup.v - breakoutNear && c.c < sup.v - breakoutClear',1)

# S/R adaptive tolerance now uses the same robust scale, with a higher multi-TF ceiling.
old='''  function srAdaptiveTolerance(bars) {\n    const tail = bars.slice(-180);\n    if (!tail.length) return 1.0;\n    let rangeSum = 0;\n    tail.forEach((b) => { rangeSum += Math.max(0.1, b.h - b.l); });\n    const avgRange = rangeSum / tail.length;\n    return Math.max(0.65, Math.min(2.4, avgRange * 1.15));\n  }\n'''
new='''  function srAdaptiveTolerance(bars) {\n    const scale = structureScale(bars, 180);\n    return Math.max(0.65, Math.min(6.0, scale * 1.15));\n  }\n'''
if old not in s: raise SystemExit('sr tolerance block missing')
s=s.replace(old,new,1)
# Make de-dup spacing follow the same tolerance instead of hard-coding 2.2 as dominant on 1m.
s=s.replace('Math.max(2.2,tol*1.6)','Math.max(1.6,tol*1.6)',1)

p.write_text(s)

Path('tests_multi_tf_normalization.py').write_text(r'''from pathlib import Path
s=Path("static/js/chart.js").read_text()
for token in [
    "function structureScale(bars, lookback = 180)",
    "const scale = structureScale(bars);",
    "const touchTol = Math.max(0.8, Math.min(4.8, scale * 0.8))",
    "const hardBreak = Math.max(1.35, Math.min(8.0, scale * 1.35))",
    "const maxAbsSlope = Math.max(0.5, Math.min(3.0, scale * 0.5))",
    "const patternTol = Math.max(PAT_TOL, Math.min(5.0, scale * 0.75))",
    "const minSwing = Math.max(2.5, scale * 2.0)",
    "const breakoutNear = Math.max(0.3, Math.min(2.5, scale * 0.25))",
    "const breakoutClear = Math.max(0.4, Math.min(3.5, scale * 0.45))",
    "return Math.max(0.65, Math.min(6.0, scale * 1.15))",
]: assert token in s, token
assert "Math.abs(L.v - R.v) <= patternTol * 1.5" in s
assert "pc <= res.v + breakoutNear && c.c > res.v + breakoutClear" in s
assert "pc >= sup.v - breakoutNear && c.c < sup.v - breakoutClear" in s
for f in ["decision.py","robust_engine.py","app_core.py","drawings_persistence.py"]: assert Path(f).exists()
print("Multi-TF Normalization contract OK")
''')
