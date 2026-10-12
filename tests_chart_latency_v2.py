from pathlib import Path

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
assert 'LATEST_POLL_HIDDEN_MS = 5000' in appjs
assert 'scheduleLatestPoll(0)' in appjs
assert 'setInterval(pollLatest, 400)' not in appjs

assert 'shiftVisibleRangeOnNewBar: true' in chart
assert 'bbUpperSeries.update({time,value:mean20 + 2 * sd20})' in chart
assert 'bbMidSeries.update({time,value:mean20})' in chart
assert 'bbLowerSeries.update({time,value:mean20 - 2 * sd20})' in chart
print('chart latency v2 checks passed')
