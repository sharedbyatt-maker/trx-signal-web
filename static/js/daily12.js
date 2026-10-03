(() => {
  const $d = (id) => document.getElementById(id);
  const money = (v, signed=false) => {
    const n = Number(v || 0);
    return `${signed && n >= 0 ? "+" : ""}${Math.round(n).toLocaleString("en-US")} MMK`;
  };
  const pct = (v, signed=false) => {
    const n = Number(v || 0);
    return `${signed && n > 0 ? "+" : ""}${n.toFixed(1)}%`;
  };
  const clsByNum = (v) => Number(v || 0) > 0 ? "green" : Number(v || 0) < 0 ? "red" : "";

  function renderActivity(r) {
    const el = $d("d12-activity");
    if (!el) return;
    const events = (r.recent_events || []).slice(-6).reverse();
    if (!events.length) {
      el.innerHTML = '<div class="d12-empty">No 12-step activity recorded yet today.</div>';
      return;
    }
    el.innerHTML = events.map((ev) => {
      const out = ev.outcome || "EVENT";
      const tone = out === "WIN" ? "green" : out === "LOSS" ? "red" : out === "SIGNAL" ? "blue" : "orange";
      const issue = String(ev.issue || "").slice(-6);
      const stake = ev.stake != null ? money(ev.stake) : "—";
      const pnl = ev.pnl != null ? `<span class="${clsByNum(ev.pnl)}">${money(ev.pnl, true)}</span>` : "";
      const detail = out === "SIGNAL"
        ? `${ev.target || "—"} · T${ev.tier || 1}/S${ev.step || 1}${ev.trigger_rsi != null ? " · RSI " + Number(ev.trigger_rsi).toFixed(1) : ""}`
        : `${ev.target || "—"} → ${ev.actual || "—"} · T${ev.tier || 1}/S${ev.step || 1}`;
      return `<div class="d12-activity-row"><span class="d12-event ${tone}">${out}</span><span>…${issue}</span><span>${detail}</span><span>${stake}</span>${pnl}</div>`;
    }).join("");
  }

  function render(d) {
    window.TRXContext?.onDaily(d);
    const r = d.report || {};
    const set = (id, text) => { const e=$d(id); if(e) e.textContent=text; };
    set("d12-date", r.date || "—");
    set("d12-signals", r.signals || 0);
    set("d12-wl", `${r.bet_wins || 0} / ${r.bet_losses || 0}`);
    set("d12-wr", pct(r.bet_win_rate));
    set("d12-episode-wr", pct(r.episode_win_rate));
    set("d12-roi", pct(r.roi_pct, true));
    set("d12-staked", money(r.total_staked));
    set("d12-returned", money(r.total_returned));
    set("d12-avg-stake", money(r.avg_stake));
    set("d12-open", r.open_episodes || 0);

    const pnl=$d("d12-pnl");
    if(pnl){ pnl.textContent=money(r.net_pnl,true); pnl.className=clsByNum(r.net_pnl); }
    const roi=$d("d12-roi");
    if(roi) roi.className=clsByNum(r.roi_pct);

    set("d12-episodes", `Resolved ${r.episodes_resolved||0} · Episode Wins ${r.episode_wins||0} · Tier Failed ${r.tier_failed||0} · Busts ${r.busts||0}`);
    set("d12-depth", `Max Stake ${money(r.max_stake)} · Deepest T${r.max_tier||1}/S${r.max_step||1} · Avg P/L/Episode ${money(r.avg_pnl_per_episode,true)}`);
    const edge = Number(r.edge_vs_break_even || 0);
    set("d12-edge", `Break-even ${Number(r.break_even_win_rate || 0).toFixed(1)}% · Edge ${edge >= 0 ? "+" : ""}${edge.toFixed(1)} pp · Avg P/L/Bet ${money(r.avg_pnl_per_bet,true)}`);
    const edgeEl=$d("d12-edge"); if(edgeEl) edgeEl.className=`daily12-line ${clsByNum(edge)}`;
    set("d12-updated", `Last ledger update: ${r.updated_at || "—"}`);

    const e=r.engine||{};
    const p=e.pending;
    set("d12-status", p
      ? `Engine ARMED · T${e.tier}/S${e.step} · ${p.target} → …${String(p.issue||"").slice(-6)} · ${money(p.stake)}${p.trigger_rsi != null ? " · Trigger RSI " + Number(p.trigger_rsi).toFixed(1) : ""}`
      : `Engine WAITING · T${e.tier||1}/S${e.step||1} · Next eligible stake ${money(e.next_eligible_stake)} · waiting for valid RSI setup`);

    renderActivity(r);

    const h=$d("d12-history");
    if(h){
      const rows=(d.history||[]).slice(0,4);
      h.innerHTML=rows.length ? rows.map(x=>`<div><span>${x.date}</span><span>W ${x.bet_wins||0} / L ${x.bet_losses||0} · ${Number(x.bet_win_rate||0).toFixed(1)}%</span><span>ROI ${pct(x.roi_pct,true)}</span><b class="${clsByNum(x.net_pnl)}">${money(x.net_pnl,true)}</b></div>`).join("") : '<div class="d12-empty">No previous daily reports yet.</div>';
    }
  }

  async function refresh(){
    try {
      const x=await fetch('/api/12step/daily-report?days=7',{cache:'no-store'});
      if (!x.ok) throw new Error("HTTP " + x.status);
      render(await x.json());
    } catch(_e) { window.TRXContext?.onDailyError(); }
  }
  refresh();
  setInterval(refresh, 10000);
})();

