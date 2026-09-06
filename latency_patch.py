from pathlib import Path


def replace_once(path, old, new, label):
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if old not in s:
        raise SystemExit(f"patch anchor missing: {label}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")


replace_once(
    "app_core.py",
    'POLL_SEC = 2        # tail-mode (?limit=500 ≈ 80KB) — fast candle updates\n',
    '''# Low-latency tail polling. Keep these env-tunable so hosting can back off\n# without a code deploy if the upstream source ever rate-limits.\ntry:\n    POLL_SEC = max(0.25, min(float(os.environ.get("TRX_POLL_SEC", "0.5")), 5.0))\nexcept (TypeError, ValueError):\n    POLL_SEC = 0.5\ntry:\n    TAIL_LIMIT = max(20, min(int(os.environ.get("TRX_TAIL_LIMIT", "50")), 500))\nexcept (TypeError, ValueError):\n    TAIL_LIMIT = 50\n''',
    "backend poll settings",
)

replace_once(
    "app_core.py",
    '            url = URL_DATA if not have_full else URL_DATA + "?limit=500"\n            res = session.get(\n                url, timeout=15,\n',
    '            url = URL_DATA if not have_full else URL_DATA + f"?limit={TAIL_LIMIT}"\n            timeout_sec = 15 if not have_full else 6\n            res = session.get(\n                url, timeout=timeout_sec,\n',
    "tail URL and timeout",
)

replace_once(
    "app_core.py",
    '                        print(f"[ENGINE] full snapshot: {len(all_rows)} rounds "\n                              f"(tail mode: {POLL_SEC}s · ?limit=500)", flush=True)\n',
    '                        print(f"[ENGINE] full snapshot: {len(all_rows)} rounds "\n                              f"(tail mode: {POLL_SEC}s · ?limit={TAIL_LIMIT})", flush=True)\n',
    "tail startup log",
)

replace_once(
    "static/js/app.js",
    'setInterval(refresh, 2000);\n',
    'setInterval(refresh, 1500);\n',
    "state refresh cadence",
)

replace_once(
    "static/js/app.js",
    'async function pollLatest() {\n  try {\n',
    'let latestPolling = false;\nasync function pollLatest() {\n  if (latestPolling) return;\n  latestPolling = true;\n  try {\n',
    "latest overlap guard start",
)

replace_once(
    "static/js/app.js",
    '''      const merged = mergeRows(fullRows, lastState.history);\n      safeRender(() => render(lastState, merged), lastState);\n    }\n  } catch (e) { /* noop */ }\n}\nsetInterval(pollLatest, 1200);\n''',
    '''      const newest = fullRows[fullRows.length - 1];\n      const fast = window.TRXChart && TRXChart.appendLatest\n        ? TRXChart.appendLatest(newest)\n        : false;\n      if (!fast) {\n        const merged = mergeRows(fullRows, lastState.history);\n        safeRender(() => render(lastState, merged), lastState);\n      }\n    }\n  } catch (e) { /* noop */ }\n  finally { latestPolling = false; }\n}\nsetInterval(pollLatest, 400);\n''',
    "latest fast path and cadence",
)

replace_once(
    "static/js/chart.js",
    '''  /* ---- public: signal arrows toggle ---- */\n  function toggleSignals() {\n''',
    '''  /* ---- ultra-fast 1m candle append ----\n     /api/latest uses this path so a fresh result does not rebuild 10 days of\n     candles/indicators just to paint one bar. The normal /api/state refresh\n     follows shortly and performs the authoritative full indicator rebuild. */\n  function appendLatest(row) {\n    if (!chart || group !== 1 || !row || !row.issue || !curBars.length) return false;\n    const issue = String(row.issue);\n    if (curLabelMap instanceof Map && curLabelMap.has(issue)) return true;\n\n    const dir = row.type === "BIG" ? 1 : -1;\n    const open = curBars[curBars.length - 1].c;\n    const close = open + dir;\n    const time = curBars.length + 1;\n    const raw = { time, open, high: Math.max(open, close), low: Math.min(open, close), close };\n\n    try {\n      candleSeries.update(raw);\n      areaSeries.update({ time, value: close });\n    } catch (e) {\n      return false;\n    }\n\n    curBars.push({ time, o: open, h: raw.high, l: raw.low, c: close });\n    curLabels.push(row.short_issue || issue.slice(-6));\n    curTimes.push(row.block_time || row.hm || "");\n    curFulls.push(issue);\n    if (!(curLabelMap instanceof Map)) curLabelMap = new Map();\n    curLabelMap.set(issue, time);\n    lastLen = curBars.length;\n    updateLegend(curBars[curBars.length - 1]);\n\n    if (window.TRXDraw && window.TRXDraw.onData) {\n      try {\n        window.TRXDraw.onData({\n          chart, series: candleSeries, labels: curLabels,\n          labelMap: curLabelMap, fulls: curFulls,\n        });\n      } catch (e) { /* drawing overlay can wait for full refresh */ }\n    }\n    return true;\n  }\n\n  /* ---- public: signal arrows toggle ---- */\n  function toggleSignals() {\n''',
    "chart fast append",
)

replace_once(
    "static/js/chart.js",
    '    update, autoSR, toggleSignals,\n',
    '    update, appendLatest, autoSR, toggleSignals,\n',
    "chart public append",
)

# Keep regression coverage close to the existing site audit suite.
p = Path("tests_deep_audit.py")
s = p.read_text(encoding="utf-8")
if "def test_low_latency_defaults():" not in s:
    marker = '\n\ndef test_flask_routes_smoke():\n'
    test = '''\n\ndef test_low_latency_defaults():\n    assert 0.25 <= core.POLL_SEC <= 1.0, core.POLL_SEC\n    assert 20 <= core.TAIL_LIMIT <= 100, core.TAIL_LIMIT\n\n'''
    if marker not in s:
        raise SystemExit("patch anchor missing: latency regression test")
    s = s.replace(marker, test + marker, 1)
    main_marker = '    test_rsi_extremes_accepts_wrapped_payload()\n    test_flask_routes_smoke()\n'
    if main_marker not in s:
        raise SystemExit("patch anchor missing: test main")
    s = s.replace(main_marker, '    test_rsi_extremes_accepts_wrapped_payload()\n    test_low_latency_defaults()\n    test_flask_routes_smoke()\n', 1)
    p.write_text(s, encoding="utf-8")
