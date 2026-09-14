from pathlib import Path


def replace_once(path, old, new):
    p = Path(path)
    s = p.read_text(encoding='utf-8')
    if old not in s:
        raise SystemExit(f'pattern not found in {path}: {old[:180]!r}')
    p.write_text(s.replace(old, new, 1), encoding='utf-8')

# Backend: explicitly request enough upstream rows for a 10-day 1m chart.
replace_once(
    'app_core.py',
    '            url = URL_DATA if not have_full else URL_DATA + f"?limit={TAIL_LIMIT}"\n            timeout_sec = 15 if not have_full else 6',
    '            # Do not rely on the upstream bare-endpoint default size. Request an\n            # explicit deep snapshot so the 10-day chart cannot silently collapse\n            # to a small provider default after an upstream behavior change.\n            url = (URL_DATA + f"?limit={MAX_FULL_ROWS}") if not have_full else URL_DATA + f"?limit={TAIL_LIMIT}"\n            timeout_sec = 30 if not have_full else 6'
)

# Feed wrapper: only the genuinely small polling request is a live-tail request.
replace_once(
    'app.py',
    'import time\nfrom collections import Counter',
    'import time\nfrom urllib.parse import parse_qs, urlparse\nfrom collections import Counter'
)
replace_once(
    'app.py',
    '''def _resilient_session_get(url, *args, **kwargs):\n    """Freshness-aware upstream fetch with active stale-feed recovery."""\n    url_s = str(url)\n    is_feed = url_s.startswith(core.URL_DATA)\n    is_tail = is_feed and "?limit=" in url_s\n    actual_url = url_s\n''',
    '''def _feed_limit(url_s):\n    try:\n        raw = parse_qs(urlparse(str(url_s)).query).get("limit", [None])[0]\n        return int(raw) if raw is not None else None\n    except (TypeError, ValueError):\n        return None\n\n\ndef _is_live_tail_url(url_s):\n    """Only small bounded polling requests get tail timeouts/cache rescue."""\n    limit = _feed_limit(url_s)\n    return str(url_s).startswith(core.URL_DATA) and limit is not None and limit <= max(500, int(getattr(core, "TAIL_LIMIT", 50)))\n\n\ndef _resilient_session_get(url, *args, **kwargs):\n    """Freshness-aware upstream fetch with active stale-feed recovery."""\n    url_s = str(url)\n    is_feed = url_s.startswith(core.URL_DATA)\n    is_tail = _is_live_tail_url(url_s)\n    actual_url = url_s\n'''
)

# Frontend history integrity + retry behavior.
replace_once(
    'static/js/app.js',
    '''function mergeRows(a, b) {\n  const m = new Map();\n  (a || []).forEach((r) => m.set(r.issue, r));\n  (b || []).forEach((r) => { if (!m.has(r.issue)) m.set(r.issue, r); });\n  return [...m.values()].sort((x, y) => (x.issue < y.issue ? -1 : x.issue > y.issue ? 1 : 0));\n}\n''',
    '''function mergeRows(a, b) {\n  const m = new Map();\n  (a || []).forEach((r) => m.set(r.issue, r));\n  // Newer/server-authoritative copies win. This also lets corrected historical\n  // rows replace stale browser copies instead of being silently masked.\n  (b || []).forEach((r) => m.set(r.issue, r));\n  return [...m.values()].sort((x, y) => (x.issue < y.issue ? -1 : x.issue > y.issue ? 1 : 0));\n}\n'''
)
replace_once(
    'static/js/app.js',
    '''    if (inc.length) {\n      fullRows = mergeRows(fullRows, inc);\n      if (fullRows.length > 30000) fullRows = fullRows.slice(-30000);\n    } else if (!force && !inc.length && data.incremental) {\n      /* server has nothing newer (or was restarted with a shorter buffer):\n         force one full refetch on the next cycle */\n      lastHistFetch = 0;\n    }\n''',
    '''    if (inc.length) {\n      // A forced fetch is a fresh authoritative 10-day snapshot, not an append.\n      // Incremental fetches append/replace by issue.\n      fullRows = force ? mergeRows([], inc) : mergeRows(fullRows, inc);\n      if (fullRows.length > 30000) fullRows = fullRows.slice(-30000);\n    } else {\n      // Initial page load can beat the background engine. Do not lock the chart\n      // into the small /api/state fallback for 45 seconds; allow the next refresh\n      // to retry the full history immediately.\n      lastHistFetch = 0;\n    }\n'''
)
replace_once(
    'static/js/app.js',
    '''    if (metaEl && data.meta) {\n      metaEl.textContent = `${(data.meta.count || fullRows.length).toLocaleString("en-US")} rounds · ${data.meta.days}d loaded`;\n    }\n''',
    '''    if (metaEl) {\n      const days = data.meta && data.meta.days ? data.meta.days : 10;\n      metaEl.textContent = `${fullRows.length.toLocaleString("en-US")} rounds · ${days}D BUFFER`;\n      metaEl.title = `Loaded chart history: ${fullRows.length.toLocaleString("en-US")} rounds`;\n    }\n'''
)

