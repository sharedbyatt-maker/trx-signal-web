(() => {
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Number(n || 0).toLocaleString();

  function setState(el, kind) {
    if (!el) return;
    el.classList.remove("waiting", "active", "win", "loss");
    el.classList.add(kind);
  }

  function render(x) {
    const p = x && x.pending;
    const ready = !!(x && x.ready);
    const status = $("l1-status");
    const focus = $("focus-l1");

    if (!ready) {
      if (status) { status.textContent = "WAITING"; setState(status, "waiting"); }
      if ($("l1-pending")) $("l1-pending").textContent = "WAITING";
      if ($("l1-target-issue")) $("l1-target-issue").textContent = (x && x.error) ? "ENGINE ERROR" : "NO ACTIVE TARGET";
      if (focus) {
        focus.className = "focus-state is-waiting";
        const b = focus.querySelector("b"); if (b) b.textContent = "WAITING";
      }
      return;
    }

    if (p) {
      if (status) { status.textContent = p.target; setState(status, "active"); }
      if ($("l1-pending")) $("l1-pending").textContent = p.target;
      if ($("l1-target-issue")) $("l1-target-issue").textContent = "TARGET · " + String(p.issue || "—").slice(-8);
      if ($("l1-stake")) $("l1-stake").textContent = fmt(p.stake) + " MMK";
      if ($("l1-tier")) $("l1-tier").textContent = "T" + p.tier;
      if ($("l1-step")) $("l1-step").textContent = "S" + p.step;
      if (focus) {
        focus.className = "focus-state is-active";
        const b = focus.querySelector("b"); if (b) b.textContent = p.target + " · " + fmt(p.stake);
      }
    } else {
      if (status) { status.textContent = "WAITING"; setState(status, "waiting"); }
      if ($("l1-pending")) $("l1-pending").textContent = x.waiting_rule ? "RULE WAIT" : "WAITING";
      if ($("l1-target-issue")) $("l1-target-issue").textContent = x.waiting_rule ? "FROZEN SKIP RULE ACTIVE" : "NO ACTIVE TARGET";
      if ($("l1-stake")) $("l1-stake").textContent = "—";
      if (focus) {
        focus.className = "focus-state is-waiting";
        const b = focus.querySelector("b"); if (b) b.textContent = x.waiting_rule ? "RULE WAIT" : "WAITING";
      }
    }

    const pnl = Number(x.today_pnl || 0);
    if ($("l1-pnl")) {
      $("l1-pnl").textContent = (pnl >= 0 ? "+" : "") + fmt(pnl) + " MMK";
      $("l1-pnl").classList.toggle("green", pnl > 0);
      $("l1-pnl").classList.toggle("red", pnl < 0);
    }
    if ($("l1-risk")) $("l1-risk").textContent = x.risk_status || "TRADE ALLOWED";

    const trades = Array.isArray(x.trades) ? x.trades.filter(t => String(t.time || "").slice(0, 10) === String(x.today || "")) : [];
    const wins = trades.filter(t => t.won).length;
    const losses = trades.length - wins;
    const staked = trades.reduce((sum, t) => sum + Number(t.stake || 0), 0);
    let deepest = null;
    trades.forEach(t => {
      const rank = Number(t.tier || 0) * 100 + Number(t.step || 0);
      if (!deepest || rank > deepest.rank) deepest = {rank, tier: t.tier, step: t.step};
    });
    if ($("l1r-date")) $("l1r-date").textContent = x.today || "—";
    if ($("l1r-bets")) $("l1r-bets").textContent = fmt(trades.length);
    if ($("l1r-wr")) $("l1r-wr").textContent = trades.length ? ((wins / trades.length) * 100).toFixed(1) + "%" : "0%";
    if ($("l1r-pnl")) {
      $("l1r-pnl").textContent = (pnl >= 0 ? "+" : "") + fmt(pnl) + " MMK";
      $("l1r-pnl").classList.toggle("green", pnl > 0);
      $("l1r-pnl").classList.toggle("red", pnl < 0);
    }
    if ($("l1r-staked")) $("l1r-staked").textContent = fmt(staked) + " MMK";
    if ($("l1r-wl")) $("l1r-wl").textContent = wins + " / " + losses;
    if ($("l1r-depth")) $("l1r-depth").textContent = deepest ? "T" + deepest.tier + "-S" + deepest.step : "—";
    const total = Number(x.model_total_pnl || 0);
    const milestone = Number(x.withdraw_milestone || 50000);
    const progress = milestone > 0 ? ((total % milestone) + milestone) % milestone : 0;
    if ($("l1r-withdraw")) $("l1r-withdraw").textContent = fmt(progress) + " / " + fmt(milestone);
    if ($("l1r-withdraw-bar")) $("l1r-withdraw-bar").style.width = Math.max(0, Math.min(100, milestone ? progress / milestone * 100 : 0)) + "%";
    if ($("l1r-total")) $("l1r-total").textContent = "MODEL TOTAL " + (total >= 0 ? "+" : "") + fmt(total) + " MMK";
    const last = x.last_trade;
    if ($("l1r-last")) $("l1r-last").textContent = last ? ("LAST " + (last.won ? "WIN" : "LOSS") + " · T" + last.tier + "-S" + last.step + " · " + fmt(last.stake)) : "NO SETTLED TRADE";
  }

  async function refresh() {
    try {
      const r = await fetch("/api/l1-capital", {cache: "no-store"});
      if (r.ok) render(await r.json());
    } catch (_) {}
  }

  refresh();
  setInterval(refresh, 1000);
})();
