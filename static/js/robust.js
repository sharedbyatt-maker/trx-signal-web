(() => {
  "use strict";

  const fmt = (n, digits = 0) => {
    const v = Number(n);
    return Number.isFinite(v)
      ? v.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })
      : "—";
  };

  function ensurePanel() {
    if (document.getElementById("robust-engine-card")) return;
    const main = document.querySelector("main");
    if (!main) return;

    const section = document.createElement("section");
    section.id = "robust-engine-card";
    section.className = "robust-card";
    section.innerHTML = `
      <div class="robust-head">
        <div>
          <div class="robust-title">🛡️ ROBUST SIGNAL ENGINE</div>
          <div class="robust-sub">Frozen causal strategy · independent Paroli / bankroll / risk state</div>
        </div>
        <span id="rb-status" class="rb-status">NO TRADE</span>
      </div>

      <div class="robust-grid">
        <div class="rb-hero">
          <span class="rb-k">ROBUST SIGNAL</span>
          <strong id="rb-signal">NO TRADE</strong>
          <span id="rb-issue" class="rb-muted">waiting for completed history…</span>
        </div>

        <div class="rb-stat"><span>Current Stake</span><b id="rb-stake">—</b></div>
        <div class="rb-stat"><span>Paroli Step</span><b id="rb-step">—</b></div>
        <div class="rb-stat"><span>Daily P/L</span><b id="rb-daypnl">—</b></div>
        <div class="rb-stat"><span>Daily TP</span><b id="rb-tp">—</b></div>
        <div class="rb-stat"><span>Daily SL</span><b id="rb-sl">—</b></div>
        <div class="rb-stat"><span>Robust Bankroll</span><b id="rb-bankroll">—</b></div>
        <div class="rb-stat"><span>Wins</span><b id="rb-wins">0</b></div>
        <div class="rb-stat"><span>Losses</span><b id="rb-losses">0</b></div>
        <div class="rb-stat"><span>Win Rate</span><b id="rb-wr">0%</b></div>
        <div class="rb-stat"><span>Total Trades</span><b id="rb-trades">0</b></div>
        <div class="rb-stat"><span>Current Drawdown</span><b id="rb-dd">—</b></div>
        <div class="rb-stat"><span>True Max Drawdown</span><b id="rb-maxdd">—</b></div>
      </div>

      <div class="rb-detail">
        <span>Score <b id="rb-score">—</b></span>
        <span>Walk RSI <b id="rb-rsi">—</b></span>
        <span>Volatility <b id="rb-vol">—</b></span>
        <span>Daily Date <b id="rb-date">—</b></span>
      </div>

      <div class="rb-audit">
        <div class="rb-audit-head">
          <div>
            <div class="rb-audit-title">Monte Carlo Risk Audit</div>
            <div class="rb-muted">20,000 shuffled locked-test sequences · runs only when requested</div>
          </div>
          <button id="rb-audit-btn" type="button">Run Risk Audit</button>
        </div>
        <div id="rb-audit-state" class="rb-audit-state">Idle</div>
        <div id="rb-audit-results" class="rb-audit-results" hidden></div>
      </div>
    `;
    const slot = document.getElementById("robust-engine-slot");
    if (slot) slot.appendChild(section);
    else main.insertAdjacentElement("afterend", section);

    document.getElementById("rb-audit-btn").addEventListener("click", startAudit);
  }

  function statusClass(status) {
    return "s-" + String(status || "NO TRADE").toLowerCase().replace(/\s+/g, "-");
  }

  function renderStatus(s) {
    ensurePanel();
    const $ = (id) => document.getElementById(id);
    if (!$("robust-engine-card")) return;

    $("rb-signal").textContent = s.signal || "NO TRADE";
    $("rb-status").textContent = s.status || "NO TRADE";
    $("rb-status").className = "rb-status " + statusClass(s.status);
    $("rb-signal").className = statusClass(s.signal);

    const pending = s.pending || {};
    const target = pending.target_issue || "";
    $("rb-issue").textContent = target
      ? `Target issue …${String(target).slice(-8)}`
      : `Last completed …${String(s.last_processed_issue || "—").slice(-8)}`;

    $("rb-stake").textContent = `${fmt(s.current_stake)} MMK`;
    $("rb-step").textContent = `${Number(s.paroli_step || 0) + 1} / 4`;
    $("rb-daypnl").textContent = `${Number(s.daily_profit || 0) >= 0 ? "+" : ""}${fmt(s.daily_profit)} MMK`;
    $("rb-tp").textContent = `+${fmt(s.daily_tp)} MMK`;
    $("rb-sl").textContent = `-${fmt(s.daily_sl)} MMK`;
    $("rb-bankroll").textContent = `${fmt(s.bankroll)} MMK`;
    $("rb-wins").textContent = fmt(s.wins);
    $("rb-losses").textContent = fmt(s.losses);
    $("rb-wr").textContent = `${fmt(s.win_rate, 2)}%`;
    $("rb-trades").textContent = fmt(s.total_trades);
    $("rb-dd").textContent = `${fmt(s.current_drawdown)} MMK`;
    $("rb-maxdd").textContent = `${fmt(s.max_drawdown)} MMK`;
    $("rb-score").textContent = fmt(s.score, 2);
    $("rb-rsi").textContent = fmt(s.walk_rsi, 2);
    $("rb-vol").textContent = fmt(s.vol, 2);
    $("rb-date").textContent = s.daily_date || "—";
  }

  async function refreshStatus() {
    try {
      const r = await fetch("/api/robust-engine/status", { cache: "no-store" });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      renderStatus(await r.json());
    } catch (e) {
      ensurePanel();
      const el = document.getElementById("rb-status");
      if (el) {
        el.textContent = "OFFLINE";
        el.className = "rb-status s-offline";
      }
    }
  }

  function renderAudit(a) {
    ensurePanel();
    const state = document.getElementById("rb-audit-state");
    const btn = document.getElementById("rb-audit-btn");
    const box = document.getElementById("rb-audit-results");
    if (!state || !btn || !box) return;

    btn.disabled = !!a.running;
    btn.textContent = a.running ? "Audit Running…" : "Run Risk Audit";

    if (a.running) {
      state.textContent = `${a.stage || "running"} · ${fmt(a.progress)}%`;
    } else if (a.error) {
      state.textContent = `Audit failed: ${a.error}`;
    } else if (a.stage === "complete" && a.result) {
      state.textContent = `Completed · ${fmt(a.runs)} runs`;
    } else {
      state.textContent = "Idle";
    }

    const mc = a.result && a.result.monte_carlo;
    if (!mc) {
      box.hidden = true;
      return;
    }

    box.hidden = false;
    box.innerHTML = `
      <div><span>Median Ending Balance</span><b>${fmt(mc.median_end)} MMK</b></div>
      <div><span>5th percentile Ending Balance</span><b>${fmt(mc.p05_end)} MMK</b></div>
      <div><span>1st percentile Ending Balance</span><b>${fmt(mc.p01_end)} MMK</b></div>
      <div><span>Worst Ending Balance</span><b>${fmt(mc.worst_end)} MMK</b></div>
      <div><span>Median Max DD</span><b>${fmt(mc.median_dd)} MMK</b></div>
      <div><span>95th percentile Max DD</span><b>${fmt(mc.p95_dd)} MMK</b></div>
      <div><span>99th percentile Max DD</span><b>${fmt(mc.p99_dd)} MMK</b></div>
      <div><span>Worst Max DD</span><b>${fmt(mc.worst_dd)} MMK</b></div>
      <div><span>P(End below initial capital)</span><b>${fmt(mc.p_loss, 2)}%</b></div>
      <div><span>P(Bust)</span><b>${fmt(mc.p_bust, 2)}%</b></div>
      <div><span>P(Max DD &gt; 20%)</span><b>${fmt(mc.p_dd20, 2)}%</b></div>
      <div><span>P(Max DD &gt; 30%)</span><b>${fmt(mc.p_dd30, 2)}%</b></div>
    `;
  }

  async function refreshAudit() {
    try {
      const r = await fetch("/api/robust-engine/audit", { cache: "no-store" });
      if (r.ok) renderAudit(await r.json());
    } catch (_) {}
  }

  async function startAudit() {
    const btn = document.getElementById("rb-audit-btn");
    const state = document.getElementById("rb-audit-state");
    const token = window.prompt("Robust Risk Audit admin token:");
    if (!token) {
      if (state) state.textContent = "Audit cancelled.";
      return;
    }

    if (btn) btn.disabled = true;
    try {
      const r = await fetch("/api/robust-engine/audit", {
        method: "POST",
        headers: { "X-Robust-Audit-Token": token }
      });
      const body = await r.json();
      if (!r.ok) {
        if (state) state.textContent = body.error || `Audit request denied (HTTP ${r.status})`;
        if (btn) btn.disabled = false;
        return;
      }
      renderAudit(body);
    } catch (e) {
      if (state) state.textContent = `Could not start audit: ${e.message}`;
      if (btn) btn.disabled = false;
    }
  }

  ensurePanel();
  refreshStatus();
  refreshAudit();
  setInterval(refreshStatus, 2000);
  setInterval(refreshAudit, 3000);
})();
