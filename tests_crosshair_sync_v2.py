from pathlib import Path
s=Path("static/js/chart.js").read_text()
for x in [
    "let crosshairLock = false",
    "function updateAllLegendsAtTime(time)",
    "function restoreLatestLegends()",
    "function paneCrosshairTargets()",
    "function syncCrosshairs()",
    "setCrosshairPosition(v, time, dst.series)",
    "clearCrosshairPosition",
    "syncCrosshairs();",
    "curRsiValues = rsiArr.slice()",
    "curMacdValues = m.macd.slice()",
    "curStochValues = st.k.slice()",
]: assert x in s, x
assert s.count("subscribeCrosshairMove") == 1, s.count("subscribeCrosshairMove")
for f in ["decision.py","robust_engine.py","app_core.py"]: assert Path(f).exists()
print("Crosshair & Pane Sync v2 contract OK")
