from pathlib import Path

p = Path('static/js/chart.js')
s = p.read_text()

# Add crosshair state/cache globals.
s = s.replace('''  let rangeLock = false;\n''', '''  let rangeLock = false;\n  let crosshairLock = false;\n  let curRsiValues = [];\n  let curMacdValues = [];\n  let curStochValues = [];\n''', 1)

# Remove pane-local crosshair subscriptions; Phase 6 installs one coordinated handler.
blocks = [
'''    chart.subscribeCrosshairMove((param) => {\n      if (!param.time) { updateLegend(curBars[curBars.length - 1]); return; }\n      updateLegend(curBars[param.time - 1]);\n    });\n''',
'''    stochChart.subscribeCrosshairMove((param) => {\n      const el = $("lg-stoch");\n      if (!param.time) { if (el) { el.textContent = ""; el.className = ""; } return; }\n      const d = param.seriesData.get(stochKSeries);\n      if (el && d) {\n        el.textContent = d.value.toFixed(1);\n        el.className = d.value >= 80 ? "red" : d.value <= 20 ? "green" : "";\n      }\n    });\n''',
'''    rsiChart.subscribeCrosshairMove((param) => {\n      if (!param.time) { updateRsiLegend(null); return; }\n      const d = param.seriesData.get(rsiSeries);\n      updateRsiLegend(d ? d.value : null);\n    });\n''',
'''    macdChart.subscribeCrosshairMove((param) => {\n      const el = $("lg-macd");\n      if (!param.time) { if (el) { el.textContent = ""; el.className = ""; } return; }\n      const d = param.seriesData.get(macdLineSeries);\n      if (el && d) {\n        el.textContent = d.value.toFixed(2);\n        el.className = d.value >= 0 ? "green" : "red";\n      }\n    });\n'''
]
for b in blocks:
    if b not in s:
        raise SystemExit('crosshair block not found')
    s = s.replace(b, '', 1)

# Add synchronized legend + crosshair helpers before chart creation.
needle = '''  /* ================= chart creation ================= */\n'''
helpers = r'''  function updateMacdLegend(val) {
    const el = $("lg-macd");
    if (!el) return;
    if (val == null || !Number.isFinite(val)) { el.textContent = ""; el.className = ""; return; }
    el.textContent = val.toFixed(2);
    el.className = val >= 0 ? "green" : "red";
  }

  function updateStochLegend(val) {
    const el = $("lg-stoch");
    if (!el) return;
    if (val == null || !Number.isFinite(val)) { el.textContent = ""; el.className = ""; return; }
    el.textContent = val.toFixed(1);
    el.className = val >= 80 ? "red" : val <= 20 ? "green" : "";
  }

  function valueAt(arr, time) {
    const i = Number(time) - 1;
    return Number.isInteger(i) && i >= 0 && i < arr.length ? arr[i] : null;
  }

  function updateAllLegendsAtTime(time) {
    const i = Number(time) - 1;
    updateLegend(Number.isInteger(i) && i >= 0 ? curBars[i] : null);
    updateRsiLegend(valueAt(curRsiValues, time));
    updateMacdLegend(valueAt(curMacdValues, time));
    updateStochLegend(valueAt(curStochValues, time));
  }

  function restoreLatestLegends() {
    const t = curBars.length;
    if (t > 0) updateAllLegendsAtTime(t);
    else {
      updateLegend(null); updateRsiLegend(null); updateMacdLegend(null); updateStochLegend(null);
    }
  }

  function paneCrosshairTargets() {
    return [
      { chart, series: candleSeries, values: curBars.map((b) => b.c), enabled: true },
      { chart: rsiChart, series: rsiSeries, values: curRsiValues, enabled: opts.rsi },
      { chart: macdChart, series: macdLineSeries, values: curMacdValues, enabled: opts.macd },
      { chart: stochChart, series: stochKSeries, values: curStochValues, enabled: opts.stoch },
    ];
  }

  function syncCrosshairs() {
    // Phase 6 — one logical time across main + RSI + MACD + STOCH.
    // Guard programmatic moves because setCrosshairPosition can emit another move event.
    paneCrosshairTargets().filter((p) => p.chart).forEach((src) => {
      src.chart.subscribeCrosshairMove((param) => {
        if (crosshairLock) return;
        crosshairLock = true;
        try {
          const time = param && param.time;
          if (time == null) {
            paneCrosshairTargets().forEach((dst) => {
              if (dst.chart && dst.chart !== src.chart && typeof dst.chart.clearCrosshairPosition === "function") {
                try { dst.chart.clearCrosshairPosition(); } catch (e) { /* noop */ }
              }
            });
            restoreLatestLegends();
            return;
          }

          updateAllLegendsAtTime(time);
          paneCrosshairTargets().forEach((dst) => {
            if (!dst.chart || dst.chart === src.chart || !dst.series || !dst.enabled) return;
            const v = valueAt(dst.values, time);
            if (v == null || !Number.isFinite(v) || typeof dst.chart.setCrosshairPosition !== "function") return;
            try { dst.chart.setCrosshairPosition(v, time, dst.series); } catch (e) { /* noop */ }
          });
        } finally {
          crosshairLock = false;
        }
      });
    });
  }

'''
if needle not in s:
    raise SystemExit('chart creation needle not found')
s = s.replace(needle, helpers + needle, 1)

# Install after all panes are initialized.
s = s.replace('''    syncRanges();\n    bindToolbar();\n''', '''    syncRanges();\n    syncCrosshairs();\n    bindToolbar();\n''', 1)

# Cache indicator arrays and use shared legend helpers.
s = s.replace('''      const rsiArr = calcRsi(closes, 14);\n      rsiSeries.setData(linePoints(rsiArr));\n      const lastRsi = [...rsiArr].reverse().find((v) => v != null);\n      updateRsiLegend(lastRsi);\n''', '''      const rsiArr = calcRsi(closes, 14);\n      curRsiValues = rsiArr.slice();\n      rsiSeries.setData(linePoints(rsiArr));\n      const lastRsi = [...rsiArr].reverse().find((v) => v != null);\n      updateRsiLegend(lastRsi);\n''', 1)
s = s.replace('''      const m = calcMacd(closes, 12, 26, 9);\n      macdLineSeries.setData(linePoints(m.macd));\n''', '''      const m = calcMacd(closes, 12, 26, 9);\n      curMacdValues = m.macd.slice();\n      macdLineSeries.setData(linePoints(m.macd));\n''', 1)
s = s.replace('''      const st = calcStoch(closes, 14, 3, 3);\n      stochKSeries.setData(linePoints(st.k));\n''', '''      const st = calcStoch(closes, 14, 3, 3);\n      curStochValues = st.k.slice();\n      stochKSeries.setData(linePoints(st.k));\n''', 1)

p.write_text(s)

Path('tests_crosshair_sync_v2.py').write_text(r'''from pathlib import Path
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
''')
