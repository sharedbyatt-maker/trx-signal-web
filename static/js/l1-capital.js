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
