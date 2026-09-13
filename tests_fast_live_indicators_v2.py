from pathlib import Path
s=Path("static/js/chart.js").read_text()
for x in [
 "let liveInd = null","function updateLiveIndicators(close, time)",
 "function emaNext(prev, value, period, countBefore, closes)","emaFastSeries.update({time,value:liveInd.ema5})",
 "rsiSeries.update({time,value:rsiVal})","macdLineSeries.update({time,value:macdVal})",
 "macdSigSeries.update({time,value:sigVal})","macdHistSeries.update({time,value:histVal",
 "stochKSeries.update({time,value:kVal})","stochDSeries.update({time,value:dVal})",
 "updateLiveIndicators(close, time)"
]: assert x in s, x
# Phase 7 behavior remains; Phase 11 may pass precomputed full-refresh arrays into the seed.
assert ("function seedLiveIndicators(closes)" in s or
        "function seedLiveIndicators(closes, computed = null)" in s)
assert ("seedLiveIndicators(closes);" in s or
        "seedLiveIndicators(closes, { ema5, ema15, ema100, rsi: rsiArr, macd: macdCalc, stoch: stochCalc });" in s)
assert "The normal /api/state refresh remains the authoritative full reconciliation" in s
for f in ["decision.py","robust_engine.py","app_core.py"]: assert Path(f).exists()
print("Fast Live Indicator Update contract OK")
