from pathlib import Path

def rep(path, old, new):
    p=Path(path); s=p.read_text(encoding='utf-8')
    if old not in s: raise SystemExit(f'not found in {path}: {old[:100]}')
    p.write_text(s.replace(old,new,1), encoding='utf-8')

# Clean default overlays: Trend + Patterns join S/R + SIG as opt-in.
rep('static/js/chart.js', 'pat: true, sr: false, tl: true, macd: false, stoch: false,', 'pat: false, sr: false, tl: false, macd: false, stoch: false,')
rep('templates/index.html', '<input type="checkbox" id="tl-toggle" checked> Trend', '<input type="checkbox" id="tl-toggle"> Trend')
rep('templates/index.html', '<input type="checkbox" id="pat-toggle" checked> Patterns', '<input type="checkbox" id="pat-toggle"> Patterns')

# 10D remains selected/data-loaded, but initial screen stays readable instead of compressing 14,400 1m bars.
rep('static/js/chart.js', 'function anchorRecent() {\n    // Default analytical view: full loaded 10-day history.\n    setHistoryRange(10);\n  }', '''function anchorRecent() {
    // RANGE 10D is the selected/data-loaded range, but do not crush ~14,400 1m
    // bars into the first screen. Start with a readable recent window; 10D remains
    // available via the selected RANGE button / FIT.
    const n = curBars.length;
    if (!n) return;
    const visible = group === 1 ? 320 : group === 5 ? 288 : group === 15 ? 192 : 120;
    const range = { from: Math.max(1, n - visible + 1), to: n + 4 };
    [chart, rsiChart, macdChart, stochChart].forEach((c) => {
      if (!c) return;
      try { c.timeScale().setVisibleLogicalRange(range); } catch (e) { /* noop */ }
    });
  }''')

# Multi-TF fast live: append the fresh 1m outcome into the current real-time bucket.
old='''  function appendLatest(row) {
    if (!chart || group !== 1 || !row || !row.issue || !curBars.length) return false;
    const issue = String(row.issue);
    if (curLabelMap instanceof Map && curLabelMap.has(issue)) return true;

    const dir = row.type === "BIG" ? 1 : -1;
    const open = curBars[curBars.length - 1].c;
    const close = open + dir;
    const time = curBars.length + 1;
    const raw = { time, open, high: Math.max(open, close), low: Math.min(open, close), close };

    try {
      candleSeries.update(raw);
      areaSeries.update({ time, value: close });
    } catch (e) {
      return false;
    }

    curBars.push({ time, o: open, h: raw.high, l: raw.low, c: close });
    curCloses.push(close);
    curLabels.push(row.short_issue || issue.slice(-6));
    curTimes.push(row.block_time || row.hm || "");
    curFulls.push(issue);
    if (!(curLabelMap instanceof Map)) curLabelMap = new Map();
    curLabelMap.set(issue, time);
    lastLen = curBars.length;
    try { updateLiveIndicators(close, time); } catch (e) { /* full state refresh will reconcile */ }
    updateLegend(curBars[curBars.length - 1]);
'''
new='''  function appendLatest(row) {
    if (!chart || !row || !row.issue || !curBars.length) return false;
    const issue = String(row.issue);
    if (curLabelMap instanceof Map && curLabelMap.has(issue)) return true;

    const dir = row.type === "BIG" ? 1 : -1;
    const last = curBars[curBars.length - 1];
    const close = last.c + dir;
    let time = last.time;
    let isNewBar = group === 1;

    // Higher TFs use the same source block-time bucket rule as full aggregation.
    // If parsing is unavailable, return false so authoritative /api/state renders it.
    if (group > 1) {
      const bt = String(row.block_time || row.blockTime || "");
      const prevBt = String(curTimes[curTimes.length - 1] || "");
      const parseMinute = (s) => {
        const m = s.match(/(?:^|\\s)(\\d{1,2}):(\\d{2})(?::\\d{2})?$/);
        return m ? Number(m[1]) * 60 + Number(m[2]) : null;
      };
      const curMin = parseMinute(bt), prevMin = parseMinute(prevBt);
      if (curMin == null || prevMin == null) return false;
      isNewBar = Math.floor(curMin / group) !== Math.floor(prevMin / group) || bt.slice(0,10) !== prevBt.slice(0,10);
    }

    let raw;
    if (isNewBar) {
      time = curBars.length + 1;
      const open = last.c;
      raw = { time, open, high: Math.max(open, close), low: Math.min(open, close), close };
    } else {
      raw = { time, open: last.o, high: Math.max(last.h, close), low: Math.min(last.l, close), close };
    }

    try {
      candleSeries.update(raw);
      areaSeries.update({ time, value: close });
    } catch (e) { return false; }

    if (isNewBar) {
      curBars.push({ time, o: raw.open, h: raw.high, l: raw.low, c: close });
      curCloses.push(close);
      curLabels.push(row.short_issue || issue.slice(-6));
      curTimes.push(row.block_time || row.hm || "");
      curFulls.push(issue);
    } else {
      curBars[curBars.length - 1] = { time, o: raw.open, h: raw.high, l: raw.low, c: close };
      curCloses[curCloses.length - 1] = close;
      curLabels[curLabels.length - 1] = row.short_issue || issue.slice(-6);
      curTimes[curTimes.length - 1] = row.block_time || row.hm || curTimes[curTimes.length - 1];
      curFulls[curFulls.length - 1] = issue;
    }
    if (!(curLabelMap instanceof Map)) curLabelMap = new Map();
    curLabelMap.set(issue, time);
    lastLen = curBars.length;
    // Incremental indicator state is exact for a newly closed 1m bar. Higher-TF
    // in-progress bars are reconciled by the normal /api/state refresh.
    if (group === 1) {
      try { updateLiveIndicators(close, time); } catch (e) { /* full state refresh will reconcile */ }
    }
    updateLegend(curBars[curBars.length - 1]);
'''
rep('static/js/chart.js', old, new)

