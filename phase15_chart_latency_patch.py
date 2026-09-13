from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'pattern not found in {path}: {old[:120]!r}')
    s = s.replace(old, new, 1)
    p.write_text(s, encoding='utf-8')

# Backend: fixed poll cadence instead of request+processing+POLL_SEC.
replace_once(
    'app_core.py',
    '    while True:\n        try:\n            url = URL_DATA if not have_full else URL_DATA + f"?limit={TAIL_LIMIT}"',
    '    while True:\n        poll_started = time.monotonic()\n        try:\n            url = URL_DATA if not have_full else URL_DATA + f"?limit={TAIL_LIMIT}"'
)

# Backend: only rebuild 30k staking walk/RSI when a genuinely new issue arrives.
old = '''                    # ---- staking-engine series (walk + RSI, chronological) ----\n                    types_strat = [x["type"] for x in parsed_history]\n                    c_s = 100\n                    closes_s = []\n                    for x in parsed_history:\n                        c_s += 1 if x["type"] == "BIG" else -1\n                        closes_s.append(c_s)\n                    arr_strat = rsi_series(closes_s, RSI_STRAT_PERIOD)\n\n                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n                    latest = parsed_history[-1]\n                    if latest["issue"] != last_issue:\n                        current_strat_day = _strat_day_from_issue(latest["issue"])'''
new = '''                    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")\n                    latest = parsed_history[-1]\n                    if latest["issue"] != last_issue:\n                        # Build the staking walk/RSI only for a fresh completed round.\n                        # Recomputing up to 30k points on every 0.5s no-change poll\n                        # adds CPU time directly to feed-detection latency.\n                        types_strat = [x["type"] for x in parsed_history]\n                        c_s = 100\n                        closes_s = []\n                        for x in parsed_history:\n                            c_s += 1 if x["type"] == "BIG" else -1\n                            closes_s.append(c_s)\n                        arr_strat = rsi_series(closes_s, RSI_STRAT_PERIOD)\n\n                        current_strat_day = _strat_day_from_issue(latest["issue"])'''
replace_once('app_core.py', old, new)

replace_once(
    'app_core.py',
    '        time.sleep(POLL_SEC)\n\n\n@app.route("/")',
    '        # Keep poll *start-to-start* cadence close to POLL_SEC. Previously we\n        # slept POLL_SEC after network/parse/CPU work, so a nominal 0.5s poll\n        # could become 0.7-1.0s. A small floor prevents hot-looping on slow/error paths.\n        elapsed = time.monotonic() - poll_started\n        time.sleep(max(0.05, POLL_SEC - elapsed))\n\n\n@app.route("/")'
)
replace_once(
    'app_core.py',
    '    """Micro-endpoint (few hundred bytes) — frontend polls this every ~1.2s\n       so new candles appear almost instantly without heavy /api/state."""',
    '    """Micro-endpoint (few hundred bytes) — visible tabs poll adaptively at ~250ms\n       so new candles appear quickly without waiting for heavy /api/state."""'
)

# Frontend: adaptive fast polling without hammering hidden/background tabs.
replace_once(
    'static/js/app.js',
    'let latestPolling = false;\nasync function pollLatest() {',
    'let latestPolling = false;\nlet latestPollTimer = 0;\nconst LATEST_POLL_VISIBLE_MS = 250;\nconst LATEST_POLL_HIDDEN_MS = 1200;\nfunction scheduleLatestPoll(delay) {\n  clearTimeout(latestPollTimer);\n  const ms = delay != null ? delay : (document.hidden ? LATEST_POLL_HIDDEN_MS : LATEST_POLL_VISIBLE_MS);\n  latestPollTimer = setTimeout(pollLatest, ms);\n}\nasync function pollLatest() {'
)
replace_once(
    'static/js/app.js',
    '  finally { latestPolling = false; }\n}\nsetInterval(pollLatest, 400);',
    '  finally {\n    latestPolling = false;\n    scheduleLatestPoll();\n  }\n}\ndocument.addEventListener("visibilitychange", () => scheduleLatestPoll(0));\nscheduleLatestPoll(0);'
)

# Chart: when user is at live edge, allow Lightweight Charts to follow the new bar.
replace_once(
    'static/js/chart.js',
    '        shiftVisibleRangeOnNewBar: false,',
    '        shiftVisibleRangeOnNewBar: true,'
)

# Fast-path BB20 update: candle and BB no longer disagree until the next full state refresh.
needle = '''    if (liveInd.ema100 != null) emaLongSeries.update({time,value:liveInd.ema100});\n\n    let rsiVal=null;'''
replacement = '''    if (liveInd.ema100 != null) emaLongSeries.update({time,value:liveInd.ema100});\n\n    // Bollinger Bands use SMA20 ± 2σ. Keep them in the same instant path as\n    // the candle; O(20) work is tiny and avoids up to ~1.5s visual lag.\n    if (closes.length >= 20) {\n      const tail20 = closes.slice(-20);\n      const mean20 = tail20.reduce((a,b)=>a+b,0) / 20;\n      let var20 = 0;\n      for (const v of tail20) var20 += (v - mean20) ** 2;\n      const sd20 = Math.sqrt(var20 / 20);\n      bbUpperSeries.update({time,value:mean20 + 2 * sd20});\n      bbMidSeries.update({time,value:mean20});\n      bbLowerSeries.update({time,value:mean20 - 2 * sd20});\n    }\n\n    let rsiVal=null;'''
replace_once('static/js/chart.js', needle, replacement)

# Focused regression/source-contract test.
Path('tests_chart_latency_v2.py').write_text(r'''from pathlib import Path

core = Path('app_core.py').read_text(encoding='utf-8')
appjs = Path('static/js/app.js').read_text(encoding='utf-8')
chart = Path('static/js/chart.js').read_text(encoding='utf-8')

assert 'poll_started = time.monotonic()' in core
assert 'elapsed = time.monotonic() - poll_started' in core
assert 'time.sleep(max(0.05, POLL_SEC - elapsed))' in core

fresh_pos = core.index('if latest["issue"] != last_issue:')
staking_pos = core.index('types_strat = [x["type"] for x in parsed_history]', fresh_pos)
assert staking_pos > fresh_pos

assert 'LATEST_POLL_VISIBLE_MS = 250' in appjs
assert 'LATEST_POLL_HIDDEN_MS = 1200' in appjs
assert 'scheduleLatestPoll(0)' in appjs
assert 'setInterval(pollLatest, 400)' not in appjs

assert 'shiftVisibleRangeOnNewBar: true' in chart
assert 'bbUpperSeries.update({time,value:mean20 + 2 * sd20})' in chart
assert 'bbMidSeries.update({time,value:mean20})' in chart
assert 'bbLowerSeries.update({time,value:mean20 - 2 * sd20})' in chart
print('chart latency v2 checks passed')
''', encoding='utf-8')
