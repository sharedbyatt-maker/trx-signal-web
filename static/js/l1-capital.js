(() => {
  const $ = (id) => document.getElementById(id);
  const fmt = (n) => Number(n || 0).toLocaleString();

  function setState(el, kind) {
    if (!el) return;
    el.classList.remove("waiting", "active", "win", "loss");
    el.classList.add(kind);
  }

  function paintRisk(value) {
    const el = $("l1-risk");
    if (!el) return;
    el.textContent = value;
    el.classList.toggle("is-observe", value !== "TRADE ALLOWED");
  }

  let lastSnapshot = null;
  function render(x, received = true) {
    if (received) { lastSnapshot = x; window.TRXContext?.onL1(x); }
    const p = window.TRXContext?.isValidTarget(x?.pending) ? x.pending : null;
    const ready = !!(x && x.ready && window.TRXContext?.isL1Ready());
    const status = $("l1-status");
    const focus = $("focus-l1");
    $("l1-signal-hero")?.classList.toggle("has-target", ready && !!p);

    if (!ready) {
      const label = x && x.stale ? (x.feed_status || "STALE") : x?.ready ? "SYNCING" : "WAITING";
      if (status) { status.textContent = label; setState(status, "waiting"); }
      if ($("l1-pending")) $("l1-pending").textContent = label;
      ["l1-stake", "l1-tier", "l1-step"].forEach(id => { if ($(id)) $(id).textContent = "—"; });
      paintRisk("OBSERVE ONLY · " + label);
      if ($("l1-target-issue")) $("l1-target-issue").textContent = (x && x.error) ? "ENGINE ERROR" : (x && x.stale ? "NO VALID SIGNAL · " + label : "NO ACTIVE TARGET");
      if (focus) {
        focus.className = "focus-state is-waiting";
        const b = focus.querySelector("b"); if (b) b.textContent = label;
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
      ["l1-stake", "l1-tier", "l1-step"].forEach(id => { if ($(id)) $(id).textContent = "—"; });
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
    paintRisk(x.risk_status || "TRADE ALLOWED");

    const trades = Array.isArray(x.trades) ? x.trades.filter(t => String(t.time || "").slice(0, 10) === String(x.today || "")) : [];
    const wins = trades.filter(t => t.won).length;
    const losses = trades.length - wins;
    const staked = trades.reduce((sum, t) => sum + Number(t.stake || 0), 0);
    let deepest = null;
    trades.forEach(t => {
      const rank = Number(t.tier || 0) * 100 + Number(t.step || 0);
      if (!deepest || rank > deepest.rank) deepest = {rank, tier: t.tier, step: t.step};
    });
    const summary = x.daily_summary || {
      bets: trades.length, wins, losses,
      win_rate: trades.length ? wins / trades.length * 100 : 0,
      staked, max_tier: deepest && deepest.tier, max_step: deepest && deepest.step,
    };
    if ($("l1r-date")) $("l1r-date").textContent = x.today || "—";
    if ($("l1r-bets")) $("l1r-bets").textContent = fmt(summary.bets);
    if ($("l1r-wr")) $("l1r-wr").textContent = Number(summary.bets) ? Number(summary.win_rate).toFixed(1) + "%" : "0%";
    if ($("l1r-pnl")) {
      $("l1r-pnl").textContent = (pnl >= 0 ? "+" : "") + fmt(pnl) + " MMK";
      $("l1r-pnl").classList.toggle("green", pnl > 0);
      $("l1r-pnl").classList.toggle("red", pnl < 0);
    }
    if ($("l1r-staked")) $("l1r-staked").textContent = fmt(summary.staked) + " MMK";
    if ($("l1r-wl")) $("l1r-wl").textContent = summary.wins + " / " + summary.losses;
    if ($("l1r-depth")) $("l1r-depth").textContent = summary.max_tier ? "T" + summary.max_tier + "-S" + summary.max_step : "—";
    const total = Number(x.model_total_pnl || 0);
    const milestone = Number(x.withdraw_milestone || 50000);
    const reachedFromTotal = milestone > 0 ? Math.floor(Math.max(0, total) / milestone) : 0;
    const reached = Math.max(0, Number.isFinite(Number(x.withdraw_milestones_reached))
      ? Number(x.withdraw_milestones_reached)
      : reachedFromTotal);
    const progress = milestone > 0
      ? Math.max(0, Math.min(milestone, Math.max(0, total) - reached * milestone))
      : 0;
    if ($("l1r-withdraw")) $("l1r-withdraw").textContent = fmt(progress) + " / " + fmt(milestone);
    if ($("l1r-withdraw-bar")) $("l1r-withdraw-bar").style.width = Math.max(0, Math.min(100, milestone ? progress / milestone * 100 : 0)) + "%";
    if ($("l1r-total")) $("l1r-total").textContent = "MODEL TOTAL " + (total >= 0 ? "+" : "") + fmt(total) + " MMK";
    const last = x.last_trade;
    if ($("l1r-last")) $("l1r-last").textContent = last ? ("LAST " + (last.won ? "WIN" : "LOSS") + " · T" + last.tier + "-S" + last.step + " · " + fmt(last.stake)) : "NO SETTLED TRADE";
  }

  let refreshing = false;
  async function refresh() {
    if (refreshing) return;
    refreshing = true;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 6000);
    try {
      const r = await fetch("/api/l1-capital", {cache: "no-store", signal: controller.signal});
      if (!r.ok) throw new Error("HTTP " + r.status);
      const x = await r.json();
      if (!x || typeof x !== "object" || Array.isArray(x)) throw new Error("Invalid L1 response");
      render(x);
    } catch (_) {
      render({ready: false, stale: true, feed_status: "OFFLINE"});
    } finally {
      clearTimeout(timeout);
      refreshing = false;
    }
  }

  refresh();
  setInterval(refresh, 1000);
  setInterval(() => { if (lastSnapshot) render(lastSnapshot, false); }, 1000);
})();
