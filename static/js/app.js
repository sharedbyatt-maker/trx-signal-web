const $ = (id) => document.getElementById(id);
const fmtInt = (n) => n.toLocaleString("en-US");
const browserOffline = () => typeof navigator !== 'undefined' && navigator.onLine === false;
function normalizeRound(row) {
  if(!row||typeof row!=='object'||Array.isArray(row))throw new Error('Invalid chart round');
  const id=row.issue;
  if(!(typeof id==='string'&&/^[A-Za-z0-9:_.-]{1,96}$/.test(id))&&!(Number.isSafeInteger(id)&&id>=0))throw new Error('Invalid chart issue');
  if(!(typeof row.number==='number'||typeof row.number==='string'&&/^[0-9]$/.test(row.number)))throw new Error('Invalid result digit');
  const number=Number(row.number),type=number>=5?'BIG':'SMALL';
  if(!Number.isInteger(number)||number<0||number>9||row.type!=null&&row.type!==type)throw new Error('Invalid result digit or type');
  if(row.block_time!=null&&(typeof row.block_time!=='string'||row.block_time.length>128))throw new Error('Invalid result time');
  if(row.block_time&& !Number.isFinite(Date.parse(row.block_time.replace(' ','T')+(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(row.block_time)?'':'Z'))))throw new Error('Invalid result time');
  if(row.block_time_utc!=null&&(typeof row.block_time_utc!=='string'||!Number.isFinite(Date.parse(row.block_time_utc))))throw new Error('Invalid result time');
  const issue=String(id);
  return {...row,issue,number,type,short_issue:issue.slice(-6),block_time:row.block_time||''};
}
function normalizeHistory(rows, tuples=false) {
  if(!Array.isArray(rows))throw new Error('Invalid chart history');
  const normalized=rows.map(row=>{
    if(tuples){if(!Array.isArray(row)||row.length<2)throw new Error('Invalid chart history');return normalizeRound({issue:row[0],number:row[1],block_time:row[2]??''});}
    return normalizeRound(row);
  });
  return [...new Map(normalized.map(r=>[r.issue,r])).values()].sort((a,b)=>a.issue<b.issue?-1:a.issue>b.issue?1:0);
}
function normalizeState(s){
  if(!s||typeof s!=='object'||Array.isArray(s)||s.log!=null&&!Array.isArray(s.log))throw new Error('Invalid state response');
  return {...s,history:normalizeHistory(s.history)};
}
function chartUpdateStatus(message){const el=$('chart-update-status');if(el){if(el.textContent!==message)el.textContent=message;el.hidden=!message;}}

/* ================= 30-day full history buffer ================= */
let fullRows = [];            // from /api/history ([issue, number, blockTime] tuples)
let fullIssueSet = new Set(); // O(1) membership for the 30-day browser buffer
let lastHistFetch = 0;
let mergedCount = 0;
let lastResultUtc = null;
let lastResultTime = "";      // server-reported blockTime of the newest round
const HIST_REFETCH_MS = 45000;

function rebuildFullIssueSet() {
  fullIssueSet = new Set(fullRows.map((r) => String(r.issue)));
}

function mergeRows(a, b) {
  const m = new Map();
  (a || []).forEach((r) => m.set(r.issue, r));
  // Newer/server-authoritative copies win. This also lets corrected historical
  // rows replace stale browser copies instead of being silently masked.
  (b || []).forEach((r) => m.set(r.issue, r));
  return [...m.values()].sort((x, y) => (x.issue < y.issue ? -1 : x.issue > y.issue ? 1 : 0));
}