# Chart: default one-day analytical view + explicit 1D/3D/10D presets.
replace_once(
    'static/js/chart.js',
    '        minBarSpacing: 0.5,',
    '        minBarSpacing: 0.02,'
)
replace_once(
    'static/js/chart.js',
    '''    const activeTf = document.querySelector(".tf-btn.active[data-g]");\n    if (activeTf) { const tf = $("lg-tf"); if (tf) tf.textContent = activeTf.textContent; }\n    const fitBtn = $("fit-btn");\n''',
    '''    const activeTf = document.querySelector(".tf-btn.active[data-g]");\n    if (activeTf) { const tf = $("lg-tf"); if (tf) tf.textContent = activeTf.textContent; }\n    document.querySelectorAll(".hist-range-btn").forEach((btn) => {\n      btn.addEventListener("click", () => {\n        document.querySelectorAll(".hist-range-btn").forEach((b) => b.classList.remove("active"));\n        btn.classList.add("active");\n        setHistoryRange(Number(btn.dataset.days) || 1);\n      });\n    });\n    const fitBtn = $("fit-btn");\n'''
)
replace_once(
    'static/js/chart.js',
    '''  function anchorRecent(n) {\n    const span = Math.min(Math.max(Math.round(320 / group), 60), n);\n    const range = { from: Math.max(1, n - span), to: n + 4 };\n    [chart, rsiChart, macdChart, stochChart].forEach((c) => {\n      if (!c) return;\n      try { c.timeScale().setVisibleLogicalRange(range); } catch (e) { /* noop */ }\n    });\n  }\n''',
    '''  function setHistoryRange(days = 1) {\n    const n = curBars.length;\n    if (!n) return false;\n    // group is minutes per candle. A 1D view therefore means 1440/group bars.\n    // 10D remains fully available; the very small minBarSpacing allows the whole\n    // buffer to be compressed even on mobile and then zoomed into normally.\n    const wanted = Math.max(1, Math.ceil((Number(days) || 1) * 1440 / Math.max(1, group)));\n    const from = Math.max(1, n - wanted + 1);\n    const range = { from, to: n + 4 };\n    [chart, rsiChart, macdChart, stochChart].forEach((c) => {\n      if (!c) return;\n      try { c.timeScale().setVisibleLogicalRange(range); } catch (e) { /* noop */ }\n    });\n    return true;\n  }\n\n  function anchorRecent() {\n    // Default analytical view: one full day, not the old ~320-bar (~5h) slice.\n    setHistoryRange(1);\n  }\n'''
)
replace_once(
    'static/js/chart.js',
    '        anchorRecent(curBars.length);',
    '        anchorRecent();'
)
replace_once(
    'static/js/chart.js',
    '    update, appendLatest, autoSR, toggleSignals,',
    '    update, appendLatest, autoSR, toggleSignals, setHistoryRange,'
)

# Toolbar: range presets + loaded buffer status; asset busting.
replace_once(
    'templates/index.html',
    '''        <button class="tf-btn" data-g="60">1h</button>\n        <button class="tf-btn fit" id="fit-btn" title="Chart အားလုံး ကျယ်ကျယ် မြင်ရန်">FIT</button>''',
    '''        <button class="tf-btn" data-g="60">1h</button>\n        <span class="tb-sep"></span>\n        <span class="tb-group-label">RANGE</span>\n        <button class="tf-btn hist-range-btn active" data-days="1" title="နောက်ဆုံး 1 ရက်">1D</button>\n        <button class="tf-btn hist-range-btn" data-days="3" title="နောက်ဆုံး 3 ရက်">3D</button>\n        <button class="tf-btn hist-range-btn" data-days="10" title="10-day history အကုန်">10D</button>\n        <span class="tb-group-label mono" id="chart-meta" title="Loaded chart history">loading…</span>\n        <button class="tf-btn fit" id="fit-btn" title="Chart အားလုံး ကျယ်ကျယ် မြင်ရန်">FIT</button>'''
)
replace_once('templates/index.html', "js/chart.js') }}?v=41", "js/chart.js') }}?v=45")
replace_once('templates/index.html', "js/app.js') }}?v=42", "js/app.js') }}?v=45")

