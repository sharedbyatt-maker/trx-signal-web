from pathlib import Path

s = Path("static/js/chart.js").read_text()
assert "function trendSegV2(pivs, bars, kind)" in s
assert "pivotProminence" in s
assert "const ps = pivs.slice(-48)" in s
assert "touches >= 3" in s
assert "retests * 6" in s
assert "violations > allowedViolations" in s
# Phase 3 behavior remains, while Phase 10 may normalize fixed thresholds by timeframe.
assert "hardBreak" in s
assert ("hardBreak = 1.35" in s or "scale * 1.35" in s)
assert ("absSlope > 0.5" in s or "absSlope > maxAbsSlope" in s)
assert 'trendSegV2(piv.hi, curBars, "res")' in s
assert 'trendSegV2(piv.lo, curBars, "sup")' in s
for f in ["decision.py", "l1_capital.py", "app_core.py"]:
    assert Path(f).exists()
print("Auto Trend Line v2 contract OK")
