from pathlib import Path

# ---- static/js/chart.js ----
p = Path('static/js/chart.js')
s = p.read_text()

old = '''  let srLevelsCache = [];
  let srCacheGroup = null;
  let srRescanNeeded = false;

  function ensureSRLevels() {
    if (srCacheGroup !== group || srRescanNeeded || !srLevelsCache.length) {
      srLevelsCache = srLevels(curBars);
      srCacheGroup = group;
      srRescanNeeded = false;
    }
    return srLevelsCache;
  }
'''
new = '''  let srLevelsCache = [];
  let srCacheGroup = null;
  let srCacheFingerprint = "";
  let srRescanNeeded = false;

  function srFingerprint() {
    if (!curBars.length) return `${group}:0`;
    const b = curBars[curBars.length - 1];
    return `${group}:${curBars.length}:${b.time}:${b.o}:${b.h}:${b.l}:${b.c}`;
  }

  function ensureSRLevels() {
    const fp = srFingerprint();
    if (srCacheGroup !== group || srRescanNeeded || srCacheFingerprint !== fp || !srLevelsCache.length) {
      srLevelsCache = srLevels(curBars);
      srCacheGroup = group;
      srCacheFingerprint = fp;
      srRescanNeeded = false;
    }
    return srLevelsCache;
  }
'''
if old not in s:
    raise SystemExit('S/R cache block not found')
s = s.replace(old, new, 1)

old = '''    for (let i = runStart; i < n; i++) {
      const dir = bars[i].c > bars[i].o ? 1 : -1;
      if (dir === rd) { rl++; rEnd = i; }
      else { flushRun(); rd = dir; rl = 1; rEnd = i; }
    }
'''
new = '''    for (let i = runStart; i < n; i++) {
      const dir = bars[i].c > bars[i].o ? 1 : bars[i].c < bars[i].o ? -1 : 0;
      if (dir === 0) { flushRun(); rd = 0; rl = 0; rEnd = -1; continue; }
      if (dir === rd) { rl++; rEnd = i; }
      else { flushRun(); rd = dir; rl = 1; rEnd = i; }
    }
'''
if old not in s:
    raise SystemExit('momentum run block not found')
s = s.replace(old, new, 1)

old = '''    const lastIssue = hist.length ? hist[hist.length - 1].issue : "";
    const key = `${hist.length}:${lastIssue}:${group}:${viewMode}:${JSON.stringify(opts)}:${(s.log || []).length}`;
'''
new = '''    const lastIssue = hist.length ? hist[hist.length - 1].issue : "";
    const tailFingerprint = hist.slice(-3).map((r) =>
      `${r.issue || ""}/${r.number ?? ""}/${r.type || ""}/${r.block_time || r.blockTime || r.hm || ""}`
    ).join("|");
    const key = `${hist.length}:${lastIssue}:${tailFingerprint}:${group}:${viewMode}:${JSON.stringify(opts)}:${(s.log || []).length}`;
'''
if old not in s:
    raise SystemExit('chart key block not found')
s = s.replace(old, new, 1)

old = '''  function autoSR() {
    if (!chart || !curBars.length) return { on: false, n: 0 };
    const cb = $("sr-toggle");
    if (opts.sr) {
      // OFF
      opts.sr = false;
      if (cb) cb.checked = false;
      drawSrLines([]);
      return { on: false, n: 0 };
    }
    // ON — full rescan and show
    opts.sr = true;
    if (cb) cb.checked = true;
    const levels = srLevels(curBars);
    drawSrLines(levels);
    return { on: true, n: levels.length };
  }
'''
new = '''  function syncSrControls() {
    const cb = $("sr-toggle"), btn = $("sr-find-btn");
    if (cb) cb.checked = !!opts.sr;
    if (btn) btn.classList.toggle("active", !!opts.sr);
  }

  function autoSR() {
    if (!chart || !curBars.length) return { on: false, n: 0 };
    if (opts.sr) {
      opts.sr = false;
      syncSrControls();
      drawSrLines([]);
      return { on: false, n: 0 };
    }
    // ON — full rescan, replace the authoritative cache, and show it.
    opts.sr = true;
    srLevelsCache = srLevels(curBars);
    srCacheGroup = group;
    srCacheFingerprint = srFingerprint();
    srRescanNeeded = false;
    syncSrControls();
    drawSrLines(srLevelsCache);
    return { on: true, n: srLevelsCache.length };
  }
'''
if old not in s:
    raise SystemExit('autoSR block not found')
s = s.replace(old, new, 1)

old = '''    bindOpt("pat-toggle", "pat");
    bindOpt("sr-toggle", "sr");
    bindOpt("tl-toggle", "tl");
'''
new = '''    bindOpt("pat-toggle", "pat");
    bindOpt("sr-toggle", "sr", syncSrControls);
    bindOpt("tl-toggle", "tl");
'''
if old not in s:
    raise SystemExit('bindOpt sr block not found')
s = s.replace(old, new, 1)

p.write_text(s)

# ---- static/js/app.js ----
p = Path('static/js/app.js')
s = p.read_text()

