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
  (b || []).forEach((r) => { if (!m.has(r.issue)) m.set(r.issue, r); });
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
      fullRows = mergeRows(fullRows, inc);
    } else if (!force && !inc.length && data.incremental) {
      /* server has nothing newer (or was restarted with a shorter buffer):
         force one full refetch on the next cycle */
      lastHistFetch = 0;
    }
    if (data.last_time) lastResultTime = data.last_time;
    else if (fullRows.length) lastResultTime = fullRows[fullRows.length - 1].block_time;
    const metaEl = $("chart-meta");
    if (metaEl && data.meta) {
      metaEl.textContent = `${(data.meta.count || fullRows.length).toLocaleString("en-US")} rounds · ${data.meta.days}d loaded`;
    }
  } catch (e) {
    /* keep old buffer on failure */
  }
}

function setConn(ok, txt) {
  $("dot").className = "dot " + (ok ? "on" : "off");
  $("conn-txt").textContent = txt && txt.length > 60 ? txt.slice(0, 57) + "…" : (txt || "");
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
  const card = $("signal-card");
  const a = s.analysis;
  card.classList.remove("sig-big", "sig-small", "sig-watch", "sig-wait", "sig-skip");
  $("next-issue").textContent = s.next_issue || "—";

  if (!a) return;
  const [cls, label] = signalClass(a.signal);
  card.classList.add(cls);
  $("signal-big").textContent = label;

  /* pulse the card when an actionable signal appears/changes */
  if ((cls === "sig-big" || cls === "sig-small") && label !== lastSigLabel) {
    card.classList.remove("flash");
    void card.offsetWidth;   // restart CSS animation
    card.classList.add("flash");
    if (soundOn) beep();
    notifySignal(label, s.next_issue);
  }
  lastSigLabel = label;

  const badge = $("score-badge");
  badge.textContent = "score " + (a.score > 0 ? "+" : "") + a.score.toFixed(1);
  badge.className = "score-badge " +
    (a.score > 0 ? "green" : a.score < 0 ? "red" : "");

  $("reason").textContent = a.reason;

  const bet = $("bet-line");
  if (s.pending) {
    bet.textContent = `💵 BET PLACED: ${s.pending.signal} — ${fmtInt(s.pending.stake || s.bet_size)} MMK (Issue ${s.pending.short_issue})`;
    bet.classList.add("show");
  } else {
    bet.classList.remove("show");
  }
}

/* ---- component gauge bars + MTF/Markov/feed-delay chips ---- */
const arrowOf = (v) => (v > 0 ? "▲" : v < 0 ? "▼" : "•");

function renderAnalytics(s) {
  const a = s.analysis || {};

  const g = $("gauges");
  if (g) {
    const parts = a.parts || [];
    if (!parts.length) { g.innerHTML = ""; return; }
    const max = Math.max(30, ...parts.map((p) => Math.abs(p.value || 0)));
    g.innerHTML = parts.map((p) => {
      const pct = Math.min(100, (Math.abs(p.value) / max) * 50) * 2;
      const cls = p.value > 0 ? "up" : p.value < 0 ? "down" : "";
      return `<div class="gauge-row"><span class="g-name">${p.name}</span>` +
        `<span class="g-bar"><i class="${cls}" style="width:${pct}%"></i></span>` +
        `<span class="g-val ${p.value > 0 ? "red" : p.value < 0 ? "blue" : ""}">${p.value > 0 ? "+" : ""}${p.value}</span></div>`;
    }).join("");
  }

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

  const fdEl = $("fd-chip");
  if (fdEl) {
    const d = s.feed_delay;
    fdEl.textContent = (d != null && d >= 120) ? `⏳ FEED +${Math.floor(d / 60)}m` : "";
    fdEl.className = "orange";
  }
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
    streakEl.textContent = `${a.streak}${last.type === "BIG" ? "▲" : "▼"}`;
    streakEl.className = "tk-val mono " + (last.type === "BIG" ? "red" : "blue");
  } else if (streakEl) {
    streakEl.textContent = "—";
    streakEl.className = "tk-val mono";
  }

  setTxt("tk-vol", a.vol != null ? a.vol.toFixed(2) : "—");

  const pl = $("tk-pl");
  if (pl) {
    pl.textContent = `${s.units >= 0 ? "+" : ""}${s.units}u`;
    pl.className = "tk-val mono " + (s.units > 0 ? "green" : s.units < 0 ? "red" : "");
  }
}

let lastHistSig = "";
function renderHistory(s) {
  const wrap = $("history");
  const h = s.history || [];
  /* skip DOM rebuild when the ball strip hasn't changed */
  const sig = h.length + ":" + (h.length ? h[h.length - 1].issue : "");
  if (sig !== lastHistSig) {
    lastHistSig = sig;
    const items = h.slice(-500).reverse().map(x =>
      `<div class="ball ${x.type.toLowerCase()}" title="Issue ${x.issue}${x.block_time ? " · 🕒 " + x.block_time : ""}">${x.number}</div>`
    ).join("");
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
  setConn(!!s.connected, s.connected ? "LIVE" : (s.error ? "OFFLINE: " + s.error : "OFFLINE"));
  safeRender(renderSignal, s);
  safeRender(renderAnalytics, s);
  mergedCount = merged ? merged.length : 0;
  safeRender(renderTicker, s);
  safeRender(renderHistory, s);
  if (window.TRXChart) TRXChart.update({ ...s, history: merged || s.history });
  setTxt("last-fetch", "Last update: " + (s.last_update || "—"));
  tickServerUpdate(s.last_update);
}

let refreshing = false;
async function refresh() {
  if (refreshing) return;          // guard: never overlap polls
  refreshing = true;
  try {
    const r = await fetch("/api/state", { cache: "no-store" });
    if (!r.ok) throw new Error("HTTP " + r.status);
    const s = await r.json();

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
  srBtn.classList.add("active");   // S/R checkbox defaults to ON
  srBtn.addEventListener("click", () => {
    if (window.TRXChart && TRXChart.autoSR) {
      const r = TRXChart.autoSR();
      srBtn.classList.toggle("active", r.on);
      clearTimeout(srBtn._t);
      if (r.on) {
        srBtn.textContent = `🔍 S/R ×${r.n}`;
        srBtn._t = setTimeout(() => { srBtn.textContent = "🔍 Auto S/R"; }, 2500);
      } else {
        srBtn.textContent = "🔍 Auto S/R";
      }
    }
  });
}
const sigBtn = $("sig-btn");
if (sigBtn) sigBtn.addEventListener("click", () => {
  if (window.TRXChart && TRXChart.toggleSignals) TRXChart.toggleSignals();
});

setInterval(refresh, 2500);
setInterval(() => fetchFullHistory(false), HIST_REFETCH_MS);
setInterval(tickClock, 1000);
tickClock();
fetchFullHistory(true).then(refresh);

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
