from pathlib import Path
s=Path("static/js/chart.js").read_text()
for x in [
 "let liveInd = null","function seedLiveIndicators(closes)","function updateLiveIndicators(close, time)",
 "function emaNext(prev, value, period, countBefore, closes)","emaFastSeries.update({time,value:liveInd.ema5})",
 "rsiSeries.update({time,value:rsiVal})","macdLineSeries.update({time,value:macdVal})",
 "macdSigSeries.update({time,value:sigVal})","macdHistSeries.update({time,value:histVal",
 "stochKSeries.update({time,value:kVal})","stochDSeries.update({time,value:dVal})",
 "updateLiveIndicators(close, time)","seedLiveIndicators(closes);"
]: assert x in s, x
assert "The normal /api/state refresh remains the authoritative full reconciliation" in s
for f in ["decision.py","robust_engine.py","app_core.py"]: assert Path(f).exists()
print("Fast Live Indicator Update contract OK")
