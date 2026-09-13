from pathlib import Path
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
