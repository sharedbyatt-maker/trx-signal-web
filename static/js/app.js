const $ = (id) => document.getElementById(id);
const fmtInt = (n) => n.toLocaleString("en-US");

/* ================= 10-day full history buffer ================= */
let fullRows = [];            // from /api/history ([issue, number, blockTime] tuples)
let lastHistFetch = 0;
let mergedCount = 0;
let lastResultTime = "";      // server-reported blockTime of the newest round
const HIST_REFETCH_MS = 45000;

function mergeRows(a, b) {
  const m = new Map();
  (a || []).forEach((r) => m.set(r.issue, r));
  // Newer/server-authoritative copies win. This also lets corrected historical
  // rows replace stale browser copies instead of being silently masked.
  (b || []).forEach((r) => m.set(r.issue, r));
  return [...m.values()].sort((x, y) => (x.issue < y.issue ? -1 : x.issue > y.issue ? 1 : 0));
}

async function fetchFullHistory(force) {
  if (!force && Date.now() - lastHistFetch < HIST_REFETCH_MS) return;
  lastHistFetch = Date.now();
  try {
    /* incremental sync: only rounds newer than what we already hold */
    const since = (!force && fullRows.length)
      ? `?since=${encodeURIComponent(fullRows[fullRows.length - 1].issue)}`
      : "";
    const r = await fetch("/api/history" + since, { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const data = await r.json();
    const inc = (data.history || []).map(([issue, number, btime]) => ({
      issue: String(issue),
      short_issue: String(issue).slice(-6),
      number,
      block_time: btime ? String(btime) : "",
      type: number >= 5 ? "BIG" : "SMALL",
    }));
    if (inc.length) {
      // A forced fetch is a fresh authoritative 10-day snapshot, not an append.
      // Incremental fetches append/replace by issue.
      fullRows = force ? mergeRows([], inc) : mergeRows(fullRows, inc);
      if (fullRows.length > 30000) fullRows = fullRows.slice(-30000);
    } else {
      // Initial page load can beat the background engine. Do not lock the chart
      // into the small /api/state fallback for 45 seconds; allow the next refresh
      // to retry the full history immediately.
      lastHistFetch = 0;
    }
    if (data.last_time) lastResultTime = data.last_time;
    else if (fullRows.length) lastResultTime = fullRows[fullRows.length - 1].block_time;
    const metaEl = $("chart-meta");
    if (metaEl) {
      const days = data.meta && data.meta.days ? data.meta.days : 10;
      metaEl.textContent = `${fullRows.length.toLocaleString("en-US")} rounds · ${days}D BUFFER`;
      metaEl.title = `Loaded chart history: ${fullRows.length.toLocaleString("en-US")} rounds`;
    }
  } catch (e) {
    /* keep old buffer on failure */
  }
}

function setConn(ok, txt) {
  $("dot").className = "dot " + (ok ? "on" : "off");
  const label = txt || (ok ? "LIVE" : "OFFLINE");
  $("conn-txt").textContent = label.length > 70 ? label.slice(0, 67) + "…" : label;
}

function signalClass(sig) {
  if (sig === "BIG") return ["sig-big", "BIG ▲"];
  if (sig === "SMALL") return ["sig-small", "SMALL ▼"];
  if (sig === "SKIP (WATCH)") return ["sig-watch", "WATCH"];
  if (sig.startsWith("SKIP")) return ["sig-skip", "NO TRADE"];
  return ["sig-wait", "WAIT"];
}

let lastSigLabel = "";
function renderSignal(s) {
  /* MARKET CONTEXT sidebar — trend + MTF + diagnostics (trade hero ဖြစ်နေတဲ့
     အချိန်တွင် console.error မဖြစ်စေရန်လည်း လုံခြုံစွာ ဖယ်ရှားပြီး) */
  const card = $("context-card");
  if (!card) return;
  const a = s.analysis;

  /* TREND strip: walk-based quick read */
  const tr = $("ctx-trend");
  if (tr) {
    const mt = a.mtf;
    if (mt && (mt.x5 || mt.x15)) {
      const agree = mt.x5 === mt.x15 && mt.x5 !== 0;
      tr.innerHTML = `×5 <b class="${mt.x5 > 0 ? "red" : "blue"}">${arrowOf(mt.x5)}</b>` +
        ` · ×15 <b class="${mt.x15 > 0 ? "red" : "blue"}">${arrowOf(mt.x15)}</b>` +
        (agree ? ` <b class="green">✓</b>` : ` <b class="orange">✗</b>`);
    } else tr.textContent = "—";
  }

  /* score chip (theme colors reuse) */
  const badge = $("score-badge");
  if (badge) {
    const sc = (a.score || 0);
    badge.textContent = `score ${sc > 0 ? "+" : ""}${sc.toFixed(1)}`;
    badge.className = "ctx-val mono " + (sc > 0 ? "red" : sc < 0 ? "blue" : "");
  }
}

/* ---- component gauge bars + MTF/Markov/feed-delay chips ---- */
const arrowOf = (v) => (v > 0 ? "▲" : v < 0 ? "▼" : "•");

function renderAnalytics(s) {
  const a = s.analysis || {};

  /* gauge bars (context card) */
  const g = $("gauges");
  if (g) {
    const parts = a.parts || [];
    if (!parts.length) { g.innerHTML = ""; }
    else {
      const max = Math.max(30, ...parts.map((p) => Math.abs(p.value || 0)));
      g.innerHTML = parts.map((p) => {
        const pct = Math.min(100, (Math.abs(p.value) / max) * 50) * 2;
        const cls = p.value > 0 ? "up" : p.value < 0 ? "down" : "";
        return `<div class="gauge-row"><span class="g-name">${p.name}</span>` +
          `<span class="g-bar"><i class="${cls}" style="width:${pct}%"></i></span>` +
          `<span class="g-val ${p.value > 0 ? "red" : p.value < 0 ? "blue" : ""}">${p.value > 0 ? "+" : ""}${p.value}</span></div>`;
      }).join("");
    }
  }

  /* reason text (context card) */
  const rs = $("reason");
  if (rs && a.reason) rs.textContent = a.reason;

  const mtfEl = $("mtf-chip");
  if (mtfEl) {
    const mt = a.mtf;
    if (mt && (mt.x5 || mt.x15)) {
      const want = (a.score || 0) > 0 ? 1 : -1;
      const agree = mt.x5 === want && mt.x15 === want;
      mtfEl.textContent = `MTF ×5 ${arrowOf(mt.x5)} · ×15 ${arrowOf(mt.x15)} ${agree ? "✓" : "✗"}`;
      mtfEl.className = agree ? "green" : "orange";
    } else mtfEl.textContent = "";
  }

  const mkEl = $("mk-chip");
  if (mkEl) {
    const mk = s.markov;
    mkEl.textContent = mk && mk.p_big != null
      ? `P(BIG) ${Math.round(mk.p_big * 100)}% (n=${mk.n})`
      : "";
    mkEl.className = mk && mk.p_big != null ? (mk.p_big >= 0.5 ? "red" : "blue") : "";
  }

  /* feed delay — silent (auto-standby engine-side only, user-facing text removed) */
  void s.feed_delay;

  /* 📡 button tooltip shows last Telegram event (sent/skip/error + time) */
  const tgB = $("tg-btn");
  if (tgB) {
    const t = s.tg_last;
    tgB.title = t
      ? `Telegram နောက်ဆုံး event — ${t.time} · ${t.result}\n${t.msg}`
      : "Telegram ချိတ်ဆက်မှု စမ်းသပ် (နှိပ်) · နောက်ဆုံး event မရှိသေးဘူး";
  }

  /* ---- 🎰 12-step staking panel (display-only detail; strategy unchanged) ---- */
  const st = s.strat || {};
  {
    const tierEl = $("st-tier"), stepEl = $("st-step");
    if (tierEl) {
      tierEl.textContent = "T" + ((st.tier || 0) + 1);
      tierEl.className = "stake-badge" + ((st.tier || 0) > 0 ? " hot" : "");
    }
    if (stepEl) stepEl.textContent = "S" + ((st.step || 0) + 1);

    const pend = s.strat_pending || st.pending;
    const modeEl = $("st-status");
    const pEl = $("st-pending");
    const issueEl = $("st-target-issue");
    const skEl = $("st-stake");
    const trigEl = $("st-trigger");
    const srcEl = $("st-source");
    const hero = $("st-signal-hero");

    if (pend) {
      if (modeEl) { modeEl.textContent = "ARMED"; modeEl.className = "stake-mode active"; }
      if (pEl) {
        pEl.textContent = pend.target || "—";
        pEl.className = "stake-hero-dir " + (pend.target === "BIG" ? "red" : "blue");
      }
      if (issueEl) issueEl.textContent = `TARGET …${String(pend.issue || "").slice(-6)}`;
      if (skEl) skEl.textContent = `${Number(pend.stake || 0).toLocaleString("en-US")} MMK`;
      if (trigEl) {
        const rv = pend.trigger_rsi != null ? Number(pend.trigger_rsi).toFixed(1) : "—";
        trigEl.textContent = `${rv} · ${pend.trigger_rule || "RSI setup"}`;
      }
      if (srcEl) {
        const src = pend.source_short_issue || String(pend.source_issue || "").slice(-6);
        const tm = pend.source_time ? String(pend.source_time).slice(11,16) : "";
        srcEl.textContent = src ? `…${src}${pend.confirm_type ? " · " + pend.confirm_type : ""}${tm ? " · " + tm : ""}` : "—";
      }
      if (hero) hero.className = "stake-signal-hero armed";
    } else {
      if (modeEl) { modeEl.textContent = "WAITING"; modeEl.className = "stake-mode waiting"; }
      if (pEl) { pEl.textContent = "WAITING"; pEl.className = "stake-hero-dir"; }
      if (issueEl) issueEl.textContent = "NO ACTIVE TARGET";
      if (skEl) skEl.textContent = "—";
      if (trigEl) trigEl.textContent = "Prev RSI ≤32 + BIG / ≥68 + SMALL";
      if (srcEl) srcEl.textContent = "waiting for confirmation round…";
      if (hero) hero.className = "stake-signal-hero";
    }

    const bEl = $("st-busts");
    if (bEl) {
      bEl.textContent = st.busts || 0;
      bEl.className = (st.busts || 0) > 0 ? "red" : "";
    }
  }
  const lastEl = $("st-last");
  if (lastEl) {
    const lt = s.strat_last;
    if (lt) {
      const cls = lt.outcome === "WIN" ? "green" : (lt.outcome === "12-STEP BUST" ? "red" : "orange");
      lastEl.innerHTML = `<span class="${cls}">${lt.outcome}</span> · T${lt.tier} · ${lt.bets || 0} bet${(lt.bets || 0) === 1 ? "" : "s"} · net ${lt.net >= 0 ? "+" : ""}${Number(lt.net || 0).toLocaleString("en-US")}`;
    } else {
      lastEl.textContent = "No settled episode yet";
    }
  }
}

/* ---- RSI 30-day extremes (Market Context strip) ---- */
async function fetchRsiExtremes() {
  const el = $("ctx-rsi30");
  if (!el) return;
  try {
    const r = await fetch("/api/rsi-extremes?days=30", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const d = await r.json();
    if (d.error) throw new Error(d.error);
    el.innerHTML =
      `L <b class="blue">${d.min.toFixed(1)}</b>` +
      ` · H <b class="red">${d.max.toFixed(1)}</b>`;
    el.title = `နောက်ဆုံး ${d.days} ရက် (${Math.round(d.rounds / 1440)} ရက်စာ ${d.rounds.toLocaleString("en-US")} rounds)\n` +
      `အနိမ့်ဆုံး RSI ${d.min} — ${d.min_at} (Issue …${d.min_issue})\n` +
      `အမြင့်ဆုံး RSI ${d.max} — ${d.max_at} (Issue …${d.max_issue})\n(နှိပ် = ပြန်တွက်)`;
  } catch (e) {
    el.textContent = "—";
  }
}
const rsi30El = $("ctx-rsi30");
if (rsi30El) {
  rsi30El.style.cursor = "pointer";
  rsi30El.addEventListener("click", () => {
    rsi30El.textContent = "…";
    fetchRsiExtremes();
  });
}

/* ---- backtest panel removed from UI — /api/backtest endpoint still available ---- */

function renderStats(s) {
  /* PERFORMANCE panel removed — stats remain available via ticker (P/L) */
}

function setTxt(id, v) { const el = $(id); if (el) el.textContent = v; }

function renderTicker(s) {
  const h = s.history || [];
  const last = h[h.length - 1];
  const a = s.analysis || {};

  setTxt("tk-issue", s.next_issue ? String(s.next_issue).slice(-8) : "—");

  const lb = $("tk-last");
  if (lb && last) {
    lb.textContent = last.number;
    lb.className = "tk-ball " + (last.type === "BIG" ? "big" : "small");
  } else if (lb) {
    lb.textContent = "—";
    lb.className = "tk-ball";
  }

  if (a.ready) {
    const total = a.big + a.small;
    setTxt("tk-big", `${a.big} · ${total ? Math.round(a.big / total * 100) : 0}%`);
    setTxt("tk-small", `${a.small} · ${total ? Math.round(a.small / total * 100) : 0}%`);
  } else {
    setTxt("tk-big", "—");
    setTxt("tk-small", "—");
  }

  const streakEl = $("tk-streak");
  if (streakEl && last && a.streak) {
    const dragon = a.streak >= DRAGON_MIN;
    streakEl.textContent = `${dragon ? "🔥 " : ""}${a.streak}${last.type === "BIG" ? "▲" : "▼"}`;
    streakEl.className = "tk-val mono " + (last.type === "BIG" ? "red" : "blue") +
      (dragon ? " dragon-glow" : "");
  } else if (streakEl) {
    streakEl.textContent = "—";
    streakEl.className = "tk-val mono";
  }

  setTxt("tk-vol", a.vol != null ? a.vol.toFixed(2) : "—");
}

/* ---- digit distribution bars (0–9 % over last 500 rounds) ---- */
let lastDistSig = "";
function renderDigitDist(s) {
  const wrap = $("digit-dist");
  if (!wrap) return;
  const h = s.history || [];
  if (!h.length) { wrap.innerHTML = ""; return; }
  const tail = h.slice(-500);
  const sig = tail.length + ":" + (tail.length ? tail[tail.length - 1].issue : "");
  if (sig === lastDistSig) return;
  lastDistSig = sig;

  const freq = new Array(10).fill(0);
  tail.forEach((x) => freq[x.number]++);
  const n = tail.length;
  const maxP = Math.max(...freq.map((c) => (c / n) * 100), 12);  // bar scale floor
  let out = "";
  for (let d = 0; d <= 9; d++) {
    const pct = (freq[d] / n) * 100;
    const barCls = d >= 5 ? "big" : "small";
    const w = Math.max(3, (pct / maxP) * 100);
    out += `<div class="dd-row">` +
      `<span class="dd-digit ${barCls}">${d}</span>` +
      `<span class="dd-bar"><i class="${barCls}" style="width:${w}%"></i></span>` +
      `<span class="dd-pct">${pct.toFixed(1)}%</span></div>`;
  }
  wrap.innerHTML = out;
}

let lastHistSig = "";
const DRAGON_MIN = 4;   // တူညီတဲ့ရလဒ် ဒီအရေအတွက် ဆက်ရင် 🔥 Dragon

function renderHistory(s) {
  const wrap = $("history");
  const h = s.history || [];
  /* skip DOM rebuild when the ball strip hasn't changed */
  const sig = h.length + ":" + (h.length ? h[h.length - 1].issue : "");
  if (sig !== lastHistSig) {
    lastHistSig = sig;
    const tail = h.slice(-500);
    /* streak length ending at each ball (chronological) */
    const runs = [];
    let r = 0;
    tail.forEach((x, i) => {
      r = (i > 0 && tail[i - 1].type === x.type) ? r + 1 : 1;
      runs.push(r);
    });
    const items = tail.map((x, i) => {
      const isDragon = runs[i] >= DRAGON_MIN;
      const isHead = isDragon && (i === tail.length - 1 || tail[i + 1].type !== x.type);
      const cls = `ball ${x.type.toLowerCase()}` +
        (isDragon ? " dragon" : "") + (isHead ? " dragon-head" : "");
      const title = `Issue ${x.issue}${x.block_time ? " · 🕒 " + x.block_time : ""}` +
        (isDragon ? ` · 🔥 Dragon ×${runs[i]}` : "");
      return `<div class="${cls}" title="${title}"` +
        (isHead ? ` data-streak="${runs[i]}"` : "") + `>${x.number}</div>`;
    }).reverse().join("");
    wrap.innerHTML = items || `<div class="empty">Waiting for data…</div>`;
  }

  const a = s.analysis;
  $("counts").innerHTML = a && a.ready
    ? `Window ${s.config.long_window}: <b class="b">BIG ${a.big}</b> · <b class="s">SMALL ${a.small}</b> · Gap ${a.gap} · <span title="10-day buffer">Buffer ${mergedCount.toLocaleString("en-US")}</span>`
    : `Collecting… Buffer ${mergedCount.toLocaleString("en-US")}`;
}

let lastLogSig = "";
function renderLog(s) {
  /* TRADE LOG panel removed — log persists in signals_log.csv */
}

function safeRender(fn, s) {
  try { fn(s); } catch (e) { console.error("render step failed:", e && e.message); }
}

function render(s, merged) {
  const fh = s.feed_health || {};
  const fstat = fh.status || (s.connected ? "LIVE" : "OFFLINE");
  if (!s.connected || fstat === "OFFLINE") {
    setConn(false, s.error ? "OFFLINE: " + s.error : "OFFLINE");
  } else if (fstat === "STALE") {
    setConn(false, `STALE FEED${fh.seconds_since_advance != null ? " · " + Math.round(fh.seconds_since_advance) + "s" : ""}`);
  } else if (fstat === "DEGRADED") {
    setConn(true, "DEGRADED · retrying feed");
  } else {
    setConn(true, "LIVE");
  }
  safeRender(renderSignal, s);
  safeRender(renderAnalytics, s);
  mergedCount = merged ? merged.length : 0;
  safeRender(renderTicker, s);
  safeRender(renderHistory, s);
  safeRender(renderDigitDist, s);
  if (window.TRXChart) TRXChart.update({ ...s, history: merged || s.history });
  setTxt("last-fetch", "Last update: " + (s.last_update || "—"));
  tickServerUpdate(s.last_update);
}

let refreshing = false;
let lastState = null;
let lastKnownIssue = "";

async function refresh() {
  if (refreshing) return;          // guard: never overlap polls
  refreshing = true;
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const s = await r.json();
    lastState = s;

    // refresh the 10-day chart buffer periodically or when it falls behind
    const lastLocal = fullRows.length ? fullRows[fullRows.length - 1].issue : "";
    const lastLive = s.history && s.history.length ? s.history[s.history.length - 1].issue : "";
    if (!fullRows.length || (lastLive && lastLive > lastLocal)) await fetchFullHistory(false);

    const merged = mergeRows(fullRows, s.history);
    render(s, merged);
  } catch (e) {
    console.error("refresh error:", e);
    setConn(false, "Connection error: " + (e && e.message ? e.message : e));
  } finally {
    refreshing = false;
  }
}

function tickClock() {
  const now = new Date();
  const hm = now.toLocaleTimeString("en-GB");
  $("clock").textContent = hm;

  /* chart bottom time bar */
  setTxt("ctb-clock", hm);
  const delayEl = $("ctb-delay");
  let interval = 60;
  for (let i = fullRows.length - 1; i >= Math.max(1, fullRows.length - 10); i--) {
    const a = Date.parse((fullRows[i - 1].block_time || "").replace(" ", "T"));
    const b = Date.parse((fullRows[i].block_time || "").replace(" ", "T"));
    if (!isNaN(a) && !isNaN(b) && b > a && b - a < 600000) { interval = Math.round((b - a) / 1000); break; }
  }
  if (lastResultTime) {
    setTxt("ctb-last", lastResultTime.replace("T", " "));
    const last = Date.parse(lastResultTime.replace(" ", "T"));
    if (!isNaN(last)) {
      /* upstream feed lag: newest blockTime vs local clock */
      const delaySec = Math.max(0, Math.round((now.getTime() - last) / 1000 - interval));
      if (delaySec >= 90 && delayEl) {
        delayEl.innerHTML = `⚠️ FEED DELAYED ~${Math.floor(delaySec / 60)}m ${delaySec % 60}s <span class="ctb-note">(source: trxchart.com)</span>`;
        delayEl.classList.add("warn");
      } else if (delayEl) {
        delayEl.textContent = "✅ FEED LIVE";
        delayEl.classList.remove("warn");
      }
      /* ETA extrapolation: draws repeat every `interval`, aligned to the last
         known slot. Modulo keeps a LIVE 0:00–1:00 countdown rolling forever —
         no more stuck "DRAWING…" state at slot boundaries. */
      const iv = interval * 1000;
      let etaMs = (last - now.getTime()) % iv;
      if (etaMs <= 0) etaMs += iv;
      const s = Math.max(0, Math.round(etaMs / 1000));
      setTxt("ctb-next", `NEXT ISSUE ETA: ~${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`);
    }
  } else {
    setTxt("ctb-last", "—");
    setTxt("ctb-next", "NEXT ISSUE ETA: —");
    if (delayEl) { delayEl.textContent = ""; delayEl.classList.remove("warn"); }
  }
}

function tickServerUpdate(t) { setTxt("ctb-srv", t || "—"); }

/* fullscreen chart mode */
const fsBtn = $("fs-btn");
if (fsBtn) fsBtn.addEventListener("click", () => {
  const card = $("chart-card");
  if (document.fullscreenElement) document.exitFullscreen();
  else if (card && card.requestFullscreen) card.requestFullscreen();
});
document.addEventListener("fullscreenchange", () => {
  const btn = $("fs-btn");
  if (btn) btn.classList.toggle("active", !!document.fullscreenElement);
});

/* Auto S/R toggle (find & show / hide) + signal arrows toggle */
const srBtn = $("sr-find-btn");
if (srBtn) {
  srBtn.classList.remove("active"); // Auto S/R defaults to OFF
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
/* 🎨 toggle: DRAW tools + INDICATORS bars (hidden by default; click = open both, again = close both) */
const dtToggle = $("dt-toggle-btn");
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
const sigBtn = $("sig-btn");
if (sigBtn) sigBtn.addEventListener("click", () => {
  if (window.TRXChart && TRXChart.toggleSignals) TRXChart.toggleSignals();
});

setInterval(refresh, 1500);
setInterval(() => fetchFullHistory(false), HIST_REFETCH_MS);
setInterval(tickClock, 1000);
tickClock();
fetchFullHistory(true).then(refresh);

/* ================= instant candle: /api/latest micro-poll =================
   Candle တစ်တင်တာနဲ့ chart ချက်ချင်း update — /api/state ကို မစောင့်ရတော့ဘူး */
let latestPolling = false;
let latestPollTimer = 0;
const LATEST_POLL_VISIBLE_MS = 250;
const LATEST_POLL_HIDDEN_MS = 1200;
function scheduleLatestPoll(delay) {
  clearTimeout(latestPollTimer);
  const ms = delay != null ? delay : (document.hidden ? LATEST_POLL_HIDDEN_MS : LATEST_POLL_VISIBLE_MS);
  latestPollTimer = setTimeout(pollLatest, ms);
}
async function pollLatest() {
  if (latestPolling) return;
  latestPolling = true;
  try {
    const r = await fetch("/api/latest", { cache: "no-store" });
    const d = await r.json();
    const rd = d.round;
    if (!rd || !rd.issue || rd.issue === lastKnownIssue) return;
    const first = lastKnownIssue === "";
    const previousIssue = lastKnownIssue;
    lastKnownIssue = rd.issue;
    if (first || !lastState) return;

    // Never synthesize across missing rounds. Browser sleep/network gaps can jump
    // several sequential issues; catch history up first so the ±1 walk stays exact.
    try {
      if (/^\d+$/.test(String(previousIssue)) && /^\d+$/.test(String(rd.issue))
          && BigInt(String(rd.issue)) > BigInt(String(previousIssue)) + 1n) {
        await fetchFullHistory(true);
        await refresh();
        return;
      }
    } catch (_e) { /* non-standard issue format: fall back to normal path */ }
    if (!fullRows.some((x) => x.issue === rd.issue)) {
      fullRows.push({
        issue: String(rd.issue),
        short_issue: String(rd.issue).slice(-6),
        number: rd.number,
        block_time: rd.block_time || "",
        type: rd.number >= 5 ? "BIG" : "SMALL",
      });
      if (fullRows.length > 30000) fullRows = fullRows.slice(-30000);
      if (rd.block_time) lastResultTime = rd.block_time;
      const newest = fullRows[fullRows.length - 1];
      const fast = window.TRXChart && TRXChart.appendLatest
        ? TRXChart.appendLatest(newest)
        : false;
      if (!fast) {
        const merged = mergeRows(fullRows, lastState.history);
        safeRender(() => render(lastState, merged), lastState);
      }
    }
  } catch (e) { /* noop */ }
  finally {
    latestPolling = false;
    scheduleLatestPoll();
  }
}
document.addEventListener("visibilitychange", () => scheduleLatestPoll(0));
scheduleLatestPoll(0);
fetchRsiExtremes();
setInterval(fetchRsiExtremes, 3600000);   // 1h

/* ================= alerts: sound + desktop notification ================= */
let soundOn = localStorage.getItem("trx_sound") === "1";

function beep() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [0, 190].forEach((delay) => setTimeout(() => {
      const o = ctx.createOscillator(), gn = ctx.createGain();
      o.type = "sine"; o.frequency.value = 880;
      gn.gain.setValueAtTime(.14, ctx.currentTime);
      gn.gain.exponentialRampToValueAtTime(.001, ctx.currentTime + .16);
      o.connect(gn).connect(ctx.destination);
      o.start(); o.stop(ctx.currentTime + .17);
    }, delay));
  } catch (e) { /* audio unavailable */ }
}

function notifySignal(label, issue) {
  try {
    if (window.Notification && Notification.permission === "granted") {
      new Notification("TRX Signal", { body: `${label} — Issue ${issue || "NEXT"}` });
    }
  } catch (e) { /* noop */ }
}

const bellBtn = $("bell-btn");
if (bellBtn) {
  bellBtn.classList.toggle("off", !soundOn);
  bellBtn.addEventListener("click", () => {
    soundOn = !soundOn;
    localStorage.setItem("trx_sound", soundOn ? "1" : "0");
    bellBtn.classList.toggle("off", !soundOn);
    if (soundOn && window.Notification && Notification.permission === "default") {
      Notification.requestPermission();
    }
    if (soundOn) beep();   // audible confirmation
  });
}

/* Telegram connectivity test (📡 header button) */
const tgBtn = $("tg-btn");
if (tgBtn) {
  tgBtn.addEventListener("click", async () => {
    tgBtn.textContent = "⏳";
    try {
      const r = await fetch("/api/telegram-test", { cache: "no-store" });
      const d = await r.json();
      tgBtn.textContent = d.ok ? "✅" : "❌";
      tgBtn.title = d.ok ? "Telegram OK — test message ပို့ပြီး" : ("Telegram error: " + (d.error || "unknown"));
    } catch (e) {
      tgBtn.textContent = "❌";
      tgBtn.title = "Telegram test failed: " + (e && e.message ? e.message : e);
    }
    setTimeout(() => { tgBtn.textContent = "📡"; }, 3000);
  });
}
