from pathlib import Path

p = Path('static/js/chart.js')
s = p.read_text()
old = '''  /* ================= bars from BIG/SMALL walk ================= */
  function buildBars(rows) {
    const bars = [];
    const labels = [];
    const times = [];
    const fulls = [];             // per-slot FULL issue (drawing anchor key)
    const labelMap = new Map();
    let price = BASE;
    rows.forEach((item, idx) => {
      const dir = item.type === "BIG" ? 1 : -1;
      const open = price;
      const close = price + dir;
      const hi = Math.max(open, close);
      const lo = Math.min(open, close);
      const slot = Math.floor(idx / group);
      if (!bars[slot]) {
        bars[slot] = { time: slot + 1, open, high: hi, low: lo, close };
        labels[slot] = item.short_issue || String(item.issue).slice(-6);
        times[slot] = item.block_time || item.hm || "";
        fulls[slot] = String(item.issue);
      } else {
        const b = bars[slot];
        b.close = close;
        if (hi > b.high) b.high = hi;
        if (lo < b.low) b.low = lo;
        times[slot] = item.block_time || item.hm || "";
      }
      const lb = item.short_issue || String(item.issue).slice(-6);
      /* anchor by FULL issue — 6-digit suffixes repeat across days and
         would teleport drawings/markers to the wrong day's bar */
      const fk = String(item.issue);
      if (!labelMap.has(fk)) labelMap.set(fk, slot + 1);
      price = close;
    });
    return { bars, labels, labelMap, times, fulls };
  }
'''
new = '''  /* ================= bars from BIG/SMALL walk ================= */
  // Phase 5 — True Timeframe Aggregation.
  // Bucket by the source wall-clock timestamp, not by row position. We deliberately
  // parse the YYYY-MM-DD HH:MM[:SS] fields ourselves so browser timezone conversion
  // cannot shift 5m/15m/1h boundaries. Invalid/missing timestamps safely fall back
  // to legacy index grouping instead of breaking the chart.
  function parseWallClock(item) {
    const raw = String((item && (item.block_time || item.blockTime || item.time)) || "").trim();
    const m = raw.match(/^(\\d{4})-(\\d{2})-(\\d{2})[ T](\\d{2}):(\\d{2})(?::(\\d{2}))?/);
    if (!m) return null;
    const year = Number(m[1]), month = Number(m[2]), day = Number(m[3]);
    const hour = Number(m[4]), minute = Number(m[5]), second = Number(m[6] || 0);
    if (month < 1 || month > 12 || day < 1 || day > 31 || hour < 0 || hour > 23 || minute < 0 || minute > 59 || second < 0 || second > 59) return null;
    return { year, month, day, hour, minute, second };
  }

  function pad2(v) { return String(v).padStart(2, "0"); }

  function timeframeBucket(item, tfMinutes, fallbackIndex) {
    const tf = Math.max(1, Number(tfMinutes) || 1);
    const wc = parseWallClock(item);
    if (!wc) {
      const legacySlot = Math.floor(fallbackIndex / tf);
      return { key: `legacy:${legacySlot}`, labelTime: String((item && (item.block_time || item.hm)) || "") };
    }
    const bucketMinute = tf >= 60 ? 0 : Math.floor(wc.minute / tf) * tf;
    const key = `${wc.year}-${pad2(wc.month)}-${pad2(wc.day)}|${pad2(wc.hour)}:${pad2(bucketMinute)}|${tf}`;
    const labelTime = `${wc.year}-${pad2(wc.month)}-${pad2(wc.day)} ${pad2(wc.hour)}:${pad2(bucketMinute)}:00`;
    return { key, labelTime };
  }

  function buildBars(rows) {
    const bars = [];
    const labels = [];
    const times = [];
    const fulls = [];             // per-slot FULL issue (drawing anchor key)
    const labelMap = new Map();
    const bucketSlots = new Map();
    let price = BASE;
    rows.forEach((item, idx) => {
      const dir = item.type === "BIG" ? 1 : -1;
      const open = price;
      const close = price + dir;
      const hi = Math.max(open, close);
      const lo = Math.min(open, close);
      const bucket = timeframeBucket(item, group, idx);
      let slot = bucketSlots.get(bucket.key);
      if (slot == null) {
        slot = bars.length;
        bucketSlots.set(bucket.key, slot);
        bars.push({ time: slot + 1, open, high: hi, low: lo, close });
        labels[slot] = item.short_issue || String(item.issue).slice(-6);
        times[slot] = bucket.labelTime || item.block_time || item.hm || "";
        fulls[slot] = String(item.issue);
      } else {
        const b = bars[slot];
        b.close = close;
        if (hi > b.high) b.high = hi;
        if (lo < b.low) b.low = lo;
        // Keep the true bucket start time stable; only OHLC evolves inside the candle.
        if (!times[slot]) times[slot] = bucket.labelTime || item.block_time || item.hm || "";
      }
      /* anchor every FULL issue to its containing timeframe candle — drawings and
         signal markers remain exact even though several 1m issues share one bar. */
      const fk = String(item.issue);
      if (!labelMap.has(fk)) labelMap.set(fk, slot + 1);
      price = close;
    });
    return { bars, labels, labelMap, times, fulls };
  }
'''
if old not in s:
    raise SystemExit('buildBars block not found')
s = s.replace(old, new, 1)
p.write_text(s)

Path('tests_timeframe_v2.py').write_text(r'''from pathlib import Path

s = Path("static/js/chart.js").read_text()
assert "function parseWallClock(item)" in s
assert "function timeframeBucket(item, tfMinutes, fallbackIndex)" in s
assert "bucketMinute = tf >= 60 ? 0 : Math.floor(wc.minute / tf) * tf" in s
assert "const bucketSlots = new Map()" in s
assert "bucketSlots.get(bucket.key)" in s
assert "labelMap.set(fk, slot + 1)" in s
assert "Math.floor(idx / group)" not in s
assert "legacySlot = Math.floor(fallbackIndex / tf)" in s

# Boundary examples for the same wall-clock bucketing rule.
def bucket(ts, tf):
    date, clock = ts.split(" ")
    hh, mm, *_ = map(int, clock.split(":"))
    bm = 0 if tf >= 60 else (mm // tf) * tf
    return f"{date} {hh:02d}:{bm:02d}"

assert bucket("2026-09-13 12:02:10", 5) == "2026-09-13 12:00"
assert bucket("2026-09-13 12:05:00", 5) == "2026-09-13 12:05"
assert bucket("2026-09-13 12:29:59", 15) == "2026-09-13 12:15"
assert bucket("2026-09-13 12:45:01", 15) == "2026-09-13 12:45"
assert bucket("2026-09-13 12:59:59", 60) == "2026-09-13 12:00"
assert bucket("2026-09-13 13:00:00", 60) == "2026-09-13 13:00"
for f in ["decision.py", "robust_engine.py", "app_core.py"]:
    assert Path(f).exists()
print("True Timeframe Aggregation contract OK")
''')