# Browser QA: verify range controls remain usable.
p = Path('e2e/chart.spec.js')
s = p.read_text(encoding='utf-8')
insert_after = '''test('switches true timeframes and keeps the chart alive', async ({ page }) => {\n  await waitForChart(page);\n  for (const [g, label] of [['5', '5m'], ['15', '15m'], ['60', '1h'], ['1', '1m']]) {\n    await page.locator(`.tf-btn[data-g="${g}"]`).click();\n    await expect(page.locator('#lg-tf')).toHaveText(label);\n    await expect(page.locator(`.tf-btn[data-g="${g}"]`)).toHaveClass(/active/);\n    await expect(page.locator('#tv-chart canvas').first()).toBeVisible();\n  }\n});\n'''
extra = insert_after + '''\ntest('history range presets expose the full-history navigation controls', async ({ page }) => {\n  await waitForChart(page);\n  await page.locator('#ind-toggle-btn').click();\n  await expect(page.locator('#chart-meta')).not.toHaveText('loading…');\n  for (const d of ['3', '10', '1']) {\n    await page.locator(`.hist-range-btn[data-days="${d}"]`).click();\n    await expect(page.locator(`.hist-range-btn[data-days="${d}"]`)).toHaveClass(/active/);\n    await expect(page.locator('#tv-chart canvas').first()).toBeVisible();\n  }\n});\n'''
if insert_after not in s:
    raise SystemExit('E2E insertion anchor not found')
p.write_text(s.replace(insert_after, extra, 1), encoding='utf-8')

# Focused backend/source contracts.
Path('tests_chart_history_10d.py').write_text(r'''import os\nos.environ["TRX_NO_ENGINE"] = "1"\n\nfrom datetime import datetime, timedelta\nfrom pathlib import Path\n\nimport app_core\nimport app\n\n\ndef _row(day, i=1):\n    issue = day.strftime("%Y%m%d") + f"000000{i:03d}"\n    return {"issue": issue, "day_int": int(day.strftime("%Y%m%d"))}\n\n\ndef test_trim_full_history_keeps_ten_calendar_days():\n    start = datetime(2026, 9, 1)\n    rows = [_row(start + timedelta(days=i)) for i in range(14)]\n    out = app_core.trim_full_history(rows, 10)\n    assert len(out) == 10\n    assert out[0]["day_int"] == 20260905\n    assert out[-1]["day_int"] == 20260914\n\n\ndef test_boot_requests_explicit_deep_history_limit():\n    src = Path("app_core.py").read_text(encoding="utf-8")\n    assert 'URL_DATA + f"?limit={MAX_FULL_ROWS}"' in src\n    assert 'timeout_sec = 30 if not have_full else 6' in src\n\n\ndef test_large_history_requests_are_not_live_tail():\n    assert app._is_live_tail_url(app_core.URL_DATA + "?limit=50")\n    assert app._is_live_tail_url(app_core.URL_DATA + "?limit=500")\n    assert not app._is_live_tail_url(app_core.URL_DATA + "?limit=30000")\n    assert not app._is_live_tail_url(app_core.URL_DATA + "?limit=45200")\n\n\ndef test_frontend_has_10day_range_and_authoritative_merge():\n    js = Path("static/js/app.js").read_text(encoding="utf-8")\n    chart = Path("static/js/chart.js").read_text(encoding="utf-8")\n    html = Path("templates/index.html").read_text(encoding="utf-8")\n    assert '(b || []).forEach((r) => m.set(r.issue, r));' in js\n    assert 'fullRows = force ? mergeRows([], inc)' in js\n    assert 'setHistoryRange(days = 1)' in chart\n    assert '1440 / Math.max(1, group)' in chart\n    assert 'data-days="10"' in html\n    assert 'id="chart-meta"' in html\n'''.replace('\\n','\n'), encoding='utf-8')
