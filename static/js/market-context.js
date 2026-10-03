/* Display-only chart insights. No engine decisions, stakes or notifications. */
window.TRXContext = (() => {
  const $ = id => document.getElementById(id);
  let state = null, l1 = null, daily = null, filter = "all";
  let l1Trades = [], dailyEvents = [], l1Unavailable = true, dailyUnavailable = true;
  let historySignature = "", historyDate = "", visibleLimit = 20, expandedKey = "";
  let stateReceived = 0, l1Received = 0, historyRows = [], setupSignature = "", frameSignature = "";
  const finite = v => typeof v === "number" && Number.isFinite(v);
  const put = (id, value, tone = "") => {
    const el = $(id);
    if (!el) return;
    if (el.textContent !== value) el.textContent = value;
    if (el.className !== tone) el.className = tone;
  };
  const money = (n, signed = false) => finite(n) ? (signed && n >= 0 ? "+" : "") + n.toLocaleString("en-US") : "—";
  const sourceDate = value => {
    if (!value) return null;
    value=String(value);
    const explicit = /Z$|[+-]\d{2}:?\d{2}$/.test(value);
    const date = new Date(explicit ? value : value.replace(" ", "T") + "+06:30");
    return Number.isFinite(date.getTime()) ? date : null;
  };
  const localDate = value => { const d=sourceDate(value); return d ? `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,"0")}-${String(d.getDate()).padStart(2,"0")}` : ""; };
  const sourceTime = value => sourceDate(value)?.toLocaleTimeString([], {hour:"2-digit", minute:"2-digit", hour12:false}) || "—";
  const sourceDateTime = value => sourceDate(value)?.toLocaleString([], {year:"numeric", month:"short", day:"numeric", hour:"2-digit", minute:"2-digit", hour12:false}) || "—";
  const receiptAge = () => stateReceived ? Math.max(0,(Date.now()-stateReceived)/1000) : Infinity;

  const fresh = () => !!state?.connected && receiptAge() < 15 && (!finite(state?.feed_health?.seconds_since_advance) || state.feed_health.seconds_since_advance+receiptAge()<120) && !/OFFLINE|STALE|DELAY|ERROR|DEGRADED/i.test(
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
    const p = state?.strat_pending || state?.strat?.pending;
    const stepArmed = validTarget(p, currentIssue);
    const l1Armed = l1Ready() && validTarget(l1.pending, currentIssue);
    put("mc-setup", !fresh() ? "UNAVAILABLE" : stepArmed || l1Armed ? "ARMED" : "WAITING", stepArmed || l1Armed ? "tone-up" : "tone-setup");
    put("mc-setup-detail", !fresh() ? "Waiting for fresh engine data" : `L1: ${l1Ready() ? l1Armed ? l1.pending.target : l1.waiting_rule ? "RULE WAIT" : "WAITING" : "SYNCING"} · 12-Step: ${stepArmed ? p.target : "WAITING"}`);
    put("mc-rule", !l1Ready() ? "Engine unavailable · no valid setup" : l1.waiting_rule ? `${l1.waiting_rule.rule || "Skip rule"} · waiting rounds` : l1Armed ? "No rule wait · engine signal armed" : "No rule wait · awaiting 1m RSI / confirmation");
    renderChecklists(p);
    renderComparisons();
    renderQuality();
  }

  const trendOf = c => !finite(c?.ema5) || !finite(c?.ema15) ? "—" : Math.abs(c.ema5-c.ema15)<0.01 ? "MIXED" : c.ema5>c.ema15 ? "UP" : "DOWN";
  const momentumOf = c => !finite(c?.rsi) || !finite(c?.previousRsi) ? "—" : Math.abs(c.rsi-c.previousRsi)<0.01 ? "FLAT" : c.rsi>c.previousRsi ? "RISING" : "FALLING";
  const toneOf = text => /^(UP|RISING|ARMED)$/.test(text) ? "tone-up" : /^(DOWN|FALLING)$/.test(text) ? "tone-down" : "";
  const currentIssue = () => String(state?.history?.at(-1)?.issue || "");
  const l1Ready = () => fresh() && l1?.ready && Date.now()-l1Received<15000 && (!l1.source_issue || String(l1.source_issue)===currentIssue());
  const validTarget = (p, issue=currentIssue()) => fresh() && /^(BIG|SMALL)$/.test(p?.target || "") &&
    !!issue && String(p.issue || "") > issue && (!state?.next_issue || String(p.issue)===String(state.next_issue));
  function checkList(id, items) {
    const list=$(id); list.replaceChildren();
    for(const [label, value, status] of items) {
      const row=document.createElement("li"), icon=document.createElement("span"), text=document.createElement("div"), title=document.createElement("strong"), detail=document.createElement("span");
      icon.className="check-icon " + (status==="ok" ? "tone-up" : "tone-zone");
      icon.textContent=status==="ok" ? "✓" : status==="wait" ? "◷" : "—";
      title.textContent=label; detail.textContent=value; text.append(title,detail); row.append(icon,text); list.append(row);
    }
  }
  function renderChecklists(p) {
    const ready=l1Ready(), lp=ready && validTarget(l1?.pending) ? l1.pending : null, sp=validTarget(p) ? p : null;
    const mode=!fresh() ? "UNAVAILABLE" : !ready ? "SYNCING" : l1.waiting_rule ? "RULE WAIT" : lp ? "ARMED" : "WAITING";
    const smode=!fresh() ? "UNAVAILABLE" : sp ? "ARMED" : "WAITING";
    put("check-l1-status",mode,toneOf(mode)); put("check-step-status",smode,toneOf(smode));
    const key=JSON.stringify([mode,smode,lp,sp,ready?l1.waiting_rule:null,ready?l1.risk_status:null]);
    if(key===setupSignature) return; setupSignature=key;
    const trigger=x=>finite(x?.trigger_rsi) ? `Engine trigger RSI ${x.trigger_rsi.toFixed(1)}` : "Trigger RSI not published";
    const target=x=>x ? `${x.target} · issue ${x.issue} · ${money(x.stake)} MMK` : "No current target issue";
    checkList("check-l1-list",[
      ["Engine sync",ready ? "Latest engine snapshot" : "Waiting for matching fresh engine data",ready?"ok":"wait"],
      ["RSI / confirmation",lp ? trigger(lp)+" · setup accepted by engine" : "Awaiting engine setup · prev RSI ≤32 + BIG / ≥68 + SMALL",lp?"ok":"wait"],
      ["Rule gate",!ready ? "Unavailable" : l1.waiting_rule ? `${l1.waiting_rule.rule || "Skip rule"} · rounds must pass` : "No skip rule active",ready&&!l1.waiting_rule?"ok":"wait"],
      ["Target",target(lp),lp?"ok":"wait"],
      ["Daily status",ready ? l1.risk_status || "Not published" : "Unavailable",ready&&l1.risk_status==="TRADE ALLOWED"?"ok":"wait"],
    ]);
    checkList("check-step-list",[
      ["Engine sync",fresh() ? "Latest 1m state" : "Waiting for fresh state",fresh()?"ok":"wait"],
      ["RSI trigger",sp ? trigger(sp) : "Awaiting engine trigger · prev RSI ≤32 or ≥68",sp&&finite(sp.trigger_rsi)?"ok":"wait"],
      ["Confirmation",sp ? sp.confirm_type ? `${sp.confirm_type} at source issue ${sp.source_issue || "—"}` : "Setup / ladder continuation accepted by engine" : "BIG after low RSI / SMALL after high RSI",sp?"ok":"wait"],
      ["Target",target(sp),sp?"ok":"wait"],
      ["Ladder level",sp ? `T${(state.strat_pending===p ? Number(sp.tier)+1 : sp.tier) || "—"} / S${(state.strat_pending===p ? Number(sp.step)+1 : sp.step) || "—"}` : "No armed ladder",sp?"ok":"wait"],
    ]);
  }
  function renderComparisons() {
    const snap=window.TRXChart?.getComparisons();
    const frames=snap?.frames || [], available=fresh();
    const key=JSON.stringify([available,frames]); if(key===frameSignature) return; frameSignature=key;
    const body=$("mc-timeframes"), closed=$("mc-closed-bars"); body.replaceChildren(); closed.replaceChildren();
    const trends=frames.map(c=>available ? trendOf(c) : "—");
    const complete=trends.length===3 && trends.every(t=>t!=="—");
    const aligned=complete && trends.every(t=>t===trends[0]) && trends[0]!=="MIXED";
    put("mc-alignment",!available ? "Feed unavailable" : !complete ? "Collecting timeframe data" : aligned ? `3 / 3 trends ${trends[0]}` : "Mixed timeframe trends",aligned?toneOf(trends[0]):"");
    for(const c of frames) {
      const row=body.insertRow(); row.dataset.timeframe=c.timeframe;
      const values=[`${c.timeframe}m · ${available ? c.complete ? "COMPLETE" : "FORMING" : "UNAVAILABLE"}`,available?trendOf(c):"—",available&&finite(c.rsi)?c.rsi.toFixed(1):"—",available?momentumOf(c):"—"];
      values.forEach((v,i)=>{ const cell=row.insertCell();cell.textContent=v;cell.className=toneOf(v); if(i===2) cell.dataset.rsi="true"; });
      const text=document.createElement("span"); text.textContent=`${c.timeframe}m: ${available?trendOf(c.closed):"—"} · RSI ${available&&finite(c.closed.rsi)?c.closed.rsi.toFixed(1):"—"}`;closed.append(text);
    }
  }
  function settledRows() {
    const times=new Map((state?.history || []).map(r=>[String(r.issue),r.block_time]));
    const rows=l1Trades.filter(t=>t.issue && /^(BIG|SMALL)$/.test(t.target) && typeof t.won==="boolean" && finite(t.pnl))
      .map(t=>({...t,engine:"L1 CAPITAL",outcome:t.won?"WIN":"LOSS"}));
    const signals=new Map(dailyEvents.filter(e=>e.outcome==="SIGNAL").map(e=>[String(e.issue),e]));
    const seen=new Set();
    for(const ev of dailyEvents) {
      if(!ev.issue || !/^(WIN|LOSS)$/.test(ev.outcome) || !finite(ev.pnl)) continue;
      const key=String(ev.issue); if(seen.has(key)) continue; seen.add(key);
      const signal=signals.get(key);
      rows.push({...ev,trigger_rsi:ev.trigger_rsi ?? signal?.trigger_rsi,source_issue:ev.source_issue ?? signal?.source_issue,
        time:ev.time || times.get(key) || window.TRXChart?.getComparisons()?.times.get(key),engine:"12-STEP"});
    }
    return rows.sort((a,b)=>String(b.issue).localeCompare(String(a.issue),"en",{numeric:true}));
  }
  function renderQuality() {
    const snap=window.TRXChart?.getComparisons();
    const age=receiptAge(), sourceAge=state?.feed_health?.seconds_since_advance;
    put("mc-quality-status",!fresh()?"UNAVAILABLE":snap?.missingMinutes || snap?.unknownTimes || snap?.irregularIntervals ? "CHECK GAPS" : "AVAILABLE",fresh()?"tone-setup":"tone-zone");
    put("mc-quality-feed",`${!fresh()?"UNAVAILABLE":state?.feed_health?.status || "LIVE"} · received ${finite(age)?Math.floor(age)+"s ago":"—"}${finite(sourceAge)?" · last advance "+Math.round(sourceAge+age)+"s ago":""}`);
    put("mc-quality-coverage",snap?.rows ? `${snap.rows.toLocaleString()} rounds · ${sourceDateTime(snap.first)} → ${sourceDateTime(snap.last)}` : "No loaded chart history");
    put("mc-quality-gaps",snap ? `${snap.missingMinutes} estimated missing minutes · ${snap.unknownTimes} unknown timestamps · ${snap.irregularIntervals} irregular intervals` : "Not checked");
    const l1Count=historyRows.filter(t=>t.engine==="L1 CAPITAL").length, stepCount=historyRows.length-l1Count;
    put("mc-quality-history",`L1 ${l1Count} · 12-Step ${stepCount} records${l1Unavailable || dailyUnavailable ? " · source unavailable" : ""} · loaded records only`);
  }
  function renderHistory() {
    const body=$("signal-history-body"); if(!body) return;
    historyRows=settledRows();
    const rows=historyRows.filter(t=>(filter==="all" || t.engine===filter) && (!historyDate || localDate(t.time)===historyDate));
    const tail=rows.slice(0,visibleLimit);
    const signature=JSON.stringify([tail,rows.length,filter,historyDate,expandedKey,l1Unavailable,dailyUnavailable]);
    if(signature===historySignature) return;historySignature=signature;
    const wins=rows.filter(t=>t.outcome==="WIN").length, pnl=rows.reduce((sum,t)=>sum+t.pnl,0);
    put("history-count",`Showing ${tail.length} of ${rows.length} settled model bets · local time · MMK`);
    put("history-summary",`${wins}W / ${rows.length-wins}L · P/L ${money(pnl,true)} MMK · filtered records`);
    body.replaceChildren();
    if(!tail.length) {const row=body.insertRow(),cell=row.insertCell();cell.colSpan=7;cell.textContent="No settled model bets available for this filter.";}
    for(const t of tail) {
      const key=t.engine+":"+t.issue, row=body.insertRow();row.className="history-result";
      const values=[`${sourceTime(t.time)} / …${String(t.issue).slice(-8)}`,t.engine,t.target || "—",money(t.stake),t.outcome,money(t.pnl,true)];
      values.forEach((value,i)=>{const cell=row.insertCell();cell.textContent=value;if(i===0)cell.title=sourceDateTime(t.time)+" · "+t.issue;if(i===2)cell.className=t.target==="BIG"?"tone-up":"tone-down";if(i>=4)cell.className=t.pnl>=0?"tone-up":"tone-down";});
      const action=row.insertCell(), button=document.createElement("button");button.type="button";button.className="history-detail-button";
      button.textContent=expandedKey===key?"Close":"View";button.setAttribute("aria-label",`Details for ${t.engine} issue ${t.issue}`);button.setAttribute("aria-expanded",String(expandedKey===key));
      button.addEventListener("click",()=>{expandedKey=expandedKey===key?"":key;renderHistory();const next=Array.from(body.querySelectorAll("[data-detail-key]")).find(b=>b.dataset.detailKey===key);next?.focus();});
      button.dataset.detailKey=key;action.append(button);
      if(expandedKey===key) {
        const details=body.insertRow();details.className="history-detail-row";const cell=details.insertCell();cell.colSpan=7;
        const dl=document.createElement("dl");dl.className="history-detail-grid";
        for(const [label,value] of [["Issue",t.issue],["Time (local)",sourceDateTime(t.time)],["Actual result",t.actual || "Not published"],["Level",`T${t.tier ?? "—"} / S${t.step ?? "—"}`],["Trigger RSI",finite(t.trigger_rsi)?t.trigger_rsi.toFixed(1):"Not recorded"],["Rule",t.trigger_rule || t.rule || "Not recorded"],["Source issue",t.source_issue || "Not recorded"]]) {
          const wrap=document.createElement("div"),dt=document.createElement("dt"),dd=document.createElement("dd");dt.textContent=label;dd.textContent=String(value);wrap.append(dt,dd);dl.append(wrap);
        }
        cell.append(dl);
      }
    }
    $("history-more").hidden=tail.length>=rows.length;
    $("history-more").textContent=`Show ${Math.min(20,rows.length-tail.length)} more`;
    const unavailable=[l1Unavailable&&"L1",dailyUnavailable&&"12-Step"].filter(Boolean);
    const unknown=historyRows.filter(t=>!localDate(t.time)).length;
    put("signal-history-status",`${unavailable.length?unavailable.join(" / ")+" history temporarily unavailable · last loaded model results retained. ":"Available engine history · "}model results; actual manual execution may differ. Loaded records only.${unknown?" "+unknown+" records have no timestamp; date filters exclude them.":""}`);
    renderQuality();
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
    filter = button.dataset.engine; visibleLimit=20; expandedKey="";
    document.querySelectorAll('.history-filters button').forEach(b => b.setAttribute("aria-pressed", String(b === button)));
    renderHistory();
  }));
  $("history-date")?.addEventListener("change",event=>{historyDate=event.target.value;visibleLimit=20;expandedKey="";renderHistory();});
  $("history-date-clear")?.addEventListener("click",()=>{historyDate="";$("history-date").value="";visibleLimit=20;expandedKey="";renderHistory();});
  $("history-more")?.addEventListener("click",()=>{visibleLimit+=20;renderHistory();});
  setInterval(renderContext, 1000);
  return {
    onState(s) { state=s; stateReceived=Date.now(); renderContext(); renderHistory(); },
    onL1(x) { l1=x; l1Received=Date.now(); l1Unavailable=!Array.isArray(x?.trades); if (!l1Unavailable) l1Trades=x.trades; renderContext(); renderHistory(); },
    onDaily(d) { daily=d; dailyUnavailable=!d?.report || !Array.isArray(d.report.recent_events); if(!dailyUnavailable) dailyEvents=[...(d.history || []).flatMap(r=>r.recent_events || []), ...(d.report?.recent_events || [])]; renderHistory(); },
    onDailyError() { dailyUnavailable=true; renderHistory(); },
  };
})();
