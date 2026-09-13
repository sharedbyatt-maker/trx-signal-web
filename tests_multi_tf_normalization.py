from pathlib import Path
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
compact=''.join(s.split())
# H&S shoulder tolerance remains scale-aware under Pattern Engine v2.
assert 'constshoulderTol=Math.max(patternTol,scale*.9)' in compact
assert 'Math.abs(L.v-R.v)>shoulderTol*1.6' in compact
# Breakout thresholds still use normalized near/clear values.
assert 'pc<=res.v+breakoutNear&&c.c>res.v+breakoutClear' in compact
assert 'pc>=sup.v-breakoutNear&&c.c<sup.v-breakoutClear' in compact
for f in ["decision.py","robust_engine.py","app_core.py","drawings_persistence.py"]: assert Path(f).exists()
print("Multi-TF Normalization contract OK")