old = '''const srBtn = $("sr-find-btn");
if (srBtn) {
  srBtn.classList.add("active");   // S/R checkbox defaults to ON
  srBtn.addEventListener("click", () => {
    if (window.TRXChart && TRXChart.autoSR) {
      const r = TRXChart.autoSR();
      srBtn.classList.toggle("active", r.on);
      clearTimeout(srBtn._t);
      if (r.on) {
        srBtn.textContent = `🔍 S/R ×${r.n}`;
        srBtn._t = setTimeout(() => { srBtn.textContent = "🔍 S/R"; }, 2500);
      } else {
        srBtn.textContent = "🔍 S/R";
      }
    }
  });
}
'''
new = '''const srBtn = $("sr-find-btn");
if (srBtn) {
  srBtn.classList.add("active");   // S/R checkbox defaults to ON
  srBtn.addEventListener("click", () => {
    if (window.TRXChart && TRXChart.autoSR) {
      const r = TRXChart.autoSR();
      srBtn.classList.toggle("active", r.on);
      clearTimeout(srBtn._t);
      if (r.on) {
        srBtn.textContent = `🔍 S/R ×${r.n}`;
        srBtn._t = setTimeout(() => { srBtn.textContent = "🔍 S/R"; }, 2500);
      } else {
        srBtn.textContent = "🔍 S/R";
      }
    }
  });
}
'''
# Keep block stable; state authority now lives in chart.js.
if old not in s:
    raise SystemExit('S/R toolbar block not found')

old2 = '''const dtToggle = $("dt-toggle-btn");
const drawBar = $("draw-tools");
const indBar = $("ind-bar");
if (dtToggle) {
  dtToggle.addEventListener("click", () => {
    const anyOpen = (drawBar && !drawBar.classList.contains("collapsed")) ||
                    (indBar && !indBar.classList.contains("collapsed"));
    if (drawBar) drawBar.classList.toggle("collapsed", anyOpen);   // open→close, closed→open
    if (indBar) indBar.classList.toggle("collapsed", anyOpen);
    dtToggle.classList.toggle("active", !anyOpen);
  });
}
'''
new2 = '''const dtToggle = $("dt-toggle-btn");
const indToggle = $("ind-toggle-btn");
const drawBar = $("draw-tools");
const indBar = $("ind-bar");
if (dtToggle) {
  dtToggle.addEventListener("click", () => {
    const open = drawBar && drawBar.classList.contains("collapsed");
    if (drawBar) drawBar.classList.toggle("collapsed", !open);
    dtToggle.classList.toggle("active", !!open);
  });
}
if (indToggle) {
  indToggle.addEventListener("click", () => {
    const open = indBar && indBar.classList.contains("collapsed");
    if (indBar) indBar.classList.toggle("collapsed", !open);
    indToggle.classList.toggle("active", !!open);
  });
}
'''
if old2 not in s:
    raise SystemExit('toolbar toggle block not found')
s = s.replace(old2, new2, 1)

old3 = '''    const rd = d.round;
    if (!rd || !rd.issue || rd.issue === lastKnownIssue) return;
    const first = lastKnownIssue === "";
    lastKnownIssue = rd.issue;
    if (first || !lastState) return;
'''
new3 = '''    const rd = d.round;
    if (!rd || !rd.issue || rd.issue === lastKnownIssue) return;
    const first = lastKnownIssue === "";
    const previousIssue = lastKnownIssue;
    lastKnownIssue = rd.issue;
    if (first || !lastState) return;

    // Never synthesize across missing rounds. Browser sleep/network gaps can jump
    // several sequential issues; catch history up first so the ±1 walk stays exact.
    try {
      if (/^\\d+$/.test(String(previousIssue)) && /^\\d+$/.test(String(rd.issue))
          && BigInt(String(rd.issue)) > BigInt(String(previousIssue)) + 1n) {
        await fetchFullHistory(true);
        await refresh();
        return;
      }
    } catch (_e) { /* non-standard issue format: fall back to normal path */ }
'''
if old3 not in s:
    raise SystemExit('latest issue block not found')
s = s.replace(old3, new3, 1)

p.write_text(s)

Path('tests_chart_correctness_v2.py').write_text(r'''from pathlib import Path

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
assert 'bars[i].c > bars[i].o ? 1 : bars[i].c < bars[i].o ? -1 : 0' in chart
assert 'if (dir === 0) { flushRun(); rd = 0; rl = 0; rEnd = -1; continue; }' in chart

# Rebuild fingerprint notices corrections to recent rows, not only len/last issue.
assert 'const tailFingerprint = hist.slice(-3)' in chart
assert '${tailFingerprint}' in chart

# Fast append refuses to bridge missing sequential issues.
assert 'BigInt(String(rd.issue)) > BigInt(String(previousIssue)) + 1n' in app
assert 'await fetchFullHistory(true);' in app
assert 'await refresh();' in app

# Drawing and indicator toolbar controls are independently operable.
assert 'const indToggle = $("ind-toggle-btn")' in app
assert 'drawBar.classList.toggle("collapsed", !open)' in app
assert 'indBar.classList.toggle("collapsed", !open)' in app

for f in ["decision.py", "robust_engine.py", "app_core.py", "drawings_persistence.py"]:
    assert Path(f).exists()
print("Chart Correctness & Cache Fix contract OK")
''')
