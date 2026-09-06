(() => {
  const $d = (id) => document.getElementById(id);
  const money = (v, signed=false) => {
    const n = Number(v || 0);
    return `${signed && n >= 0 ? "+" : ""}${n.toLocaleString("en-US")} MMK`;
  };
  function render(d) {
    const r = d.report || {};
    const set = (id, text) => { const e=$d(id); if(e) e.textContent=text; };
    set("d12-date", r.date || "—");
    set("d12-signals", r.signals || 0);
    set("d12-wl", `${r.bet_wins || 0} / ${r.bet_losses || 0}`);
    set("d12-wr", `${Number(r.bet_win_rate || 0).toFixed(1)}%`);
    const pnl=$d("d12-pnl"); if(pnl){ pnl.textContent=money(r.net_pnl,true); pnl.className=r.net_pnl>0?"green":r.net_pnl<0?"red":""; }
    set("d12-staked", money(r.total_staked)); set("d12-returned", money(r.total_returned));
    set("d12-episodes", `Episodes ${r.episodes_resolved||0} · Wins ${r.episode_wins||0} · Tier Failed ${r.tier_failed||0} · Busts ${r.busts||0}`);
    set("d12-depth", `Max Stake ${money(r.max_stake)} · Deepest T${r.max_tier||1}/S${r.max_step||1}`);
    const e=r.engine||{}; const p=e.pending;
    set("d12-status", p ? `Engine ACTIVE · T${e.tier}/S${e.step} · ${p.target} · ${money(p.stake)} · …${String(p.issue||"").slice(-6)}` : `Engine WAITING · T${e.tier||1}/S${e.step||1}`);
    const h=$d("d12-history");
    if(h){ h.innerHTML=(d.history||[]).slice(0,3).map(x=>`<div><span>${x.date}</span><span>W ${x.bet_wins||0} / L ${x.bet_losses||0}</span><b class="${x.net_pnl>0?'green':x.net_pnl<0?'red':''}">${money(x.net_pnl,true)}</b></div>`).join(""); }
  }
  async function refresh(){
    try { const x=await fetch('/api/12step/daily-report?days=7',{cache:'no-store'}); if(x.ok) render(await x.json()); } catch(_e) {}
  }
  refresh(); setInterval(refresh, 10000);
})();
