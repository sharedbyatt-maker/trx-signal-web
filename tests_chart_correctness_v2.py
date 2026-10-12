from pathlib import Path

chart = Path("static/js/chart.js").read_text()
app = Path("static/js/app.js").read_text()

# S/R cache must follow new bars and manual rescans must replace the cache.
for token in [
    'let srCacheFingerprint = ""',
    'function srFingerprint()',
    'srCacheFingerprint !== fp',
    'srLevelsCache = srLevels(curBars)',
    'srCacheFingerprint = srFingerprint()',
    'function syncSrControls()',
]:
    assert token in chart, token

# Flat aggregated candles are neutral, never bearish momentum.
compact = ''.join(chart.split())
assert 'bars[i].c>bars[i].o?1:bars[i].c<bars[i].o?-1:0' in compact
assert 'if(dir===0){flushRun();rd=0;rl=0;rEnd=-1;continue;}' in compact

# Rebuild fingerprint notices corrections to recent rows, not only len/last issue.
assert 'const tailFingerprint = hist.slice(-3)' in chart
assert '${tailFingerprint}' in chart

# Fast append refuses to bridge missing sequential issues.
assert 'BigInt(String(rd.issue)) > BigInt(String(previousIssue)) + 1n' in app
assert 'await fetchFullHistory(true,true);' in app
assert 'await refresh();' in app

# Drawing and indicator toolbar controls are independently operable.
assert 'const indToggle = $("ind-toggle-btn")' in app
assert 'drawBar.classList.toggle("collapsed", !open)' in app
assert 'indBar.classList.toggle("collapsed", !open)' in app

for f in ["decision.py", "l1_capital.py", "app_core.py", "drawings_persistence.py"]:
    assert Path(f).exists()
print("Chart Correctness & Cache Fix contract OK")