let historyRequest = null;
async function fetchFullHistory(force, strict = false) {
  if(browserOffline()){if(strict)throw new Error('Browser offline');return;}
  if (historyRequest) {
    try{await historyRequest;}catch(e){if(strict&&!force)throw e;}
    if (force) return fetchFullHistory(true, strict);
    return;
  }
  historyRequest = loadFullHistory(force, strict);
  try { await historyRequest; }
  finally { historyRequest = null; }
}
async function loadFullHistory(force, strict = false) {
  if (!force && Date.now() - lastHistFetch < HIST_REFETCH_MS) return;
  lastHistFetch = Date.now();
  const issueAtStart = fullRows.length ? fullRows[fullRows.length - 1].issue : "";
  let retainedLiveArrival = false;
  try {
    /* incremental sync: only rounds newer than what we already hold */
    const since = (!force && fullRows.length)
      ? `?since=${encodeURIComponent(fullRows[fullRows.length - 1].issue)}`
      : "";
    const data = await TRXNet.run(async signal => {
      const r = await fetch("/api/history" + since, { cache: "no-store", signal });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }, 12000);
    if(strict && (!Array.isArray(data.history)||!data.history.length))throw new Error("No chart history available. Existing chart retained.");
    const inc = normalizeHistory(data?.history, true);
    if (inc.length) {
      // A forced fetch is a fresh authoritative 30-day snapshot, not an append.
      // Incremental fetches append/replace by issue.
      // A response can lag /api/latest. Preserve rounds received during this
      // request, while still replacing/correcting the older snapshot entirely.
      const snapshotEnd = inc[inc.length - 1].issue;
      const arrived = force ? fullRows.filter(r => r.issue > issueAtStart && r.issue > snapshotEnd) : [];
      retainedLiveArrival = arrived.length > 0 || (!force && fullRows.length > 0 && fullRows[fullRows.length - 1].issue > snapshotEnd);
      fullRows = force ? mergeRows(inc, arrived) : mergeRows(fullRows, inc);
      if (fullRows.length > 45200) fullRows = fullRows.slice(-45200);
      rebuildFullIssueSet();
    } else {
      // Initial page load can beat the background engine. Do not lock the chart
      // into the small /api/state fallback for 45 seconds; allow the next refresh
      // to retry the full history immediately.
      lastHistFetch = 0;
      retainedLiveArrival = fullRows.length > 0 && fullRows[fullRows.length - 1].issue > issueAtStart;
    }
    if (!retainedLiveArrival) {
      const newest=fullRows.at(-1);
      lastResultUtc = (!newest?.block_time||data.last_time===newest.block_time)&&typeof data.last_time_utc==='string'?data.last_time_utc:null;
      lastResultTime = newest?.block_time || data.last_time || '';
    }
    const metaEl = $("chart-meta");
    if (metaEl) {
      const days = data.meta && data.meta.days ? data.meta.days : 30;
      metaEl.textContent = `${fullRows.length.toLocaleString("en-US")} rounds · ${days}D BUFFER`;
      metaEl.title = `Loaded chart history: ${fullRows.length.toLocaleString("en-US")} rounds`;
    }
  } catch (e) {
    /* keep old buffer on failure */
    lastHistFetch = 0;
    if(strict)throw e;
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
  if(s.money_settings){const m=s.money_settings;const fmt=v=>Number(v).toLocaleString();const limit=v=>v?fmt(v)+' MMK':'Disabled';if($('st-money-settings'))$('st-money-settings').textContent=`Bankroll ${fmt(m.bankroll)} · Base ${fmt(m.base)} · TP ${limit(m.tp)} · SL ${limit(m.sl)}`;if($('st-money-ladder'))$('st-money-ladder').textContent=(s.money_ladder||[]).map((r,t)=>`T${t+1}: `+r.map(fmt).join(' → ')).join(' / ');if($('st-money-risk')){$('st-money-risk').textContent=s.money_risk_status||'Manual execution only';$('st-money-risk').classList.toggle('is-observe',s.money_risk_status!=='TRADE ALLOWED');}}

  {
    const tierEl = $("st-tier"), stepEl = $("st-step");
    if (tierEl) {
      tierEl.textContent = "T" + ((st.tier || 0) + 1);
      tierEl.className = "stake-badge" + ((st.tier || 0) > 0 ? " hot" : "");
    }
    if (stepEl) stepEl.textContent = "S" + ((st.step || 0) + 1);

    const candidate = s.strat_pending || st.pending;
    const fresh = window.TRXContext?.isFresh() ?? !!s.connected;
    const pend = fresh && window.TRXContext?.isValidTarget(candidate) ? candidate : null;
    const unavailable = !fresh;
    const modeEl = $("st-status");
    const pEl = $("st-pending");
    const issueEl = $("st-target-issue");
    const skEl = $("st-stake");
    const trigEl = $("st-trigger");
    const srcEl = $("st-source");
    const hero = $("st-signal-hero");

    if (pend) {
      window.TRXAlerts?.signal("12-STEP", pend);
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
      if (modeEl) { modeEl.textContent = unavailable ? "UNAVAILABLE" : "WAITING"; modeEl.className = "stake-mode waiting"; }
      if (pEl) { pEl.textContent = unavailable ? "UNAVAILABLE" : "WAITING"; pEl.className = "stake-hero-dir"; }
      if (issueEl) issueEl.textContent = unavailable ? "NO VALID SIGNAL · FEED UNAVAILABLE" : "NO ACTIVE TARGET";
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
    const d = await TRXNet.run(async signal => {
      const r = await fetch("/api/rsi-extremes?days=30", { cache: "no-store", signal });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    }, 45000);
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
  const counts = $("counts");
  /* Recent History UI is optional/removed; keep history data available for chart logic. */
  if (!wrap && !counts) return;
  const h = s.history || [];
  /* skip DOM rebuild when the ball strip hasn't changed */
  const sig = h.length + ":" + (h.length ? h[h.length - 1].issue : "");
  if (wrap && sig !== lastHistSig) {
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
  if (counts) {
    counts.innerHTML = a && a.ready
      ? `Window ${s.config.long_window}: <b class="b">BIG ${a.big}</b> · <b class="s">SMALL ${a.small}</b> · Gap ${a.gap} · <span title="30-day buffer">Buffer ${mergedCount.toLocaleString("en-US")}</span>`
      : `Collecting… Buffer ${mergedCount.toLocaleString("en-US")}`;
  }
}

let lastLogSig = "";
function renderLog(s) {
  /* TRADE LOG panel removed — log persists in signals_log.csv */
}

function safeRender(fn, s) {
  try { fn(s); } catch (e) { console.error("render step failed:", e && e.message); }
}

function render(s, merged, received = true) {
  if (typeof s.admin_alerts_enabled === "boolean") {
    document.body.dataset.adminAlerts = s.admin_alerts_enabled ? "1" : "0";
    const bell = $("bell-btn");
    if (bell) bell.disabled = !s.admin_alerts_enabled;
  }
  if (received) {
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
    window.TRXContext?.onState(s);
  }
  safeRender(renderSignal, s);
  safeRender(renderAnalytics, s);
  mergedCount = merged ? merged.length : 0;
  safeRender(renderTicker, s);
  safeRender(renderHistory, s);
  safeRender(renderDigitDist, s);
  if (window.TRXChart) TRXChart.update({ ...s, history: merged || s.history });
  tickServerUpdate(s.last_update_utc || (s.last_update ? s.last_update.replace(" ", "T") + "Z" : null));
}

let refreshing = false;
let lastState = null;
let lastStateReceived = 0;
let lastKnownIssue = "";
let lastStateAttempt = 0, gapRetryAt = 0;

let refreshRequest=null, manualChartRefreshing=false;
async function refresh(){
  if(manualChartRefreshing)return;
  if(browserOffline()){setConn(false,'OFFLINE · browser connection lost');return;}
  if(refreshRequest)return refreshRequest;
  if(document.hidden&&!window.TRXAlerts?.isEnabled?.()&&Date.now()-lastStateAttempt<15000)return;
  refreshRequest=loadState();try{return await refreshRequest;}finally{refreshRequest=null;}
}
async function loadState() {
  if (refreshing) return;          // guard: never overlap polls
  refreshing = true;
  lastStateAttempt=Date.now();
  try {
    const s = await TRXNet.run(async signal => {
      const r = await fetch("/api/state", { cache: "no-store", signal });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
    const validState=normalizeState(s);
    lastState = validState;
    lastStateReceived = Date.now();

    // refresh the 30-day chart buffer periodically or when it falls behind
    const lastLocal = fullRows.length ? fullRows[fullRows.length - 1].issue : "";
    const lastLive = validState.history.at(-1)?.issue||'';
    if (!fullRows.length || (lastLive && lastLive > lastLocal)) {
      fetchFullHistory(false).then(() => {
        if (lastState === validState && Date.now() - lastStateReceived < 15000) {
          if (window.TRXChart) TRXChart.update({...validState, history:mergeRows(fullRows,validState.history)});
        }
      }).catch(()=>{});
    }

    const merged = mergeRows(fullRows, validState.history);
    render(validState, merged);
  } catch (e) {
    setConn(false, "Connection error: " + (e && e.message ? e.message : e));
    if (lastState) safeRender(renderAnalytics, lastState);
  } finally {
    refreshing = false;
  }
}

$('chart-refresh')?.addEventListener('click',async()=>{
  if(manualChartRefreshing)return;
  manualChartRefreshing=true;const button=$('chart-refresh'),status=$('chart-refresh-status');
  button.disabled=true;button.setAttribute('aria-busy','true');button.classList.add('is-refreshing');status.textContent='Refreshing chart…';
  try{
    if(refreshRequest)await refreshRequest;
    const results=await Promise.allSettled([
      TRXNet.run(async signal=>{const r=await fetch('/api/state',{cache:'no-store',signal});if(!r.ok)throw new Error('State HTTP '+r.status);return normalizeState(await r.json());}),
      fetchFullHistory(true,true)
    ]);
    const failed=results.find(r=>r.status==='rejected');if(failed)throw failed.reason;
    const s=results[0].value;lastState=s;lastStateReceived=Date.now();render(s,mergeRows(fullRows,s.history));
    status.textContent='Chart refreshed · '+new Date().toLocaleTimeString();
  }catch(e){status.textContent='Refresh failed · '+(e?.message||'Data unavailable')+'. Your chart is retained.';}
  finally{manualChartRefreshing=false;button.disabled=false;button.removeAttribute('aria-busy');button.classList.remove('is-refreshing');}
});

function sourceEpoch(value) {
  const raw = String(value || "").trim().replace(" ", "T");
  // TRXChart's naive blockTime is Myanmar time; never use the viewer's timezone.
  return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(raw) ? raw : raw + "+06:30");
}

function tickClock() {
  const now = new Date();
  const hm = now.toLocaleTimeString("en-GB");
  $("clock").textContent = hm;
  const offset = -now.getTimezoneOffset();
  const zone = "UTC" + (offset >= 0 ? "+" : "−") + String(Math.floor(Math.abs(offset) / 60)).padStart(2, "0") + ":" + String(Math.abs(offset) % 60).padStart(2, "0");
  $("clock").title = "Local time · " + zone;
  if (lastStateReceived && Date.now() - lastStateReceived >= 15000 && !/OFFLINE|ERROR|STALE|DEGRADED/i.test($('conn-txt')?.textContent||'')) setConn(false, "OFFLINE · state update overdue");
  if (lastState) safeRender(renderAnalytics, lastState);
  setTxt("ctb-zone", "LOCAL " + zone);

  /* chart bottom time bar */
  setTxt("ctb-clock", hm);
  const delayEl = $("ctb-delay");
  let interval = 60;
  for (let i = fullRows.length - 1; i >= Math.max(1, fullRows.length - 10); i--) {
    const a = sourceEpoch(fullRows[i - 1].block_time);
    const b = sourceEpoch(fullRows[i].block_time);
    if (!isNaN(a) && !isNaN(b) && b > a && b - a < 600000) { interval = Math.round((b - a) / 1000); break; }
  }
  if (lastResultTime) {
    const last = sourceEpoch(lastResultUtc || lastResultTime);
    if (!isNaN(last)) {
      setTxt("ctb-last", new Date(last).toLocaleTimeString("en-GB"));
      const age = Math.max(0, Math.round((now.getTime() - last) / 1000));
      setTxt("ctb-age", "AGE: " + (age < 60 ? age + "s" : Math.floor(age / 60) + "m " + age % 60 + "s"));
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
      setTxt("ctb-next", window.TRXContext?.isFresh()
        ? `NEXT ISSUE ETA: ~${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`
        : "NEXT ISSUE ETA: —");
    }
  } else {
    setTxt("ctb-last", "—");
    setTxt("ctb-age", "AGE: —");
    setTxt("ctb-next", "NEXT ISSUE ETA: —");
    if (delayEl) { delayEl.textContent = ""; delayEl.classList.remove("warn"); }
  }
}

function tickServerUpdate(t) {
  const stamp = t && Date.parse(t);
  const value = Number.isFinite(stamp) ? new Date(stamp).toISOString().replace("T", " ").slice(0, 19) : "—";
  setTxt("ctb-srv", value);
  setTxt("last-fetch", "Server updated (UTC): " + value);
}

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
/* Drawing palette and indicator controls open independently. */
const dtToggle = $("dt-toggle-btn");
const indToggle = $("ind-toggle-btn");
const drawBar = $("draw-tools");
const indBar = $("ind-bar");
if (dtToggle) {
  dtToggle.addEventListener("click", () => {
    const open = drawBar && drawBar.classList.contains("collapsed");
    if (drawBar) drawBar.classList.toggle("collapsed", !open);
    dtToggle.classList.toggle("active", !!open);
    dtToggle.setAttribute("aria-expanded", String(!!open));
  });
}
if (indToggle) {
  indToggle.addEventListener("click", () => {
    const open = indBar && indBar.classList.contains("collapsed");
    if (indBar) indBar.classList.toggle("collapsed", !open);
    indToggle.classList.toggle("active", !!open);
    indToggle.setAttribute("aria-expanded",String(!!open));
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
fetchFullHistory(true);
refresh();

/* ================= instant candle: /api/latest micro-poll =================
   Candle တစ်တင်တာနဲ့ chart ချက်ချင်း update — /api/state ကို မစောင့်ရတော့ဘူး */
let latestPolling = false;
let latestPollTimer = 0;
const LATEST_POLL_VISIBLE_MS = 250;
const LATEST_POLL_HIDDEN_MS = 5000;
function scheduleLatestPoll(delay) {
  clearTimeout(latestPollTimer);
  const backgroundDelay=window.TRXAlerts?.isEnabled?.()?1200:LATEST_POLL_HIDDEN_MS;
  const ms = delay != null ? delay : (browserOffline()?LATEST_POLL_HIDDEN_MS:document.hidden?backgroundDelay:LATEST_POLL_VISIBLE_MS);
  latestPollTimer = setTimeout(pollLatest, ms);
}
async function pollLatest() {
  if (latestPolling) return;
  latestPolling = true;
  try {
    if(browserOffline())return;
    const d = await TRXNet.run(async signal => {
      const r = await fetch("/api/latest", { cache: "no-store", signal });
      if (!r.ok) throw new Error("HTTP " + r.status);
      return r.json();
    });
    if(!d?.round)return;
    const rd = normalizeRound(d.round);
    if (lastKnownIssue && String(rd.issue) < String(lastKnownIssue)) return;
    lastKnownIssue = rd.issue;
    window.TRXContext?.onLatest(rd);
    if (!lastState) return;
    const chartRows=window.TRXChart?.studyInfo?.().rows||lastState.history;
    const previousIssue=String(chartRows.at(-1)?.issue||'');
    if(rd.issue>=previousIssue&&rd.block_time){lastResultTime=rd.block_time;lastResultUtc=rd.block_time_utc||null;}
    if(previousIssue&&rd.issue<=previousIssue&&fullIssueSet.has(rd.issue)){chartUpdateStatus('');return;}

    // Never synthesize across missing rounds. Browser sleep/network gaps can jump
    // several sequential issues; catch history up first so the ±1 walk stays exact.
    try {
      if (/^\d+$/.test(String(previousIssue)) && /^\d+$/.test(String(rd.issue))
          && BigInt(String(rd.issue)) > BigInt(String(previousIssue)) + 1n) {
        if(Date.now()<gapRetryAt)return;
        gapRetryAt=Date.now()+1500;
        chartUpdateStatus('Syncing missing chart history…');
        await fetchFullHistory(true,true);
        await refresh();
        gapRetryAt=0;
        if(String(window.TRXChart?.studyInfo?.().rows.at(-1)?.issue||'')>=rd.issue)chartUpdateStatus('');
        return;
      }
    } catch (_e) { chartUpdateStatus('Chart history delayed · retrying. Existing chart retained.');return; }
    if (!fullIssueSet.has(String(rd.issue))) {
      fullRows.push({
        issue: String(rd.issue),
        short_issue: String(rd.issue).slice(-6),
        number: rd.number,
        block_time: rd.block_time || "",
        type: rd.number >= 5 ? "BIG" : "SMALL",
      });
      if (fullRows.length > 45200) fullRows = fullRows.slice(-45200);
      rebuildFullIssueSet();
      if (rd.block_time) lastResultTime = rd.block_time;
      lastResultUtc = rd.block_time_utc || null;
      const newest = fullRows[fullRows.length - 1];
      const fast = window.TRXChart && TRXChart.appendLatest
        ? TRXChart.appendLatest(newest)
        : false;
      if (!fast) {
        const merged = mergeRows(fullRows, lastState.history);
        safeRender(() => render(lastState, merged, false), lastState);
      }
      if (lastState) safeRender(renderAnalytics, lastState);
    }
    chartUpdateStatus('');
  } catch (e) { if(!browserOffline())chartUpdateStatus('Latest chart update unavailable · retrying. Existing chart retained.'); }
  finally {
    latestPolling = false;
    scheduleLatestPoll();
  }
}
function resumePublicView(){if(browserOffline())return;lastHistFetch=0;refresh();fetchFullHistory(false);scheduleLatestPoll(0);window.dispatchEvent(new Event('trx:view-resume'));}
document.addEventListener("visibilitychange", () => {if(!document.hidden)resumePublicView();else scheduleLatestPoll();});
window.addEventListener('online',resumePublicView);
window.addEventListener('pageshow',e=>{if(e.persisted)resumePublicView();});
window.addEventListener('offline',()=>{setConn(false,'OFFLINE · browser connection lost');scheduleLatestPoll();if(lastState)safeRender(renderAnalytics,lastState);});
scheduleLatestPoll(0);
fetchRsiExtremes();
setInterval(fetchRsiExtremes, 3600000);   // 1h

/* ================= alerts: sound + desktop notification ================= */
let soundOn = false;
try { soundOn = localStorage.getItem("trx_sound") === "1"; } catch (_e) {}

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
    setTimeout(() => { ctx.close().catch(() => {}); }, 500);
  } catch (e) { /* audio unavailable */ }
}

function notifySignal(label, issue) {
  try {
    if (window.Notification && Notification.permission === "granted") {
      new Notification("TRX Signal", { body: `${label} — Issue ${issue || "NEXT"}` });
    }
  } catch (e) { /* noop */ }
}

const alertedIssues = new Map();
window.TRXAlerts = {
  isEnabled(){return document.body.dataset.adminAlerts!=='0'&&soundOn;},
  signal(engine, pending) {
    if (document.body.dataset.adminAlerts === "0" || !soundOn || !pending || !window.TRXContext?.isValidTarget(pending)) return;
    const key = String(pending.issue) + ":" + pending.target;
    if (alertedIssues.get(engine) === key) return;
    alertedIssues.set(engine, key);
    beep();
    notifySignal(engine + " " + pending.target, pending.issue);
  },
};

const bellBtn = $("bell-btn");
if (bellBtn) {
  bellBtn.classList.toggle("off", !soundOn);
  bellBtn.disabled = document.body.dataset.adminAlerts === "0";
  bellBtn.addEventListener("click", () => {
    soundOn = !soundOn;
    try { localStorage.setItem("trx_sound", soundOn ? "1" : "0"); } catch (_e) {}
    bellBtn.classList.toggle("off", !soundOn);
    if (soundOn && window.Notification && Notification.permission === "default") {
      Notification.requestPermission().catch(() => {});
    }
    if (soundOn) beep();   // audible confirmation
  });
}

/* Telegram connectivity test (📡 header button) */
const tgBtn = $("tg-btn");
if (tgBtn) {
  tgBtn.addEventListener("click", async () => {
    if (tgBtn.disabled) return;
    tgBtn.disabled = true;
    tgBtn.textContent = "⏳";
    try {
      const d = await TRXNet.run(async signal => {
        const r = await fetch("/api/telegram-test", {
        method: "POST",
        cache: "no-store",
        headers: { "X-Requested-With": "TRX-Terminal" },
        signal,
      });
        return r.json();
      }, 12000);
      tgBtn.textContent = d.ok ? "✅" : "❌";
      tgBtn.title = d.ok ? "Telegram OK — test message ပို့ပြီး" : ("Telegram error: " + (d.error || "unknown"));
    } catch (e) {
      tgBtn.textContent = "❌";
      tgBtn.title = "Telegram test failed: " + (e && e.message ? e.message : e);
    }
    tgBtn.disabled = false;
    setTimeout(() => { tgBtn.textContent = "📡"; }, 3000);
  });
}


