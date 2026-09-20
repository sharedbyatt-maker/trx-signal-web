from pathlib import Path
s=Path("static/js/chart.js").read_text()
for x in ["srAdaptiveTolerance","srLevelStats","rejections","retests","flipped","STRONG","MEDIUM","FLIP","role=L<close"]: assert x in s, x
for f in ["decision.py","l1_capital.py","app_core.py"]: assert Path(f).exists()
print("Auto S/R v2 contract OK")