# Restore compact UI sizing explicitly so later imported CSS cannot inflate the terminal.
p=Path('static/css/style.css'); s=p.read_text(encoding='utf-8')
s += '''\n/* Compact terminal typography guard — preserve the original dense desktop scale. */
html { font-size: 16px; }
body { font-size: 12px; }
button, input, select, textarea { font: inherit; }
.tf-btn { font-size: 10px; }
.chart-toggle { font-size: 10px; }
@media (max-width: 600px) {
  body { font-size: 11px; }
  .tf-btn { font-size: 10px; }
}\n'''
p.write_text(s,encoding='utf-8')

# Cache-bust CSS/JS so deployed browsers don't mix old/new assets.
rep('templates/index.html', "filename='css/style.css') }}?v=43", "filename='css/style.css') }}?v=44")
rep('templates/index.html', "filename='js/chart.js') }}?v=48", "filename='js/chart.js') }}?v=49")

Path('tests_chart_ui_live_v2.py').write_text(r'''from pathlib import Path

def test_clean_overlay_defaults_and_readable_10d_start():
    html=Path('templates/index.html').read_text(encoding='utf-8')
    js=Path('static/js/chart.js').read_text(encoding='utf-8')
    assert 'id="tl-toggle">' in html and 'id="tl-toggle" checked' not in html
    assert 'id="pat-toggle"' in html and 'id="pat-toggle" checked' not in html
    assert 'pat: false, sr: false, tl: false' in js
    assert 'group === 1 ? 320' in js
    assert 'setHistoryRange(days = 10)' in js

def test_multi_tf_fast_append_and_compact_font_guard():
    js=Path('static/js/chart.js').read_text(encoding='utf-8')
    css=Path('static/css/style.css').read_text(encoding='utf-8')
    assert 'group !== 1' not in js[js.index('function appendLatest'):js.index('function toggleSignals')]
    assert 'Math.floor(curMin / group)' in js
    assert 'curBars[curBars.length - 1] =' in js
    assert 'body { font-size: 12px; }' in css
    assert '.tf-btn { font-size: 10px; }' in css
''',encoding='utf-8')
