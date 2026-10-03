/* Display-only chart insights. No engine decisions, stakes or notifications. */
window.TRXContext = (() => {
  const $ = id => document.getElementById(id);
  let state = null, l1 = null, daily = null, filter = "all";
  let l1Trades = [], dailyEvents = [], l1Unavailable = true, dailyUnavailable = true;
  let historySignature = "";
  const finite = v => typeof v === "number" && Number.isFinite(v);
  const put = (id, value, tone = "") => {
    const el = $(id);
    if (!el) return;
    if (el.textContent !== value) el.textContent = value;
    if (el.className !== tone) el.className = tone;
  };
  const money = (n, signed = false) => finite(n) ? (signed && n >= 0 ? "+" : "") + n.toLocaleString("en-US") : "—";
  const sourceTime = value => {
    if (!value) return "—";
    const explicit = /Z$|[+-]\d{2}:?\d{2}$/.test(value);
    const date = new Date(explicit ? value : value.replace(" ", "T") + "+06:30");
    return Number.isFinite(date.getTime()) ? date.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", hour12:false}) : "—";
  };
  const fresh = () => !!state?.connected && !/OFFLINE|STALE|DELAY|ERROR/i.test(
    (state.feed_health?.status || "") + " " + ($("conn-txt")?.textContent || "OFFLINE"));

  function renderContext() {
    if (!$("market-panel")) return;
    const c = window.TRXChart?.getContext();
    const available = fresh() && c?.count >= 15 && finite(c.rsi) && finite(c.ema5) && finite(c.ema15);
    put("mc-timeframe", `BIG/SMALL walk · ${c?.timeframe || 1}m conditions`);
    if (!available) {
      put("mc-trend-icon", "↔", "market-icon");
      put("mc-momentum-icon", "↔", "market-icon");
      ["mc-trend", "mc-momentum", "mc-rsi"].forEach(id => put(id, "—"));
      put("mc-trend-detail", fresh() ? "Collecting chart data" : "Feed unavailable");
      put("mc-momentum-detail", "Waiting for fresh chart data");
      put("mc-zone", "RSI 14 · thresholds 32 / 68");
    } else {
      const gap = c.ema5 - c.ema15;
      const trend = Math.abs(gap) < 0.01 ? "MIXED" : gap > 0 ? "UP" : "DOWN";
      put("mc-trend", trend, trend === "UP" ? "tone-up" : trend === "DOWN" ? "tone-down" : "");
      put("mc-trend-detail", `EMA 5 ${trend === "MIXED" ? "near" : gap > 0 ? "above" : "below"} EMA 15`);
      put("mc-trend-icon", trend === "UP" ? "↗" : trend === "DOWN" ? "↘" : "↔", "market-icon " + (trend === "UP" ? "tone-up" : trend === "DOWN" ? "tone-down" : ""));
      const delta = finite(c.previousRsi) ? c.rsi - c.previousRsi : 0;
      const rising = delta > 0.01, falling = delta < -0.01;
      const momentum = rising ? (c.rsi <= 32 || c.previousRsi <= 32 ? "RECOVERING" : "RISING") : falling ? "FALLING" : "FLAT";
      put("mc-momentum", momentum, rising ? "tone-up" : falling ? "tone-down" : "");
      put("mc-momentum-icon", rising ? "↗" : falling ? "↘" : "↔", "market-icon " + (rising ? "tone-up" : falling ? "tone-down" : ""));
      put("mc-momentum-detail", `RSI ${delta > 0 ? "+" : ""}${delta.toFixed(1)} vs previous bar`);
      put("mc-rsi", c.rsi.toFixed(1));
      put("mc-zone", c.rsi <= 32 ? "OVERSOLD ≤32" : c.rsi >= 68 ? "OVERBOUGHT ≥68" : "NEUTRAL · 32–68", c.rsi <= 32 || c.rsi >= 68 ? "tone-zone" : "");
    }
    const currentIssue = String(state?.history?.at(-1)?.issue || "");
    const p = state?.strat?.pending || state?.strat_pending;
    const stepArmed = fresh() && p?.target && String(p.issue || "") > currentIssue;
    const l1Armed = fresh() && l1?.ready && l1.pending;
    put("mc-setup", !fresh() ? "UNAVAILABLE" : stepArmed || l1Armed ? "ARMED" : "WAITING", stepArmed || l1Armed ? "tone-up" : "tone-setup");
    put("mc-setup-detail", !fresh() ? "Waiting for fresh engine data" : `L1: ${l1?.ready ? l1Armed ? l1.pending.target : l1.waiting_rule ? "RULE WAIT" : "WAITING" : "SYNCING"} · 12-Step: ${stepArmed ? p.target : "WAITING"}`);
    put("mc-rule", !fresh() || !l1?.ready ? "Engine unavailable · no valid setup" : l1.waiting_rule ? `${l1.waiting_rule.rule || "Skip rule"} · waiting rounds` : l1.pending ? "No rule wait · engine signal armed" : "No rule wait · awaiting 1m RSI / confirmation");
  }

  function renderHistory() {
    const body = $("signal-history-body");
    if (!body) return;
    const times = new Map((state?.history || []).map(r => [String(r.issue), r.block_time]));
    const rows = l1Trades.filter(t => t.issue && /^(BIG|SMALL)$/.test(t.target) && typeof t.won === "boolean" && finite(t.pnl))
      .map(t => ({...t, engine:"L1 CAPITAL", outcome:t.won ? "WIN" : "LOSS"}));
    const seen = new Set();
    for (const ev of dailyEvents) {
      if (!ev.issue || !/^(WIN|LOSS)$/.test(ev.outcome) || !finite(ev.pnl)) continue;
      const key = String(ev.issue);
      if (seen.has(key)) continue;
      seen.add(key);
      rows.push({...ev, time:ev.time || times.get(key), engine:"12-STEP"});
    }
    const tail = rows.filter(t => filter === "all" || t.engine === filter)
      .sort((a,b) => String(b.issue).localeCompare(String(a.issue), "en", {numeric:true})).slice(0,5);
    const signature = JSON.stringify([tail, filter, l1Unavailable, dailyUnavailable]);
    if (signature === historySignature) return;
    historySignature = signature;
    body.replaceChildren();
    if (!tail.length) {
      const row = body.insertRow(), cell = row.insertCell(); cell.colSpan = 6;
      cell.textContent = "No settled model bets available for this filter.";
    }
    tail.forEach(t => {
      const row = body.insertRow();
      const values = [`${sourceTime(t.time)} / …${String(t.issue).slice(-8)}`, t.engine, t.target || "—", money(t.stake), t.outcome, money(t.pnl, true)];
      values.forEach((value,i) => {
        const cell = row.insertCell(); cell.textContent = value;
        if (i === 0) cell.title = String(t.issue);
        if (i === 2) cell.className = t.target === "BIG" ? "tone-up" : "tone-down";
        if (i >= 4) cell.className = t.pnl >= 0 ? "tone-up" : "tone-down";
      });
    });
    const unavailable = [l1Unavailable && "L1", dailyUnavailable && "12-Step"].filter(Boolean);
    put("signal-history-status", unavailable.length ? `${unavailable.join(" / ")} history temporarily unavailable · last loaded model results retained.` : "Available engine history · model results; actual manual execution may differ.");
  }

  function selectTab(button, focus = false) {
    document.querySelectorAll('.market-tabs [role="tab"]').forEach(tab => {
      const active = tab === button;
      tab.setAttribute("aria-selected", String(active)); tab.tabIndex = active ? 0 : -1;
      $(tab.getAttribute("aria-controls")).hidden = !active;
    });
    if (focus) button.focus();
  }
  const tabs = Array.from(document.querySelectorAll('.market-tabs [role="tab"]'));
  tabs.forEach((tab,i) => {
    tab.addEventListener("click", () => selectTab(tab));
    tab.addEventListener("keydown", event => {
      const next = event.key === "ArrowRight" ? (i+1)%tabs.length : event.key === "ArrowLeft" ? (i+tabs.length-1)%tabs.length : event.key === "Home" ? 0 : event.key === "End" ? tabs.length-1 : null;
      if (next !== null) { event.preventDefault(); selectTab(tabs[next], true); }
    });
  });
  document.querySelectorAll('.history-filters button').forEach(button => button.addEventListener("click", () => {
    filter = button.dataset.engine;
    document.querySelectorAll('.history-filters button').forEach(b => b.setAttribute("aria-pressed", String(b === button)));
    renderHistory();
  }));
  setInterval(renderContext, 1000);
  return {
    onState(s) { state=s; renderContext(); renderHistory(); },
    onL1(x) { l1=x; l1Unavailable=!Array.isArray(x?.trades); if (!l1Unavailable) l1Trades=x.trades; renderContext(); renderHistory(); },
    onDaily(d) { daily=d; dailyUnavailable=false; dailyEvents=[...(d.history || []).flatMap(r=>r.recent_events || []), ...(d.report?.recent_events || [])]; renderHistory(); },
    onDailyError() { dailyUnavailable=true; renderHistory(); },
  };
})();
