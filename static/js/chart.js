/* TradingView-style chart (Lightweight Charts v4)
   Trend model: BIG -> +1 step, SMALL -> -1 step
   Features: Candles/Area · TF grouping ×1..×50 · EMA 5/15 · Bollinger Bands
             RSI(14) sub-pane (synced) · Auto Trendlines · S/R levels
             Pattern markers: DT / DB / HS / IHS / 3 Soldiers / 3 Crows */
window.TRXChart = (() => {
  const UP = "#089981";
  const DOWN = "#f23645";
  const WIN_C = "#089981";
  const LOSS_C = "#f23645";
  const BASE = 100;
  const PAT_TOL = 0.9;        // pattern peak tolerance (price units)
  const PIVOT_K = 3;          // fractal pivot strength

  let chart = null;
  let rsiChart = null;
  let macdChart = null;
  let macdLineSeries = null;
  let macdSigSeries = null;
  let macdHistSeries = null;
  let candleSeries = null;
  let areaSeries = null;
  let emaFastSeries = null;
  let emaSlowSeries = null;
  let emaLongSeries = null;
  let bbUpperSeries = null;
  let bbMidSeries = null;
  let bbLowerSeries = null;
  let tlResSeries = null;     // resistance trendline
  let tlSupSeries = null;     // support trendline
  let rsiSeries = null;
  let srLines = [];           // active price lines
  let containerEl = null;
  let rsiEl = null;
  let macdEl = null;
  let stochEl = null;
  let stochChart = null;
  let stochKSeries = null;
  let stochDSeries = null;

  let group = 1;
  let viewMode = "candles";   // candles | line
  let opts = {
    ema: true, bb: false, rsi: true, sig: true,
    pat: true, sr: true, tl: true, macd: false, stoch: false,
  };

  /* S/R level cache — levels must NOT drift on every data tick */
  let srLevelsCache = [];
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

  let curBars = [];           // [{time,o,h,l,c}]
  let curLabels = [];
  let curTimes = [];          // real blockTime per bar (slot index -> "YYYY-MM-DD HH:MM:SS")
  let curFulls = [];          // per-slot FULL issue (drawing anchor)
  let curLabelMap = new Map();
  let fittedOnce = false;
  let lastLen = 0;
  let lastKey = "";
  let lastState = null;
  let rangeLock = false;

  const $ = (id) => document.getElementById(id);

  /* ================= indicator math ================= */
  function calcEma(values, period) {
    const out = new Array(values.length).fill(null);
    if (values.length < period) return out;
    const k = 2 / (period + 1);
    let e = 0;
    for (let i = 0; i < period; i++) e += values[i];
    e /= period;
    out[period - 1] = e;
    for (let i = period; i < values.length; i++) {
      e = values[i] * k + e * (1 - k);
      out[i] = e;
    }
    return out;
  }

  function calcRsi(closes, period = 14) {
    const out = new Array(closes.length).fill(null);
    if (closes.length < period + 1) return out;
    let g = 0, l = 0;
    for (let i = 1; i <= period; i++) {
      const d = closes[i] - closes[i - 1];
      if (d > 0) g += d; else l -= d;
    }
    let ag = g / period, al = l / period;
    out[period] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
    for (let i = period + 1; i < closes.length; i++) {
      const d = closes[i] - closes[i - 1];
      ag = (ag * (period - 1) + Math.max(d, 0)) / period;
      al = (al * (period - 1) + Math.max(-d, 0)) / period;
      out[i] = al === 0 ? 100 : 100 - 100 / (1 + ag / al);
    }
    return out;
  }

  function calcBB(closes, period = 20, mult = 2) {
    const up = [], mid = [], lo = [];
    for (let i = 0; i < closes.length; i++) {
      if (i < period - 1) { up.push(null); mid.push(null); lo.push(null); continue; }
      let s = 0;
      for (let j = i - period + 1; j <= i; j++) s += closes[j];
      const mean = s / period;
      let v = 0;
      for (let j = i - period + 1; j <= i; j++) v += (closes[j] - mean) ** 2;
      const sd = Math.sqrt(v / period);
      up.push(mean + mult * sd);
      mid.push(mean);
      lo.push(mean - mult * sd);
    }
    return { up, mid, lo };
  }

  function calcMacd(closes, fast = 12, slow = 26, sig = 9) {
    const ef = calcEma(closes, fast), es = calcEma(closes, slow);
    const macd = closes.map((_, i) =>
      ef[i] == null || es[i] == null ? null : ef[i] - es[i]);
    // EMA of MACD line
    const signal = new Array(closes.length).fill(null);
    const k = 2 / (sig + 1);
    let prev = null;
    for (let i = 0; i < closes.length; i++) {
      if (macd[i] == null) continue;
      prev = prev == null ? macd[i] : macd[i] * k + prev * (1 - k);
      signal[i] = prev;
    }
    const hist = macd.map((v, i) => (v == null || signal[i] == null) ? null : v - signal[i]);
    return { macd, signal, hist };
  }

  function smaArr(values, period) {
    const out = new Array(values.length).fill(null);
    let sum = 0, bad = 0;
    const q = [];
    for (let i = 0; i < values.length; i++) {
      const v = values[i];
      q.push(v);
      if (v == null) bad++; else sum += v;
      if (q.length > period) {
        const old = q.shift();
        if (old == null) bad--; else sum -= old;
      }
      if (q.length === period && bad === 0) out[i] = sum / period;
    }
    return out;
  }

  function calcStoch(closes, period = 14, kSmooth = 3, dSmooth = 3) {
    const raw = new Array(closes.length).fill(null);
    for (let i = period - 1; i < closes.length; i++) {
      let hh = -Infinity, ll = Infinity;
      for (let j = i - period + 1; j <= i; j++) {
        if (closes[j] > hh) hh = closes[j];
        if (closes[j] < ll) ll = closes[j];
      }
      raw[i] = hh === ll ? 50 : ((closes[i] - ll) / (hh - ll)) * 100;
    }
    const k = smaArr(raw, kSmooth);
    const d = smaArr(k, dSmooth);
    return { k, d };
  }

  /* ================= bars from BIG/SMALL walk ================= */
  // Phase 5 — True Timeframe Aggregation.
  // Bucket by the source wall-clock timestamp, not by row position. We deliberately
  // parse the YYYY-MM-DD HH:MM[:SS] fields ourselves so browser timezone conversion
  // cannot shift 5m/15m/1h boundaries. Invalid/missing timestamps safely fall back
  // to legacy index grouping instead of breaking the chart.
  function parseWallClock(item) {
    const raw = String((item && (item.block_time || item.blockTime || item.time)) || "").trim();
    const m = raw.match(/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})(?::(\d{2}))?/);
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

  function linePoints(arr) {
    const pts = [];
    arr.forEach((v, i) => { if (v !== null && v !== undefined) pts.push({ time: i + 1, value: v }); });
    return pts;
  }

  /* ================= pivots & structure ================= */
  function findPivots(bars, k = PIVOT_K) {
    const hi = [], lo = [];
    for (let i = k; i < bars.length - k; i++) {
      let isH = true, isL = true;
      for (let j = 1; j <= k; j++) {
        if (bars[i].high <= bars[i - j].high || bars[i].high <= bars[i + j].high) isH = false;
        if (bars[i].low >= bars[i - j].low || bars[i].low >= bars[i + j].low) isL = false;
        if (!isH && !isL) break;
      }
      if (isH) hi.push({ i, t: bars[i].time, v: bars[i].high });
      if (isL) lo.push({ i, t: bars[i].time, v: bars[i].low });
    }
    return { hi, lo };
  }

  /* ---- Auto Trend Line v2 -------------------------------------------------
     Build many bounded candidates instead of blindly joining the last 2 pivots.
     Candidates are scored by: pivot touches, pivot prominence, recency, retests,
     line age/span, slope quality and post-anchor violations. A recent decisive
     break invalidates the line. This is display-only chart structure logic. */
  function pivotProminence(p, bars, kind, radius = 8) {
    const a = Math.max(0, p.i - radius), z = Math.min(bars.length - 1, p.i + radius);
    if (kind === "res") {
      let floor = Infinity;
      for (let i = a; i <= z; i++) floor = Math.min(floor, bars[i].l);
      return Math.max(0, p.v - floor);
    }
    let ceil = -Infinity;
    for (let i = a; i <= z; i++) ceil = Math.max(ceil, bars[i].h);
    return Math.max(0, ceil - p.v);
  }

  function trendSegV2(pivs, bars, kind) {
    if (!bars.length || pivs.length < 2) return null;

    // Keep runtime bounded on long history while still considering older anchors.
    const ps = pivs.slice(-48);
    const lastI = bars.length - 1;
    const touchTol = 0.8;
    const hardBreak = 1.35;
    let best = null;

    for (let a = 0; a < ps.length - 1; a++) {
      const p1 = ps[a];
      for (let b = a + 1; b < ps.length; b++) {
        const p2 = ps[b];
        const gap = p2.i - p1.i;
        if (gap < 6 || gap > 420) continue;
        const dt = p2.t - p1.t;
        if (!dt) continue;
        const slope = (p2.v - p1.v) / dt;
        const absSlope = Math.abs(slope);
        if (absSlope > 0.5) continue; // implausibly steep on the ±1 synthetic walk

        const lineAt = (i) => p1.v + slope * (bars[i].time - p1.t);

        // A decisive recent break means the old boundary is no longer active.
        let broken = false;
        const recentFrom = Math.max(p2.i + 1, lastI - 12);
        for (let i = recentFrom; i <= lastI; i++) {
          const lv = lineAt(i);
          if (kind === "res" ? bars[i].h > lv + hardBreak : bars[i].l < lv - hardBreak) {
            broken = true; break;
          }
        }
        if (broken) continue;

        let violations = 0;
        for (let i = p2.i + 1; i <= lastI; i++) {
          const lv = lineAt(i);
          if (kind === "res" ? bars[i].h > lv + touchTol : bars[i].l < lv - touchTol) violations++;
        }
        // Allow a tiny amount of noise, but reject repeatedly pierced boundaries.
        const allowedViolations = Math.max(1, Math.floor((lastI - p2.i) / 90));
        if (violations > allowedViolations) continue;

        let touches = 0, retests = 0;
        for (const q of ps) {
          if (q.i < p1.i) continue;
          const lv = p1.v + slope * (q.t - p1.t);
          if (Math.abs(q.v - lv) <= touchTol) {
            touches++;
            if (q.i > p2.i) retests++;
          }
        }
        if (touches < 2) continue;

        const prom1 = pivotProminence(p1, bars, kind);
        const prom2 = pivotProminence(p2, bars, kind);
        const prominence = Math.min(8, (prom1 + prom2) / 2);
        const age = Math.max(0, lastI - p2.i);
        const recency = Math.max(0, 1 - age / 500);
        const spanScore = Math.min(10, gap / 35);
        const touchBonus = touches >= 3 ? 14 + Math.min(10, (touches - 3) * 2) : 0;
        const slopePenalty = absSlope > 0.28 ? (absSlope - 0.28) * 22 : 0;
        const score = touches * 10 + touchBonus + retests * 6 + prominence * 2.2
          + recency * 15 + spanScore - violations * 18 - slopePenalty;

        if (!best || score > best.score) {
          best = { p1, p2, slope, score, touches, retests, violations, prominence };
        }
      }
    }

    if (!best) return null;
    const tEnd = bars[bars.length - 1].time + 3;
    const endValue = best.p2.v + best.slope * (tEnd - best.p2.t);
    return {
      pts: [
        { time: best.p1.t, value: best.p1.v },
        { time: best.p2.t, value: best.p2.v },
        { time: tEnd, value: endValue },
      ],
      slope: best.slope,
      score: best.score,
      touches: best.touches,
      retests: best.retests,
      violations: best.violations,
      prominence: best.prominence,
    };
  }

  function mk(t, v, position, shape, color, text) {
    return { time: t, position, shape, color, text, size: 1 };
  }

  /* ---- pattern detection on recent bars ----
     Labels (readable):
       DT ▼  Double Top          — တန်းတူ ထိပ်၂ခု → ပြန်လှည့်ဖိုမ် (bearish)
       DB ▲  Double Bottom       — တန်းတူ အောက်ခြေ၂ခု → ပြန်တက်ဖိုမ် (bullish)
       HS ▼  Head & Shoulders    — ခေါင်းရှည် top → ဆင်းဖိုမ်
       IHS ▲ Inverse H&S         — ခေါင်းပြန် bottom → တက်ဖိုမ်
       BO ↑/↓ Breakout           — S/R level ဖြတ်ထွက်
       ▲×N / ▼×N Momentum run    — N ဆက်တိုက် တက်/ဆင်း */
  function detectPatterns(ph, pl, bars) {
    const marks = [];
    const n = bars.length;
    const from = Math.max(0, n - 450);
    const hh = ph.filter((p) => p.i >= from);
    const ll = pl.filter((p) => p.i >= from);

    /* ---- Double Top: equal highs + meaningful trough depth ---- */
    let lastDT = -1;
    for (let a = 1; a < hh.length; a++) {
      const q = hh[a], p = hh[a - 1];
      if (q.i - p.i < 4 || q.i - p.i > 90) continue;
      if (p.i <= lastDT) continue;                       // no overlapping patterns
      let trough = Infinity;
      for (let i = p.i; i <= q.i; i++) trough = Math.min(trough, bars[i].low);
      const height = Math.max(p.v, q.v) - trough;
      const tol = Math.max(PAT_TOL, height * 0.18);      // adaptive tolerance
      if (Math.abs(q.v - p.v) <= tol && height >= 2.5) {
        marks.push(mk(q.t, q.v, "aboveBar", "circle", "#ff9800", "DT ▼"));
        lastDT = q.i;
      }
    }
    /* ---- Double Bottom ---- */
    let lastDB = -1;
    for (let a = 1; a < ll.length; a++) {
      const q = ll[a], p = ll[a - 1];
      if (q.i - p.i < 4 || q.i - p.i > 90) continue;
      if (p.i <= lastDB) continue;
      let peak = -Infinity;
      for (let i = p.i; i <= q.i; i++) peak = Math.max(peak, bars[i].high);
      const depth = peak - Math.min(p.v, q.v);
      const tol = Math.max(PAT_TOL, depth * 0.18);
      if (Math.abs(q.v - p.v) <= tol && depth >= 2.5) {
        marks.push(mk(q.t, q.v, "belowBar", "circle", "#ff9800", "DB ▲"));
        lastDB = q.i;
      }
    }
    /* ---- Head & Shoulders: head margin + shoulder symmetry ---- */
    let lastHS = -1;
    for (let b = 1; b < hh.length - 1; b++) {
      const L = hh[b - 1], M = hh[b], R = hh[b + 1];
      if (R.i - L.i < 8 || R.i - L.i > 130) continue;
      if (M.i <= lastHS) continue;
      const margin = Math.max(1.0, (M.v - Math.min(L.v, R.v)) * 0.25);
      const dL = M.i - L.i, dR = R.i - M.i;
      if (M.v > L.v + margin && M.v > R.v + margin
          && Math.abs(L.v - R.v) <= PAT_TOL * 1.5
          && dL / dR >= 0.5 && dL / dR <= 2) {
        marks.push(mk(M.t, M.v, "aboveBar", "square", DOWN, "HS ▼"));
        lastHS = R.i;
      }
    }
    /* ---- Inverse Head & Shoulders ---- */
    let lastIHS = -1;
    for (let b = 1; b < ll.length - 1; b++) {
      const L = ll[b - 1], M = ll[b], R = ll[b + 1];
      if (R.i - L.i < 8 || R.i - L.i > 130) continue;
      if (M.i <= lastIHS) continue;
      const margin = Math.max(1.0, (Math.max(L.v, R.v) - M.v) * 0.25);
      const dL = M.i - L.i, dR = R.i - M.i;
      if (M.v < L.v - margin && M.v < R.v - margin
          && Math.abs(L.v - R.v) <= PAT_TOL * 1.5
          && dL / dR >= 0.5 && dL / dR <= 2) {
        marks.push(mk(M.t, M.v, "belowBar", "square", UP, "IHS ▲"));
        lastIHS = R.i;
      }
    }
    /* ---- NEW: Breakouts through confirmed S/R pivots ---- */
    const evts = [
      ...hh.map((p) => ({ ...p, kind: "H" })),
      ...ll.map((p) => ({ ...p, kind: "L" })),
    ].sort((a, b) => a.i - b.i);
    let ei = 0, res = null, sup = null, lastBo = -5;
    for (let i = Math.max(1, from); i < n; i++) {
      while (ei < evts.length && evts[ei].i <= i - PIVOT_K) {
        const e = evts[ei++];
        if (e.kind === "H") res = e; else sup = e;
      }
      const c = bars[i], pc = bars[i - 1].c;
      if (i - lastBo > 3) {
        if (res && pc <= res.v + 0.3 && c.c > res.v + 0.4) {
          marks.push(mk(c.time, c.h, "aboveBar", "arrowUp", UP, "BO ↑"));
          lastBo = i; res = null;
        } else if (sup && pc >= sup.v - 0.3 && c.c < sup.v - 0.4) {
          marks.push(mk(c.time, c.l, "belowBar", "arrowDown", DOWN, "BO ↓"));
          lastBo = i; sup = null;
        }
      }
    }
    /* ---- Momentum runs: mark END of run, require ≥4 to stay meaningful ---- */
    const three = [];
    const runStart = Math.max(2, n - 260);
    let rl = 0, rd = 0, rEnd = -1;
    const flushRun = () => {
      if (rl >= 4 && rEnd >= runStart) {
        const b = bars[rEnd];
        three.push(rd === 1
          ? mk(b.time, b.h, "aboveBar", "arrowUp", UP, `▲×${rl}`)
          : mk(b.time, b.l, "belowBar", "arrowDown", DOWN, `▼×${rl}`));
      }
    };
    for (let i = runStart; i < n; i++) {
      const dir = bars[i].c > bars[i].o ? 1 : -1;
      if (dir === rd) { rl++; rEnd = i; }
      else { flushRun(); rd = dir; rl = 1; rEnd = i; }
    }
    flushRun();

    // de-dup by time+text: structural patterns first (priority), then latest
    // breakouts/momentum that don't sit on top of a structural mark
    const seen = new Set();
    const clean = [];
    const pushMark = (m) => {
      const key = m.time + "|" + m.text;
      if (seen.has(key)) return false;
      seen.add(key);
      clean.push(m);
      return true;
    };
    marks.forEach(pushMark);                       // DT / DB / HS / IHS / BO priority
    const structTimes = clean.map((m) => m.time);
    let added = 0;
    for (let i = three.length - 1; i >= 0 && added < 12; i--) {
      const m = three[i];
      if (structTimes.some((t) => Math.abs(t - m.time) <= 2)) continue;
      if (pushMark(m)) added++;
    }
    clean.sort((a, b) => a.time - b.time);
    return clean;
  }

  /* ---- Auto Support / Resistance v2 --------------------------------------
     Adaptive clustering + touch/rejection/recency scoring + break/retest and
     support<->resistance role-flip detection. Display-only chart structure. */
  function srAdaptiveTolerance(bars) {
    const tail = bars.slice(-180);
    if (!tail.length) return 1.0;
    let rangeSum = 0;
    tail.forEach((b) => { rangeSum += Math.max(0.1, b.h - b.l); });
    const avgRange = rangeSum / tail.length;
    return Math.max(0.65, Math.min(2.4, avgRange * 1.15));
  }

  function srLevelStats(level, bars, tol) {
    let touches = 0, rejections = 0, lastTouch = -1, breaksUp = 0, breaksDown = 0;
    let lastBreakUp = -1, lastBreakDown = -1, retests = 0;
    for (let i = 1; i < bars.length; i++) {
      const b = bars[i], prev = bars[i - 1];
      const near = b.l <= level + tol && b.h >= level - tol;
      if (near) {
        touches++; lastTouch = i;
        const rejectUp = b.h >= level - tol && b.c < level - tol * 0.15;
        const rejectDown = b.l <= level + tol && b.c > level + tol * 0.15;
        if (rejectUp || rejectDown) rejections++;
      }
      if (prev.c <= level + tol * 0.2 && b.c > level + tol * 0.75) {
        breaksUp++; lastBreakUp = i;
      }
      if (prev.c >= level - tol * 0.2 && b.c < level - tol * 0.75) {
        breaksDown++; lastBreakDown = i;
      }
    }
    if (lastBreakUp >= 0) {
      for (let i = lastBreakUp + 1; i < bars.length; i++) {
        if (bars[i].l <= level + tol && bars[i].c >= level) { retests++; break; }
      }
    }
    if (lastBreakDown >= 0) {
      for (let i = lastBreakDown + 1; i < bars.length; i++) {
        if (bars[i].h >= level - tol && bars[i].c <= level) { retests++; break; }
      }
    }
    const age = lastTouch < 0 ? bars.length : bars.length - 1 - lastTouch;
    const recency = Math.max(0, 1 - age / 700);
    return { touches, rejections, lastTouch, breaksUp, breaksDown, lastBreakUp, lastBreakDown, retests, recency };
  }

  function srLevels(bars, maxLevels = 6) {
    const lim = bars.slice(-2500);
    if (lim.length < 25) return [];
    const close = lim[lim.length - 1].c;
    const tol = srAdaptiveTolerance(lim);
    const piv = findPivots(lim, Math.max(3, Math.min(6, Math.floor(lim.length / 60))));
    const pts = [
      ...piv.hi.map((p) => ({ v:p.v, i:p.i, kind:'H' })),
      ...piv.lo.map((p) => ({ v:p.v, i:p.i, kind:'L' })),
      ...lim.slice(-60).map((b, j) => ({ v:b.h, i:lim.length-60+j, kind:'H' })),
      ...lim.slice(-60).map((b, j) => ({ v:b.l, i:lim.length-60+j, kind:'L' })),
    ].filter((x) => Number.isFinite(x.v));
    if (!pts.length) return [];

    pts.sort((a,b)=>a.v-b.v);
    const clusters=[]; let cur=[pts[0]];
    for (let i=1;i<pts.length;i++) {
      const mean=cur.reduce((s,x)=>s+x.v,0)/cur.length;
      if (Math.abs(pts[i].v-mean)<=tol) cur.push(pts[i]);
      else { clusters.push(cur); cur=[pts[i]]; }
    }
    clusters.push(cur);

    const scored=clusters.map((cl)=>{
      const L=cl.reduce((s,x)=>s+x.v,0)/cl.length;
      const st=srLevelStats(L,lim,tol);
      const hiTouches=cl.filter(x=>x.kind==='H').length, loTouches=cl.filter(x=>x.kind==='L').length;
      let role=L<close?'S':'R'; let flipped=false;
      if (st.lastBreakUp>=0 && st.lastBreakUp>st.lastBreakDown && close>=L-tol*0.35) { role='S'; flipped=true; }
      if (st.lastBreakDown>=0 && st.lastBreakDown>st.lastBreakUp && close<=L+tol*0.35) { role='R'; flipped=true; }
      const sideQuality=role==='S'?loTouches:hiTouches;
      const score=st.touches*5 + st.rejections*4 + st.retests*9 + sideQuality*2.5 + st.recency*12 + (flipped?8:0) - (st.breaksUp+st.breaksDown)*1.5;
      const strength=score>=70?'STRONG':score>=42?'MEDIUM':'WEAK';
      return { L, c:st.touches, score, strength, role, flipped, retests:st.retests, rejections:st.rejections, tol };
    }).filter(x=>x.c>=2 || Math.abs(x.L-close)<=tol*2.5);

    const picked=[];
    for (const it of scored.sort((a,b)=>b.score-a.score)) {
      if (picked.every((p)=>Math.abs(p.L-it.L)>=Math.max(2.2,tol*1.6))) picked.push(it);
      if (picked.length>=maxLevels) break;
    }
    // Ensure one useful level on each side when available.
    if (!picked.some(x=>x.L<close)) {
      const q=scored.filter(x=>x.L<close).sort((a,b)=>Math.abs(close-a.L)-Math.abs(close-b.L))[0]; if(q)picked.push(q);
    }
    if (!picked.some(x=>x.L>=close)) {
      const q=scored.filter(x=>x.L>=close).sort((a,b)=>Math.abs(close-a.L)-Math.abs(close-b.L))[0]; if(q)picked.push(q);
    }
    return picked.sort((a,b)=>a.L-b.L).slice(0,maxLevels+2);
  }

  function drawSrLines(levels) {
    srLines.forEach((pl)=>{ try { candleSeries.removePriceLine(pl); } catch(e){} });
    srLines=[]; if(!opts.sr) return;
    levels.forEach((lv)=>{
      const isSup=(lv.role|| (lv.L<curBars[curBars.length-1].c?'S':'R'))==='S';
      const strong=lv.strength==='STRONG', medium=lv.strength==='MEDIUM';
      const alpha=strong?.88:medium?.68:.48;
      const color=isSup?`rgba(8,153,129,${alpha})`:`rgba(242,54,69,${alpha})`;
      const cls=strong?'●●●':medium?'●●':'●';
      const flip=lv.flipped?' FLIP':'';
      srLines.push(candleSeries.createPriceLine({
        price:lv.L, color,
        lineWidth: strong?2:1,
        lineStyle: strong?LightweightCharts.LineStyle.Solid:LightweightCharts.LineStyle.Dashed,
        axisLabelVisible:true,
        title:`${isSup?'S':'R'} ${cls}${flip} T${lv.c||0} Rj${lv.rejections||0}`,
      }));
    });
  }

  /* ================= signal markers (WIN/LOSS) ================= */
  function buildMarkers(log) {
    const markers = [];
    (log || []).forEach((e) => {
      // precise anchoring: FULL issue -> its bar (works on every TF)
      const t = curLabelMap instanceof Map
        ? curLabelMap.get(e.full_issue || "") ?? curLabelMap.get(e.issue)
        : undefined;
      if (t == null) return;
      const win = e.outcome === "WIN";
      const big = e.signal === "BIG";
      const small = e.signal === "SMALL";
      if (!big && !small) return;
      markers.push({
        time: t,
        position: big ? "belowBar" : "aboveBar",
        color: e.outcome === "" ? "#ff9800" : win ? WIN_C : LOSS_C,
        shape: big ? "arrowUp" : "arrowDown",
        text: `${big ? "B" : "S"}${e.outcome === "WIN" ? "✓" : e.outcome === "LOSS" ? "✗" : ""}`,
        size: 2,
      });
    });
    markers.sort((a, b) => a.time - b.time);
    return markers;
  }

  /* ================= legend ================= */
  function updateLegend(bar) {
    const ohlc = $("lg-ohlc");
    const chg = $("lg-chg");
    const tmEl = $("lg-time");
    if (!ohlc || !chg) return;
    if (!bar) { ohlc.innerHTML = ""; chg.textContent = ""; chg.className = "lg-chg"; if (tmEl) tmEl.textContent = ""; return; }
    const up = bar.c >= bar.o;
    const cls = up ? "green" : "red";
    const s = `<b class="${cls}">`;
    ohlc.innerHTML =
      `O ${s}${bar.o.toFixed(1)}</b>` +
      ` H ${s}${bar.h.toFixed(1)}</b>` +
      ` L ${s}${bar.l.toFixed(1)}</b>` +
      ` C ${s}${bar.c.toFixed(1)}</b>`;
    if (tmEl) {
      const tm = curTimes[bar.time - 1] || "";
      const hm = tm.length >= 16 ? tm.slice(11, 16) : tm;
      tmEl.textContent = hm ? `🕒 ${hm}` : "";
    }
    if (bar.o !== bar.c) {
      const pct = ((bar.c - bar.o) / bar.o) * 100;
      chg.textContent = `${pct >= 0 ? "+" : ""}${pct.toFixed(2)}%`;
      chg.className = "lg-chg " + cls;
    } else {
      chg.textContent = "";
      chg.className = "lg-chg";
    }
  }

  function updateRsiLegend(val) {
    const el = $("lg-rsi");
    const zEl = $("lg-rsi-zone");
    if (!el) return;
    if (val == null) { el.textContent = ""; el.className = ""; if (zEl) zEl.textContent = ""; return; }
    el.textContent = val.toFixed(1);
    el.className = val >= 70 ? "red" : val <= 30 ? "green" : "";
    if (zEl) {
      zEl.textContent = val >= 70 ? "OB" : val <= 30 ? "OS" : "NEUTRAL";
      zEl.className = "lg-rsi-zone " + (val >= 70 ? "red" : val <= 30 ? "green" : "");
    }
  }

  /* ================= chart creation ================= */
  function baseChartOptions(el, height) {
    return {
      width: el.clientWidth,
      height,
      layout: {
        background: { type: "solid", color: "transparent" },
        textColor: "#787b86",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: "rgba(42,46,57,.55)" },
        horzLines: { color: "rgba(42,46,57,.55)" },
      },
      rightPriceScale: { borderColor: "#2a2e39" },
      timeScale: { borderColor: "#2a2e39", visible: false },
      crosshair: {
        mode: LightweightCharts.CrosshairMode.Normal,
        vertLine: { color: "#9598a1", width: 1, style: LightweightCharts.LineStyle.LargeDashed, labelBackgroundColor: "#363a45" },
        horzLine: { color: "#9598a1", width: 1, style: LightweightCharts.LineStyle.LargeDashed, labelBackgroundColor: "#363a45" },
      },
    };
  }

  function init(container) {
    containerEl = container;
    chart = LightweightCharts.createChart(container, {
      ...baseChartOptions(container, container.clientHeight),
      watermark: {
        visible: true,
        text: "TRX / ROUND · 10-DAY",
        color: "rgba(209,212,220,0.04)",
        fontSize: 46,
        horzAlign: "center",
        vertAlign: "center",
      },
      rightPriceScale: {
        borderColor: "#2a2e39",
        scaleMargins: { top: 0.08, bottom: 0.07 },
      },
      timeScale: {
        borderColor: "#2a2e39",
        visible: true,
        rightOffset: 3,
        barSpacing: 7,
        minBarSpacing: 0.5,
        shiftVisibleRangeOnNewBar: false,
        ticksVisible: true,
        secondsVisible: false,
        tickMarkMaxCharacterLength: 5,
        tickMarkFormatter: (t) => {
          const tm = curTimes[t - 1] || "";
          const hm = tm.length >= 16 ? tm.slice(11, 16) : tm;
          return hm || curLabels[t - 1] || "";
        },
      },
      localization: {
        timeFormatter: (t) => {
          const lb = curLabels[t - 1] || "";
          const tm = curTimes[t - 1] || "";
          return [tm ? `🕒 ${tm}` : null, lb ? `Issue …${lb}` : null].filter(Boolean).join("\n") || "";
        },
      },
    });

    const fmt = { type: "price", precision: 1, minMove: 0.1 };

    candleSeries = chart.addCandlestickSeries({
      upColor: UP, downColor: DOWN, wickUpColor: UP, wickDownColor: DOWN,
      borderVisible: false, priceFormat: fmt,
    });

    areaSeries = chart.addAreaSeries({
      lineColor: "#2962ff",
      topColor: "rgba(41,98,255,.30)",
      bottomColor: "rgba(41,98,255,.02)",
      lineWidth: 2, priceFormat: fmt, visible: false,
    });

    emaFastSeries = chart.addLineSeries({
      color: "#ff9800", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, visible: opts.ema, priceFormat: fmt,
    });
    emaSlowSeries = chart.addLineSeries({
      color: "#9c27b0", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, visible: opts.ema, priceFormat: fmt,
    });
    emaLongSeries = chart.addLineSeries({
      color: "#00bcd4", lineWidth: 1.5, lineStyle: LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, visible: opts.ema, priceFormat: fmt,
    });

    bbUpperSeries = chart.addLineSeries({
      color: "rgba(41,98,255,.65)", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      visible: opts.bb, priceFormat: fmt,
    });
    bbMidSeries = chart.addLineSeries({
      color: "rgba(255,152,0,.45)", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      visible: opts.bb, priceFormat: fmt,
    });
    bbLowerSeries = chart.addLineSeries({
      color: "rgba(41,98,255,.65)", lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      visible: opts.bb, priceFormat: fmt,
    });

    tlResSeries = chart.addLineSeries({
      color: "rgba(242,54,69,.85)", lineWidth: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      visible: opts.tl, priceFormat: fmt,
    });
    tlSupSeries = chart.addLineSeries({
      color: "rgba(8,153,129,.85)", lineWidth: 2,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
      visible: opts.tl, priceFormat: fmt,
    });

    chart.subscribeCrosshairMove((param) => {
      if (!param.time) { updateLegend(curBars[curBars.length - 1]); return; }
      updateLegend(curBars[param.time - 1]);
    });

    new ResizeObserver(() => {
      if (!chart || !containerEl) return;
      chart.applyOptions({ width: containerEl.clientWidth, height: containerEl.clientHeight });
      if (rsiChart && rsiEl) rsiChart.applyOptions({ width: rsiEl.clientWidth, height: rsiEl.clientHeight });
      if (macdChart && macdEl) macdChart.applyOptions({ width: macdEl.clientWidth, height: macdEl.clientHeight });
      if (stochChart && stochEl) stochChart.applyOptions({ width: stochEl.clientWidth, height: stochEl.clientHeight });
    }).observe(container);

    initRsiPane();
    initMacdPane();
    initStochPane();
    syncRanges();
    bindToolbar();
    updateLegend(null);
  }

  function initStochPane() {
    stochEl = $("stoch-chart");
    if (!stochEl) return;
    stochChart = LightweightCharts.createChart(stochEl, {
      ...baseChartOptions(stochEl, stochEl.clientHeight),
      rightPriceScale: { borderColor: "#2a2e39", scaleMargins: { top: 0.12, bottom: 0.12 } },
    });
    stochKSeries = stochChart.addLineSeries({
      color: "#2962ff", lineWidth: 1.5, priceLineVisible: false, lastValueVisible: true,
    });
    stochDSeries = stochChart.addLineSeries({
      color: "#ff6d00", lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    [80, 20].forEach((lvl) => {
      stochKSeries.createPriceLine({
        price: lvl,
        color: lvl === 80 ? "rgba(242,54,69,.4)" : "rgba(8,153,129,.4)",
        lineWidth: 1, lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true, title: String(lvl),
      });
    });
    stochChart.subscribeCrosshairMove((param) => {
      const el = $("lg-stoch");
      if (!param.time) { if (el) { el.textContent = ""; el.className = ""; } return; }
      const d = param.seriesData.get(stochKSeries);
      if (el && d) {
        el.textContent = d.value.toFixed(1);
        el.className = d.value >= 80 ? "red" : d.value <= 20 ? "green" : "";
      }
    });
    applyStochVisibility();
  }

  function applyStochVisibility() {
    const pane = $("stoch-pane");
    if (pane) pane.classList.toggle("off", !opts.stoch);
    if (stochEl && stochChart) {
      stochChart.applyOptions({
        width: stochEl.clientWidth,
        height: stochEl.clientHeight,
        visible: opts.stoch,
      });
    }
  }

  function syncRanges() {
    // N-way visible-range sync (main <-> rsi <-> macd <-> stoch), feedback-guarded
    const charts = [chart, rsiChart, macdChart, stochChart].filter(Boolean);
    charts.forEach((src) => {
      src.timeScale().subscribeVisibleLogicalRangeChange((r) => {
        if (!r || rangeLock) return;
        rangeLock = true;
        try { charts.forEach((c) => { if (c !== src) c.timeScale().setVisibleLogicalRange(r); }); }
        catch (e) { /* noop */ }
        if (window.TRXDraw && window.TRXDraw.redraw) window.TRXDraw.redraw();
        rangeLock = false;
      });
    });
  }
  function initRsiPane() {
    rsiEl = $("rsi-chart");
    if (!rsiEl) return;
    rsiChart = LightweightCharts.createChart(rsiEl, {
      ...baseChartOptions(rsiEl, rsiEl.clientHeight),
      rightPriceScale: {
        borderColor: "#2a2e39",
        scaleMargins: { top: 0.12, bottom: 0.12 },
      },
    });
    rsiSeries = rsiChart.addLineSeries({
      color: "#b39ddb", lineWidth: 1.8,
      priceLineVisible: false, lastValueVisible: true,
    });
    [70, 30].forEach((lvl) => {
      rsiSeries.createPriceLine({
        price: lvl,
        color: lvl === 70 ? "rgba(242,54,69,.4)" : "rgba(8,153,129,.4)",
        lineWidth: 1,
        lineStyle: LightweightCharts.LineStyle.Dotted,
        axisLabelVisible: true,
        title: String(lvl),
      });
    });
    /* 50 midline — subtle reference */
    rsiSeries.createPriceLine({
      price: 50,
      color: "rgba(120,123,134,.3)",
      lineWidth: 1,
      lineStyle: LightweightCharts.LineStyle.Dotted,
      axisLabelVisible: false,
      title: "50",
    });
    rsiChart.subscribeCrosshairMove((param) => {
      if (!param.time) { updateRsiLegend(null); return; }
      const d = param.seriesData.get(rsiSeries);
      updateRsiLegend(d ? d.value : null);
    });

    applyRsiVisibility();
  }

  function initMacdPane() {
    macdEl = $("macd-chart");
    if (!macdEl) return;
    macdChart = LightweightCharts.createChart(macdEl, {
      ...baseChartOptions(macdEl, macdEl.clientHeight),
      rightPriceScale: {
        borderColor: "#2a2e39",
        scaleMargins: { top: 0.15, bottom: 0.15 },
      },
    });
    macdHistSeries = macdChart.addHistogramSeries({
      priceLineVisible: false, lastValueVisible: false,
      visible: opts.macd,
    });
    macdLineSeries = macdChart.addLineSeries({
      color: "#2962ff", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: true,
    });
    macdSigSeries = macdChart.addLineSeries({
      color: "#ff6d00", lineWidth: 1,
      priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    macdChart.subscribeCrosshairMove((param) => {
      const el = $("lg-macd");
      if (!param.time) { if (el) { el.textContent = ""; el.className = ""; } return; }
      const d = param.seriesData.get(macdLineSeries);
      if (el && d) {
        el.textContent = d.value.toFixed(2);
        el.className = d.value >= 0 ? "green" : "red";
      }
    });
    applyMacdVisibility();
  }

  function applyMacdVisibility() {
    const pane = $("macd-pane");
    if (pane) pane.classList.toggle("off", !opts.macd);
    if (macdEl && macdChart) {
      macdChart.applyOptions({
        width: macdEl.clientWidth,
        height: macdEl.clientHeight,
        visible: opts.macd,
      });
    }
  }

  function applyRsiVisibility() {
    const pane = $("rsi-pane");
    if (pane) pane.classList.toggle("off", !opts.rsi);
    if (rsiEl && rsiChart) {
      rsiChart.applyOptions({
        width: rsiEl.clientWidth,
        height: rsiEl.clientHeight,
        visible: opts.rsi,
      });
    }
  }

  /* ================= toolbar ================= */
  function bindToolbar() {
    document.querySelectorAll(".vm-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".vm-btn").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        viewMode = btn.dataset.v;
        refit();
        if (lastState) update(lastState, true);
      });
    });
    document.querySelectorAll(".tf-btn[data-g]").forEach((btn) => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".tf-btn[data-g]").forEach((b) => b.classList.remove("active"));
        btn.classList.add("active");
        group = parseInt(btn.dataset.g, 10) || 1;
        const tf = $("lg-tf");
        if (tf) tf.textContent = btn.textContent;
        refit();
        if (lastState) update(lastState, true);
      });
    });
    const activeTf = document.querySelector(".tf-btn.active[data-g]");
    if (activeTf) { const tf = $("lg-tf"); if (tf) tf.textContent = activeTf.textContent; }
    const fitBtn = $("fit-btn");
    if (fitBtn) fitBtn.addEventListener("click", () => {
      [chart, rsiChart, macdChart, stochChart].forEach((c) => {
        if (c) c.timeScale().fitContent();
      });
    });
    /* ---- zoom in / out / reset — visible logical range based, all panes synced ----
       (wheel/pinch zoom already works; these buttons do discrete steps) */
    const zoomStep = (mult) => {
      [chart, rsiChart, macdChart, stochChart].forEach((c) => {
        if (!c) return;
        try {
          const r = c.timeScale().getVisibleLogicalRange();
          if (!r) return;
          const mid = (r.from + r.to) / 2;
          const half = Math.max(8, ((r.to - r.from) / 2) * mult);
          c.timeScale().setVisibleLogicalRange({ from: mid - half, to: mid + half });
        } catch (e) { /* noop */ }
      });
    };
    const zinBtn = $("zoom-in-btn");
    const zoutBtn = $("zoom-out-btn");
    const zresetBtn = $("zoom-reset-btn");
    if (zinBtn) zinBtn.addEventListener("click", () => zoomStep(0.75));
    if (zoutBtn) zoutBtn.addEventListener("click", () => zoomStep(1.25));
    if (zresetBtn) zresetBtn.addEventListener("click", () => {
      [chart, rsiChart, macdChart, stochChart].forEach((c) => {
        if (c) c.timeScale().fitContent();
      });
    });
    const bindOpt = (id, key, after) => {
      const el = $(id);
      if (!el) return;
      opts[key] = el.checked;
      el.addEventListener("change", () => {
        opts[key] = el.checked;
        if (after) after();
        if (lastState) update(lastState, true);
      });
    };
    bindOpt("ema-toggle", "ema");
    bindOpt("bb-toggle", "bb");
    bindOpt("pat-toggle", "pat");
    bindOpt("sr-toggle", "sr");
    bindOpt("tl-toggle", "tl");
    bindOpt("rsi-toggle", "rsi", applyRsiVisibility);
    bindOpt("macd-toggle", "macd", applyMacdVisibility);
    bindOpt("stoch-toggle", "stoch", applyStochVisibility);
  }

  function refit() {
    fittedOnce = false;
    srRescanNeeded = true;   // re-cluster S/R for the new timeframe
  }

  function anchorRecent(n) {
    const span = Math.min(Math.max(Math.round(320 / group), 60), n);
    const range = { from: Math.max(1, n - span), to: n + 4 };
    [chart, rsiChart, macdChart, stochChart].forEach((c) => {
      if (!c) return;
      try { c.timeScale().setVisibleLogicalRange(range); } catch (e) { /* noop */ }
    });
  }

  /* ================= main update ================= */
  function update(s, force) {
    const wrap = $("tv-chart");
    if (!wrap) return;
    if (!chart) init(wrap);

    lastState = s;
    const hist = s.history || [];

    // skip rebuild when nothing changed
    const lastIssue = hist.length ? hist[hist.length - 1].issue : "";
    const key = `${hist.length}:${lastIssue}:${group}:${viewMode}:${JSON.stringify(opts)}:${(s.log || []).length}`;
    if (!force && key === lastKey) return;
    lastKey = key;

    // capture current view so setData() cannot scroll/zoom the chart
    const prevRange = (() => {
      try { return chart.timeScale().getVisibleLogicalRange(); } catch (e) { return null; }
    })();

    const { bars, labels, labelMap, times, fulls } = buildBars(hist);
    curBars = bars.map((b) => ({ time: b.time, o: b.open, h: b.high, l: b.low, c: b.close }));
    curLabels = labels;
    curTimes = times || [];
    curFulls = fulls || [];
    curLabelMap = labelMap;

    candleSeries.setData(bars);
    candleSeries.applyOptions({ visible: viewMode === "candles" });

    areaSeries.setData(linePoints(curBars.map((b) => b.c)));
    areaSeries.applyOptions({ visible: viewMode === "line" });

    const closes = curBars.map((b) => b.c);

    const emaFpts = linePoints(calcEma(closes, 5));
    const emaSpts = linePoints(calcEma(closes, 15));
    emaFastSeries.setData(emaFpts);
    emaSlowSeries.setData(emaSpts);
    emaLongSeries.setData(linePoints(calcEma(closes, 100)));
    emaFastSeries.applyOptions({ visible: opts.ema && viewMode !== "none" });
    emaSlowSeries.applyOptions({ visible: opts.ema });
    emaLongSeries.applyOptions({ visible: opts.ema });

    const bb = calcBB(closes, 20, 2);
    bbUpperSeries.setData(linePoints(bb.up));
    bbMidSeries.setData(linePoints(bb.mid));
    bbLowerSeries.setData(linePoints(bb.lo));
    bbUpperSeries.applyOptions({ visible: opts.bb });
    bbMidSeries.applyOptions({ visible: opts.bb });
    bbLowerSeries.applyOptions({ visible: opts.bb });

    // ---- structure: pivots -> trendlines -> patterns -> S/R ----
    // FIX: compute fractal pivots on a tail window only — full-history scans
    // (up to ~30k bars) made every refresh sluggish without adding signals.
    const TAIL = Math.min(curBars.length, 1500);
    const tailStart = curBars.length - TAIL;
    const tailBars = curBars.slice(tailStart);
    const pivRaw = findPivots(tailBars, PIVOT_K);
    const piv = {
      hi: pivRaw.hi.map((p) => ({ ...p, i: p.i + tailStart })),
      lo: pivRaw.lo.map((p) => ({ ...p, i: p.i + tailStart })),
    };
    const resSeg = trendSegV2(piv.hi, curBars, "res");
    const supSeg = trendSegV2(piv.lo, curBars, "sup");
    tlResSeries.setData(resSeg ? resSeg.pts : []);
    tlSupSeries.setData(supSeg ? supSeg.pts : []);
    tlResSeries.applyOptions({ visible: opts.tl });
    tlSupSeries.applyOptions({ visible: opts.tl });

    drawSrLines(opts.sr ? ensureSRLevels() : []);

    // push chart internals to manual drawing-tools overlay EARLY
    // (must never be skipped, even if a later step throws)
    if (window.TRXDraw && window.TRXDraw.onData) {
      try {
        window.TRXDraw.onData({
          chart, series: candleSeries,
          labels: curLabels, labelMap: curLabelMap,
          fulls: curFulls, bars: curBars, // drawing v2 OHLC magnet snap (display-only)
        });
      } catch (e) { /* noop */ }
    }

    // ---- markers: signals + patterns (sanitized — invalid time must never crash the chart) ----
    let markers = opts.sig ? buildMarkers(s.log) : [];
    if (opts.pat) {
      const pm = detectPatterns(piv.hi, piv.lo, curBars);
      markers = markers.concat(pm);
      markers.sort((a, b) => a.time - b.time);
    }
    markers = markers.filter((m) => m && typeof m.time === "number" && !isNaN(m.time));
    candleSeries.setMarkers(markers);
    areaSeries.setMarkers(markers);

    // ---- RSI sub-pane ----
    if (rsiSeries) {
      const rsiArr = calcRsi(closes, 14);
      rsiSeries.setData(linePoints(rsiArr));
      const lastRsi = [...rsiArr].reverse().find((v) => v != null);
      updateRsiLegend(lastRsi);
    }

    // ---- MACD sub-pane ----
    if (macdLineSeries) {
      const m = calcMacd(closes, 12, 26, 9);
      macdLineSeries.setData(linePoints(m.macd));
      macdSigSeries.setData(linePoints(m.signal));
      macdHistSeries.setData(m.hist.map((v, i) => v == null ? null : ({
        time: i + 1,
        value: v,
        color: v >= 0 ? "rgba(8,153,129,.55)" : "rgba(242,54,69,.5)",
      })).filter(Boolean));
      macdHistSeries.applyOptions({ visible: opts.macd });
      macdLineSeries.applyOptions({ visible: opts.macd });
      macdSigSeries.applyOptions({ visible: opts.macd });
    }

    // ---- Stochastic sub-pane ----
    if (stochKSeries) {
      const st = calcStoch(closes, 14, 3, 3);
      stochKSeries.setData(linePoints(st.k));
      stochDSeries.setData(linePoints(st.d));
      stochKSeries.applyOptions({ visible: opts.stoch });
      stochDSeries.applyOptions({ visible: opts.stoch });
    }

    // ---- view anchoring ----
    if (curBars.length > 5) {
      const bigJump = curBars.length - lastLen > 500;
      if (!fittedOnce || bigJump) {
        anchorRecent(curBars.length);
        fittedOnce = true;
      } else if (prevRange) {
        // restore exactly where the user was (prevents jump on every refresh)
        try {
          chart.timeScale().setVisibleLogicalRange(prevRange);
        } catch (e) { /* noop */ }
      }
    }
    lastLen = curBars.length;
    if (curBars.length) updateLegend(curBars[curBars.length - 1]);

    // structure summary chip in legend row
    const chip = $("lg-struct");
    if (chip) {
      const tags = [];
      if (resSeg && supSeg) {
        if (resSeg.slope < -0.04 && supSeg.slope > 0.04) tags.push("TRIANGLE ▽");
        else if (resSeg.slope > 0.04 && supSeg.slope > 0.04) tags.push("CHANNEL ▲");
        else if (resSeg.slope < -0.04 && supSeg.slope < -0.04) tags.push("CHANNEL ▼");
      }
      if (curBars.length > 30) {
        const diff = calcEma(closes, 5).at(-1) - calcEma(closes, 15).at(-1);
        tags.push(diff > 0 ? "TREND ▲" : "TREND ▼");
      }
      chip.textContent = tags.join(" · ");
      chip.className = "lg-struct" + (tags.length
        ? (/▲/.test(tags[tags.length - 1] || "") ? " green" : " red")
        : "");
    }
  }

  function drawSrLevels(levels) {
    drawSrLines(levels);
  }

  /* ---- public: Auto S/R button (rescan+show / hide toggle) ---- */
  function autoSR() {
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

  /* ---- ultra-fast 1m candle append ----
     /api/latest uses this path so a fresh result does not rebuild 10 days of
     candles/indicators just to paint one bar. The normal /api/state refresh
     follows shortly and performs the authoritative full indicator rebuild. */
  function appendLatest(row) {
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
    curLabels.push(row.short_issue || issue.slice(-6));
    curTimes.push(row.block_time || row.hm || "");
    curFulls.push(issue);
    if (!(curLabelMap instanceof Map)) curLabelMap = new Map();
    curLabelMap.set(issue, time);
    lastLen = curBars.length;
    updateLegend(curBars[curBars.length - 1]);

    if (window.TRXDraw && window.TRXDraw.onData) {
      try {
        window.TRXDraw.onData({
          chart, series: candleSeries, labels: curLabels,
          labelMap: curLabelMap, fulls: curFulls, bars: curBars,
        });
      } catch (e) { /* drawing overlay can wait for full refresh */ }
    }
    return true;
  }

  /* ---- public: signal arrows toggle ---- */
  function toggleSignals() {
    opts.sig = !opts.sig;
    const btn = $("sig-btn");
    if (btn) btn.classList.toggle("active", opts.sig);
    if (lastState) update(lastState, true);
    return opts.sig;
  }

  return {
    update, appendLatest, autoSR, toggleSignals,
    _view: () => {
      try { const r = chart.timeScale().getVisibleLogicalRange(); return { from: r.from, to: r.to }; }
      catch (e) { return null; }
    },
  };
})();
