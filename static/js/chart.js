/* TradingView-style chart (Lightweight Charts v4)
   Trend model: BIG -> +1 step, SMALL -> -1 step
   Features: Candles/Area · TF grouping ×1..×50 · EMA 5/15 · SMA 20/50 · Bollinger Bands
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
  let sma20Series = null;
  let sma50Series = null;
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
    ema: true, sma: false, bb: false, rsi: true, sig: false,
    pat: false, sr: false, tl: false, macd: false, stoch: false,
  };

  /* S/R level cache — levels must NOT drift on every data tick */
  let srLevelsCache = [];
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

  let curBars = [];           // [{time,o,h,l,c}]
  let curCloses = [];         // hot-path close cache; kept in lockstep with curBars
  let curLabels = [];
  let curTimes = [];          // real blockTime per bar (slot index -> "YYYY-MM-DD HH:MM:SS")
  let curFulls = [];          // per-slot FULL issue (drawing anchor)
  let curLabelMap = new Map();
  let fittedOnce = false;
  let lastLen = 0;
  let lastKey = "";
  let lastState = null;
  let rangeLock = false;
  let crosshairLock = false;
  let curRsiValues = [];
  let curMacdValues = [];
  let curStochValues = [];
  let liveInd = null;

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
    return { macd, signal, hist, emaFast: ef, emaSlow: es };
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

  function calcStoch(bars, period = 14, kSmooth = 3, dSmooth = 3) {
    // Standard Stochastic Oscillator: current close relative to the highest
    // HIGH / lowest LOW over the lookback. This replaces the old close-only
    // walk oscillator while preserving 14,3,3 smoothing.
    const raw = new Array(bars.length).fill(null);
    for (let i = period - 1; i < bars.length; i++) {
      let hh = -Infinity, ll = Infinity;
      for (let j = i - period + 1; j <= i; j++) {
        if (bars[j].h > hh) hh = bars[j].h;
        if (bars[j].l < ll) ll = bars[j].l;
      }
      const close = bars[i].c;
      raw[i] = hh === ll ? 50 : ((close - ll) / (hh - ll)) * 100;
    }
    const k = smaArr(raw, kSmooth);
    const d = smaArr(k, dSmooth);
    return { raw, k, d };
  }

  function seedLiveIndicators(closes, computed = null) {
    if (!closes.length) { liveInd = null; return; }
    const ema5 = computed?.ema5 || calcEma(closes, 5);
    const ema15 = computed?.ema15 || calcEma(closes, 15);
    const ema100 = computed?.ema100 || calcEma(closes, 100);
    const rsi = computed?.rsi || calcRsi(closes, 14);
    const macd = computed?.macd || calcMacd(closes, 12, 26, 9);
    const st = computed?.stoch || calcStoch(curBars, 14, 3, 3);

    // Wilder RSI state, seeded exactly like calcRsi().
    let ag = null, al = null;
    if (closes.length >= 15) {
      let g = 0, l = 0;
      for (let i = 1; i <= 14; i++) {
        const d = closes[i] - closes[i - 1];
        if (d > 0) g += d; else l -= d;
      }
      ag = g / 14; al = l / 14;
      for (let i = 15; i < closes.length; i++) {
        const d = closes[i] - closes[i - 1];
        ag = (ag * 13 + Math.max(d, 0)) / 14;
        al = (al * 13 + Math.max(-d, 0)) / 14;
      }
    }

    liveInd = {
      ema5: ema5.at(-1), ema15: ema15.at(-1), ema100: ema100.at(-1),
      ema12: macd.emaFast.at(-1), ema26: macd.emaSlow.at(-1),
      rsiAg: ag, rsiAl: al,
      macdSignal: macd.signal.at(-1),
      stochRaw: [], stochK: [],
      lastClose: closes.at(-1), count: closes.length,
    };
    liveInd.stochRaw = (st.raw || []).slice(-3).filter((v)=>v!=null);
    liveInd.stochK = st.k.slice(-3).filter((v)=>v!=null);
    curRsiValues = rsi.slice();
    curMacdValues = macd.macd.slice();
    curStochValues = st.k.slice();
  }

  function emaNext(prev, value, period, countBefore, closes) {
    if (countBefore + 1 < period) return null;
    if (countBefore + 1 === period) {
      const tail = closes.slice(-period);
      return tail.reduce((a,b)=>a+b,0)/period;
    }
    if (prev == null) return calcEma(closes, period).at(-1);
    const k=2/(period+1);
    return value*k + prev*(1-k);
  }

  function updateLiveIndicators(close, time) {
    if (!liveInd || group !== 1) return false;
    const closes = curCloses;
    const before = liveInd.count;
    const prevClose = liveInd.lastClose;

    liveInd.ema5 = emaNext(liveInd.ema5, close, 5, before, closes);
    liveInd.ema15 = emaNext(liveInd.ema15, close, 15, before, closes);
    liveInd.ema100 = emaNext(liveInd.ema100, close, 100, before, closes);
    liveInd.ema12 = emaNext(liveInd.ema12, close, 12, before, closes);
    liveInd.ema26 = emaNext(liveInd.ema26, close, 26, before, closes);

    if (liveInd.ema5 != null) emaFastSeries.update({time,value:liveInd.ema5});
    if (liveInd.ema15 != null) emaSlowSeries.update({time,value:liveInd.ema15});
    if (liveInd.ema100 != null) emaLongSeries.update({time,value:liveInd.ema100});

    // Bollinger Bands use SMA20 ± 2σ. Keep them in the same instant path as
    // the candle; O(20) work is tiny and avoids up to ~1.5s visual lag.
    if (closes.length >= 20) {
      const tail20 = closes.slice(-20);
      const mean20 = tail20.reduce((a,b)=>a+b,0) / 20;
      let var20 = 0;
      for (const v of tail20) var20 += (v - mean20) ** 2;
      const sd20 = Math.sqrt(var20 / 20);
      // SMA20 and BB middle are mathematically identical: compute once, fan out.
      sma20Series.update({time,value:mean20});
      bbUpperSeries.update({time,value:mean20 + 2 * sd20});
      bbMidSeries.update({time,value:mean20});
      bbLowerSeries.update({time,value:mean20 - 2 * sd20});
    }
    if (closes.length >= 50) {
      const tail50 = closes.slice(-50);
      const mean50 = tail50.reduce((a,b)=>a+b,0) / 50;
      sma50Series.update({time,value:mean50});
    }

    let rsiVal=null;
    if (before >= 14 && liveInd.rsiAg != null && liveInd.rsiAl != null) {
      const d=close-prevClose;
      liveInd.rsiAg=(liveInd.rsiAg*13+Math.max(d,0))/14;
      liveInd.rsiAl=(liveInd.rsiAl*13+Math.max(-d,0))/14;
      rsiVal=liveInd.rsiAl===0?100:100-100/(1+liveInd.rsiAg/liveInd.rsiAl);
    }
    curRsiValues.push(rsiVal);
    if (rsiVal!=null && rsiSeries) rsiSeries.update({time,value:rsiVal});
    if (opts.rsi) updateRsiLegend(rsiVal);

    let macdVal=null, sigVal=null, histVal=null;
    if (liveInd.ema12!=null && liveInd.ema26!=null) {
      macdVal=liveInd.ema12-liveInd.ema26;
      const k=2/10;
      liveInd.macdSignal=liveInd.macdSignal==null?macdVal:macdVal*k+liveInd.macdSignal*(1-k);
      sigVal=liveInd.macdSignal; histVal=macdVal-sigVal;
    }
    curMacdValues.push(macdVal);
    if (macdVal!=null && macdLineSeries) macdLineSeries.update({time,value:macdVal});
    if (sigVal!=null && macdSigSeries) macdSigSeries.update({time,value:sigVal});
    if (histVal!=null && macdHistSeries) macdHistSeries.update({time,value:histVal,color:histVal>=0?'rgba(8,153,129,.55)':'rgba(242,54,69,.5)'});
    if (opts.macd) updateMacdLegend(macdVal);

    let raw=null,kVal=null,dVal=null;
    if (curBars.length>=14) {
      const tail=curBars.slice(-14);
      const hh=Math.max(...tail.map((b)=>b.h)), ll=Math.min(...tail.map((b)=>b.l));
      raw=hh===ll?50:((close-ll)/(hh-ll))*100;
      liveInd.stochRaw.push(raw); if(liveInd.stochRaw.length>3)liveInd.stochRaw.shift();
      if(liveInd.stochRaw.length===3) kVal=liveInd.stochRaw.reduce((a,b)=>a+b,0)/3;
      if(kVal!=null){ liveInd.stochK.push(kVal); if(liveInd.stochK.length>3)liveInd.stochK.shift(); }
      if(liveInd.stochK.length===3) dVal=liveInd.stochK.reduce((a,b)=>a+b,0)/3;
    }
    curStochValues.push(kVal);
    if(kVal!=null && stochKSeries) stochKSeries.update({time,value:kVal});
    if(dVal!=null && stochDSeries) stochDSeries.update({time,value:dVal});
    if(opts.stoch) updateStochLegend(kVal);

    liveInd.lastClose=close; liveInd.count=before+1;
    return true;
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
  function structuralLookbackBars(available, tfMinutes = group) {
    const tf = Math.max(1, Number(tfMinutes) || 1);
    // 1m: use 3 days (4,320 bars) to deepen structure context without
    // rescanning all ~14,400 ten-day bars every authoritative refresh.
    // 5m/15m/1h: the full 10-day buffer is small enough to analyze directly.
    const days = tf === 1 ? 3 : 10;
    const wanted = Math.ceil(days * 1440 / tf);
    return Math.max(0, Math.min(Number(available) || 0, wanted));
  }

  function structureScale(bars, lookback = 180) {
    const tail = (bars || []).slice(-lookback);
    if (!tail.length) return 1.0;
    const ranges = tail.map((b) => Math.max(0.1, Number(b.h) - Number(b.l)))
      .filter((v) => Number.isFinite(v)).sort((a,b)=>a-b);
    if (!ranges.length) return 1.0;
    // Median is deliberately used instead of mean so one unusually long candle
    // cannot inflate every structural threshold on higher timeframes.
    const m = Math.floor(ranges.length / 2);
    const med = ranges.length % 2 ? ranges[m] : (ranges[m-1] + ranges[m]) / 2;
    return Math.max(0.75, Math.min(8.0, med));
  }

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
    const scale = structureScale(bars);
    const touchTol = Math.max(0.8, Math.min(4.8, scale * 0.8));
    const hardBreak = Math.max(1.35, Math.min(8.0, scale * 1.35));
    const maxAbsSlope = Math.max(0.5, Math.min(3.0, scale * 0.5));
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
        if (absSlope > maxAbsSlope) continue; // normalized to current timeframe range

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
  function clampScore(v) { return Math.max(0, Math.min(100, Math.round(v))); }
  function patternMark(t, v, position, shape, color, code, score, confirmed=true) {
    const c = clampScore(score);
    const flag = confirmed ? "✓" : "?";
    return mk(t, v, position, shape, color, `${code}${flag} ${c}%`);
  }
  function minLowBetween(bars, a, b) {
    let v = Infinity, idx = -1;
    for (let i = Math.max(0,a); i <= Math.min(bars.length-1,b); i++) {
      if (bars[i].l < v) { v = bars[i].l; idx = i; }
    }
    return { v, i: idx };
  }
  function maxHighBetween(bars, a, b) {
    let v = -Infinity, idx = -1;
    for (let i = Math.max(0,a); i <= Math.min(bars.length-1,b); i++) {
      if (bars[i].h > v) { v = bars[i].h; idx = i; }
    }
    return { v, i: idx };
  }
  function firstCloseBreak(bars, from, to, level, dir, clear) {
    for (let i = Math.max(1,from); i <= Math.min(bars.length-1,to); i++) {
      const prev = bars[i-1].c, cur = bars[i].c;
      if (dir < 0 && prev >= level-clear*.25 && cur < level-clear) return i;
      if (dir > 0 && prev <= level+clear*.25 && cur > level+clear) return i;
    }
    return -1;
  }
  function breakoutOutcome(bars, breakI, level, dir, tol) {
    let retestI=-1, failedI=-1, continuation=0;
    const end=Math.min(bars.length-1, breakI+8);
    for(let i=breakI+1;i<=end;i++){
      const b=bars[i];
      if(dir>0){
        if(b.l<=level+tol && b.c>=level-tol*.15 && retestI<0) retestI=i;
        if(b.c<level-tol*.55){failedI=i;break;}
        if(b.c>level+tol*.8) continuation++;
      }else{
        if(b.h>=level-tol && b.c<=level+tol*.15 && retestI<0) retestI=i;
        if(b.c>level+tol*.55){failedI=i;break;}
        if(b.c<level-tol*.8) continuation++;
      }
    }
    return {retestI,failedI,continuation,confirmed:failedI<0&&(retestI>=0||continuation>=2)};
  }

  /* ---- Pattern Engine v2 --------------------------------------------------
     Structural patterns require neckline/level confirmation before receiving a
     confirmed badge. Scores combine symmetry, swing depth, recency and break
     quality. Breakouts are classified as confirmed/retested or failed instead
     of treating every close through a pivot as equally valid. */
  function detectPatterns(ph, pl, bars) {
    const marks = [];
    const n = bars.length;
    if (n < 12) return marks;
    const scale = structureScale(bars);
    const patternTol = Math.max(PAT_TOL, Math.min(5.0, scale * 0.75));
    const minSwing = Math.max(2.5, scale * 2.0);
    const breakoutNear = Math.max(0.3, Math.min(2.5, scale * 0.25));
    const breakoutClear = Math.max(0.4, Math.min(3.5, scale * 0.45));
    const from = Math.max(0, n - structuralLookbackBars(n));
    const hh = ph.filter((p) => p.i >= from);
    const ll = pl.filter((p) => p.i >= from);
    const recencyScore = (i) => Math.max(0, 12 - (n-1-i)/35);

    /* Double Top — second top is only confirmed after neckline close break. */
    let lastDT=-1;
    for(let a=1;a<hh.length;a++){
      const p=hh[a-1], q=hh[a];
      const span=q.i-p.i;
      if(span<5||span>100||p.i<=lastDT)continue;
      const neck=minLowBetween(bars,p.i,q.i);
      const height=Math.max(p.v,q.v)-neck.v;
      const tol=Math.max(patternTol,height*.16);
      const symmetry=Math.max(0,1-Math.abs(q.v-p.v)/Math.max(tol,0.01));
      if(Math.abs(q.v-p.v)>tol||height<minSwing)continue;
      const br=firstCloseBreak(bars,q.i+1,q.i+35,neck.v,-1,breakoutClear*.65);
      const breakQuality=br>=0?Math.min(20,Math.max(0,(neck.v-bars[br].c)/Math.max(scale,.1))*8+10):0;
      const score=48+symmetry*18+Math.min(14,height/Math.max(scale,.1)*3)+breakQuality+recencyScore(q.i);
      const confirmed=br>=0;
      if(confirmed||q.i>=n-18){
        const t=confirmed?bars[br].time:q.t, v=confirmed?bars[br].l:q.v;
        marks.push(patternMark(t,v,confirmed?"belowBar":"aboveBar","circle","#ff9800","DT",score,confirmed));
        lastDT=q.i;
      }
    }

    /* Double Bottom — mirror of Double Top. */
    let lastDB=-1;
    for(let a=1;a<ll.length;a++){
      const p=ll[a-1], q=ll[a];
      const span=q.i-p.i;
      if(span<5||span>100||p.i<=lastDB)continue;
      const neck=maxHighBetween(bars,p.i,q.i);
      const depth=neck.v-Math.min(p.v,q.v);
      const tol=Math.max(patternTol,depth*.16);
      const symmetry=Math.max(0,1-Math.abs(q.v-p.v)/Math.max(tol,0.01));
      if(Math.abs(q.v-p.v)>tol||depth<minSwing)continue;
      const br=firstCloseBreak(bars,q.i+1,q.i+35,neck.v,1,breakoutClear*.65);
      const breakQuality=br>=0?Math.min(20,Math.max(0,(bars[br].c-neck.v)/Math.max(scale,.1))*8+10):0;
      const score=48+symmetry*18+Math.min(14,depth/Math.max(scale,.1)*3)+breakQuality+recencyScore(q.i);
      const confirmed=br>=0;
      if(confirmed||q.i>=n-18){
        const t=confirmed?bars[br].time:q.t, v=confirmed?bars[br].h:q.v;
        marks.push(patternMark(t,v,confirmed?"aboveBar":"belowBar","circle","#ff9800","DB",score,confirmed));
        lastDB=q.i;
      }
    }

    /* Head & Shoulders — shoulder symmetry + two neckline troughs + break. */
    let lastHS=-1;
    for(let b=1;b<hh.length-1;b++){
      const L=hh[b-1],M=hh[b],R=hh[b+1];
      if(R.i-L.i<10||R.i-L.i>150||M.i<=lastHS)continue;
      const leftNeck=minLowBetween(bars,L.i,M.i), rightNeck=minLowBetween(bars,M.i,R.i);
      const neck=(leftNeck.v+rightNeck.v)/2;
      const shoulderTol=Math.max(patternTol,scale*.9);
      const headLift=M.v-Math.max(L.v,R.v);
      const spacingRatio=(M.i-L.i)/Math.max(1,R.i-M.i);
      const shoulderSym=Math.max(0,1-Math.abs(L.v-R.v)/Math.max(shoulderTol,.1));
      const spacingSym=Math.max(0,1-Math.abs(1-spacingRatio)/1.2);
      if(headLift<Math.max(scale*.8,minSwing*.25)||Math.abs(L.v-R.v)>shoulderTol*1.6||spacingRatio<.45||spacingRatio>2.2)continue;
      const br=firstCloseBreak(bars,R.i+1,R.i+40,neck,-1,breakoutClear*.7);
      const score=50+shoulderSym*13+spacingSym*10+Math.min(12,headLift/Math.max(scale,.1)*5)+(br>=0?18:0)+recencyScore(R.i);
      const confirmed=br>=0;
      if(confirmed||R.i>=n-20){
        marks.push(patternMark(confirmed?bars[br].time:M.t,confirmed?bars[br].l:M.v,confirmed?"belowBar":"aboveBar","square",DOWN,"HS",score,confirmed));
        lastHS=R.i;
      }
    }

    /* Inverse Head & Shoulders. */
    let lastIHS=-1;
    for(let b=1;b<ll.length-1;b++){
      const L=ll[b-1],M=ll[b],R=ll[b+1];
      if(R.i-L.i<10||R.i-L.i>150||M.i<=lastIHS)continue;
      const leftNeck=maxHighBetween(bars,L.i,M.i), rightNeck=maxHighBetween(bars,M.i,R.i);
      const neck=(leftNeck.v+rightNeck.v)/2;
      const shoulderTol=Math.max(patternTol,scale*.9);
      const headDrop=Math.min(L.v,R.v)-M.v;
      const spacingRatio=(M.i-L.i)/Math.max(1,R.i-M.i);
      const shoulderSym=Math.max(0,1-Math.abs(L.v-R.v)/Math.max(shoulderTol,.1));
      const spacingSym=Math.max(0,1-Math.abs(1-spacingRatio)/1.2);
      if(headDrop<Math.max(scale*.8,minSwing*.25)||Math.abs(L.v-R.v)>shoulderTol*1.6||spacingRatio<.45||spacingRatio>2.2)continue;
      const br=firstCloseBreak(bars,R.i+1,R.i+40,neck,1,breakoutClear*.7);
      const score=50+shoulderSym*13+spacingSym*10+Math.min(12,headDrop/Math.max(scale,.1)*5)+(br>=0?18:0)+recencyScore(R.i);
      const confirmed=br>=0;
      if(confirmed||R.i>=n-20){
        marks.push(patternMark(confirmed?bars[br].time:M.t,confirmed?bars[br].h:M.v,confirmed?"aboveBar":"belowBar","square",UP,"IHS",score,confirmed));
        lastIHS=R.i;
      }
    }

    /* Breakout / retest / failed-break classification. */
    const evts=[...hh.map(p=>({...p,kind:"H"})),...ll.map(p=>({...p,kind:"L"}))].sort((a,b)=>a.i-b.i);
    let ei=0,res=null,sup=null,lastBo=-10;
    for(let i=Math.max(1,from);i<n;i++){
      while(ei<evts.length&&evts[ei].i<=i-PIVOT_K){const e=evts[ei++];if(e.kind==="H")res=e;else sup=e;}
      if(i-lastBo<=3)continue;
      const c=bars[i],pc=bars[i-1].c;
      let level=null,dir=0;
      if(res&&pc<=res.v+breakoutNear&&c.c>res.v+breakoutClear){level=res.v;dir=1;res=null;}
      else if(sup&&pc>=sup.v-breakoutNear&&c.c<sup.v-breakoutClear){level=sup.v;dir=-1;sup=null;}
      if(!dir)continue;
      const out=breakoutOutcome(bars,i,level,dir,Math.max(patternTol*.55,scale*.45));
      const distance=Math.abs(c.c-level)/Math.max(scale,.1);
      const baseScore=55+Math.min(18,distance*12)+Math.min(12,out.continuation*5)+(out.retestI>=0?12:0)+recencyScore(i);
      if(out.failedI>=0){
        const fb=bars[out.failedI];
        marks.push(patternMark(fb.time,dir>0?fb.h:fb.l,dir>0?"aboveBar":"belowBar",dir>0?"arrowDown":"arrowUp",dir>0?DOWN:UP,dir>0?"FB↓":"FB↑",Math.max(58,baseScore-18),true));
      }else{
        const code=out.retestI>=0?(dir>0?"BO+RT↑":"BO+RT↓"):(dir>0?"BO↑":"BO↓");
        marks.push(patternMark(c.time,dir>0?c.h:c.l,dir>0?"aboveBar":"belowBar",dir>0?"arrowUp":"arrowDown",dir>0?UP:DOWN,code,baseScore,out.confirmed));
      }
      lastBo=i;
    }

    /* Momentum runs — retain simple sequence context but score by run length. */
    const momentum=[];
    const runStart=Math.max(2,n-260);
    let rl=0,rd=0,rEnd=-1;
    const flushRun=()=>{
      if(rl>=4&&rEnd>=runStart){
        const b=bars[rEnd],score=clampScore(52+Math.min(36,(rl-4)*7)+recencyScore(rEnd));
        momentum.push(patternMark(b.time,rd===1?b.h:b.l,rd===1?"aboveBar":"belowBar",rd===1?"arrowUp":"arrowDown",rd===1?UP:DOWN,rd===1?`MOM↑×${rl}`:`MOM↓×${rl}`,score,true));
      }
    };
    for(let i=runStart;i<n;i++){
      const dir=bars[i].c>bars[i].o?1:bars[i].c<bars[i].o?-1:0;
      if(dir===0){flushRun();rd=0;rl=0;rEnd=-1;continue;}
      if(dir===rd){rl++;rEnd=i;}else{flushRun();rd=dir;rl=1;rEnd=i;}
    }
    flushRun();

    // De-dup and avoid hiding structural signals under momentum markers.
    const seen=new Set(),clean=[];
    const pushMark=(m)=>{const key=m.time+"|"+m.text.replace(/\s\d+%$/,'');if(seen.has(key))return false;seen.add(key);clean.push(m);return true;};
    marks.filter(m=>{const q=Number((m.text.match(/(\d+)%$/)||[])[1]||0);return q>=55;}).forEach(pushMark);
    const structTimes=clean.map(m=>m.time);
    let added=0;
    for(let i=momentum.length-1;i>=0&&added<10;i--){const m=momentum[i];if(structTimes.some(t=>Math.abs(t-m.time)<=2))continue;if(pushMark(m))added++;}
    clean.sort((a,b)=>a.time-b.time);
    return clean;
  }

  /* ---- Auto Support / Resistance v2 --------------------------------------
     Adaptive clustering + touch/rejection/recency scoring + break/retest and
     support<->resistance role-flip detection. Display-only chart structure. */
  function srAdaptiveTolerance(bars) {
    const scale = structureScale(bars, 180);
    return Math.max(0.65, Math.min(6.0, scale * 1.15));
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
    const lim = bars.slice(-structuralLookbackBars(bars.length));
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
      if (picked.every((p)=>Math.abs(p.L-it.L)>=Math.max(1.6,tol*1.6))) picked.push(it);
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

  function updateMacdLegend(val) {
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
      { chart, series: candleSeries, values: curCloses, enabled: true },
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
        minBarSpacing: 0.02,
        shiftVisibleRangeOnNewBar: true,
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

    sma20Series = chart.addLineSeries({
      color: "#e91e63", lineWidth: 1.5,
      priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, visible: opts.sma, priceFormat: fmt,
    });
    sma50Series = chart.addLineSeries({
      color: "#ffd54f", lineWidth: 1.5, lineStyle: LightweightCharts.LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, visible: opts.sma, priceFormat: fmt,
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


    let resizeRaf = 0;
    new ResizeObserver(() => {
      if (resizeRaf) return;
      resizeRaf = requestAnimationFrame(() => {
        resizeRaf = 0;
        if (!chart || !containerEl) return;
        chart.applyOptions({ width: containerEl.clientWidth, height: containerEl.clientHeight });
        if (rsiChart && rsiEl) rsiChart.applyOptions({ width: rsiEl.clientWidth, height: rsiEl.clientHeight });
        if (macdChart && macdEl) macdChart.applyOptions({ width: macdEl.clientWidth, height: macdEl.clientHeight });
        if (stochChart && stochEl) stochChart.applyOptions({ width: stochEl.clientWidth, height: stochEl.clientHeight });
      });
    }).observe(container);

    initRsiPane();
    initMacdPane();
    initStochPane();
    syncRanges();
    syncCrosshairs();
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

  let drawRedrawRaf = 0;
  function scheduleDrawRedraw() {
    if (drawRedrawRaf || !window.TRXDraw || !window.TRXDraw.redraw) return;
    drawRedrawRaf = requestAnimationFrame(() => {
      drawRedrawRaf = 0;
      try { window.TRXDraw.redraw(); } catch (e) { /* noop */ }
    });
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
        scheduleDrawRedraw();
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
    const historyRangeSelect = $("history-range-select");
    if (historyRangeSelect) {
      historyRangeSelect.addEventListener("change", () => {
        setHistoryRange(Number(historyRangeSelect.value) || 10);
      });
    }
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
    bindOpt("sma-toggle", "sma");
    bindOpt("bb-toggle", "bb");
    bindOpt("pat-toggle", "pat");
    bindOpt("sr-toggle", "sr", syncSrControls);
    bindOpt("tl-toggle", "tl");
    bindOpt("rsi-toggle", "rsi", applyRsiVisibility);
    bindOpt("macd-toggle", "macd", applyMacdVisibility);
    bindOpt("stoch-toggle", "stoch", applyStochVisibility);
  }

  function refit() {
    fittedOnce = false;
    srRescanNeeded = true;   // re-cluster S/R for the new timeframe
  }

  function setHistoryRange(days = 10) {
    const n = curBars.length;
    if (!n) return false;
    const wanted = Math.max(1, Math.ceil((Number(days) || 10) * 1440 / Math.max(1, group)));
    const from = Math.max(1, n - wanted + 1);
    const range = { from, to: n + 4 };
    [chart, rsiChart, macdChart, stochChart].forEach((c) => {
      if (!c) return;
      try { c.timeScale().setVisibleLogicalRange(range); } catch (e) { /* noop */ }
    });
    return true;
  }

  function anchorRecent() {
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
    const tailFingerprint = hist.slice(-3).map((r) =>
      `${r.issue || ""}/${r.number ?? ""}/${r.type || ""}/${r.block_time || r.blockTime || r.hm || ""}`
    ).join("|");
    const key = `${hist.length}:${lastIssue}:${tailFingerprint}:${group}:${viewMode}:${JSON.stringify(opts)}:${(s.log || []).length}`;
    if (!force && key === lastKey) return;
    lastKey = key;

    // capture current view so setData() cannot scroll/zoom the chart
    const prevRange = (() => {
      try { return chart.timeScale().getVisibleLogicalRange(); } catch (e) { return null; }
    })();

    const { bars, labels, labelMap, times, fulls } = buildBars(hist);
    curBars = bars.map((b) => ({ time: b.time, o: b.open, h: b.high, l: b.low, c: b.close }));
    curCloses = curBars.map((b) => b.c);
    curLabels = labels;
    curTimes = times || [];
    curFulls = fulls || [];
    curLabelMap = labelMap;

    candleSeries.setData(bars);
    candleSeries.applyOptions({ visible: viewMode === "candles" });

    areaSeries.setData(linePoints(curCloses));
    areaSeries.applyOptions({ visible: viewMode === "line" });

    const closes = curCloses;
    const ema5 = calcEma(closes, 5);
    const ema15 = calcEma(closes, 15);
    const ema100 = calcEma(closes, 100);
    const sma20 = smaArr(closes, 20);
    const sma50 = smaArr(closes, 50);
    const rsiArr = calcRsi(closes, 14);
    const macdCalc = calcMacd(closes, 12, 26, 9);
    const stochCalc = calcStoch(curBars, 14, 3, 3);
    seedLiveIndicators(closes, { ema5, ema15, ema100, rsi: rsiArr, macd: macdCalc, stoch: stochCalc });

    emaFastSeries.setData(linePoints(ema5));
    emaSlowSeries.setData(linePoints(ema15));
    emaLongSeries.setData(linePoints(ema100));
    emaFastSeries.applyOptions({ visible: opts.ema && viewMode !== "none" });
    emaSlowSeries.applyOptions({ visible: opts.ema });
    emaLongSeries.applyOptions({ visible: opts.ema });

    sma20Series.setData(linePoints(sma20));
    sma50Series.setData(linePoints(sma50));
    sma20Series.applyOptions({ visible: opts.sma });
    sma50Series.applyOptions({ visible: opts.sma });

    const bb = calcBB(closes, 20, 2);
    bbUpperSeries.setData(linePoints(bb.up));
    // BB middle === SMA20; reuse the already-computed SMA20 array.
    bbMidSeries.setData(linePoints(sma20));
    bbLowerSeries.setData(linePoints(bb.lo));
    bbUpperSeries.applyOptions({ visible: opts.bb });
    bbMidSeries.applyOptions({ visible: opts.bb });
    bbLowerSeries.applyOptions({ visible: opts.bb });

    // ---- structure: pivots -> trendlines -> patterns -> S/R ----
    // Analysis Integrity v2: adaptive structural window. 1m uses the latest
    // 3 days; higher timeframes can safely use the full 10-day chart buffer.
    const TAIL = structuralLookbackBars(curBars.length);
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
      curRsiValues = rsiArr.slice();
      rsiSeries.setData(linePoints(rsiArr));
      const lastRsi = [...rsiArr].reverse().find((v) => v != null);
      updateRsiLegend(lastRsi);
    }

    // ---- MACD sub-pane ----
    if (macdLineSeries) {
      const m = macdCalc;
      curMacdValues = m.macd.slice();
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
      const st = stochCalc;
      curStochValues = st.k.slice();
      stochKSeries.setData(linePoints(st.k));
      stochDSeries.setData(linePoints(st.d));
      stochKSeries.applyOptions({ visible: opts.stoch });
      stochDSeries.applyOptions({ visible: opts.stoch });
    }

    // ---- view anchoring ----
    if (curBars.length > 5) {
      const bigJump = curBars.length - lastLen > 500;
      if (!fittedOnce || bigJump) {
        anchorRecent();
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
        const diff = (ema5.at(-1) ?? 0) - (ema15.at(-1) ?? 0);
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
  function syncSrControls() {
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

  /* ---- ultra-fast 1m candle + indicator append ----
     /api/latest updates the fresh candle plus EMA/RSI/MACD/Stoch immediately.
     The normal /api/state refresh remains the authoritative full reconciliation. */
  function appendLatest(row) {
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
        const m = s.match(/(?:^|\s)(\d{1,2}):(\d{2})(?::\d{2})?$/);
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
    update, appendLatest, autoSR, toggleSignals, setHistoryRange,
    _view: () => {
      try { const r = chart.timeScale().getVisibleLogicalRange(); return { from: r.from, to: r.to }; }
      catch (e) { return null; }
    },
    _qa: { calcStoch, structuralLookbackBars },
  };
})();
