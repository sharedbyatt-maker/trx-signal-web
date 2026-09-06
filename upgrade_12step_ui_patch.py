from pathlib import Path

# ---------------- app_core.py ----------------
p = Path('app_core.py')
s = p.read_text(encoding='utf-8')

old = '''def _strat_daily_snapshot(day=None, days=7):
    today = day or datetime.now().strftime("%Y-%m-%d")
    with strat_daily_lock:
        keys = sorted(strat_daily_reports.keys(), reverse=True)
        if today not in strat_daily_reports:
            current = _empty_strat_daily(today)
        else:
            current = dict(strat_daily_reports[today])
        history = [dict(strat_daily_reports[k]) for k in keys if k != today][:max(0, days-1)]
    for r in [current] + history:
        n = int(r.get("settled_bets", 0)); ew = int(r.get("episode_wins", 0)); er = int(r.get("episodes_resolved", 0))
        r["bet_win_rate"] = round(int(r.get("bet_wins",0))*100/n, 2) if n else 0.0
        r["episode_win_rate"] = round(ew*100/er, 2) if er else 0.0
        r.pop("event_ids", None)
    return current, history
'''
new = '''def _enrich_strat_daily_report(report):
    """Add display-only performance metrics without changing 12-step accounting."""
    r = dict(report or {})
    n = int(r.get("settled_bets", 0))
    wins = int(r.get("bet_wins", 0))
    ew = int(r.get("episode_wins", 0))
    er = int(r.get("episodes_resolved", 0))
    signals = int(r.get("signals", 0))
    staked = int(r.get("total_staked", 0))
    net = int(r.get("net_pnl", 0))
    break_even = 100.0 / STAKE_PAYOUT
    bet_wr = (wins * 100.0 / n) if n else 0.0
    r["bet_win_rate"] = round(bet_wr, 2)
    r["episode_win_rate"] = round(ew * 100.0 / er, 2) if er else 0.0
    r["roi_pct"] = round(net * 100.0 / staked, 2) if staked else 0.0
    r["avg_stake"] = round(staked / n) if n else 0
    r["avg_pnl_per_bet"] = round(net / n) if n else 0
    r["avg_pnl_per_episode"] = round(net / er) if er else 0
    r["open_episodes"] = max(0, signals - er)
    r["break_even_win_rate"] = round(break_even, 2)
    r["edge_vs_break_even"] = round(bet_wr - break_even, 2) if n else 0.0
    r.pop("event_ids", None)
    return r


def _strat_daily_snapshot(day=None, days=7):
    today = day or datetime.now().strftime("%Y-%m-%d")
    with strat_daily_lock:
        keys = sorted(strat_daily_reports.keys(), reverse=True)
        if today not in strat_daily_reports:
            current = _empty_strat_daily(today)
        else:
            current = dict(strat_daily_reports[today])
        history = [dict(strat_daily_reports[k]) for k in keys if k != today][:max(0, days-1)]
    current = _enrich_strat_daily_report(current)
    history = [_enrich_strat_daily_report(r) for r in history]
    return current, history
'''
if old not in s:
    raise SystemExit('daily snapshot target not found')
s = s.replace(old, new)

old = '''def format_strat_daily_telegram(report):
    status = "🟢 PROFIT" if report.get("net_pnl",0) > 0 else ("🔴 LOSS" if report.get("net_pnl",0) < 0 else "⚪ FLAT")
    return (
        "[12-STEP ENGINE]\\n📊 DAILY REPORT\\n\\n"
        f"Date: {report.get('date')}\\nStatus: {status}\\n"
        f"Signals: {report.get('signals',0)}\\n"
        f"Settled Bets: {report.get('settled_bets',0)} · W {report.get('bet_wins',0)} / L {report.get('bet_losses',0)} "
        f"({report.get('bet_win_rate',0):.1f}% WR)\\n"
        f"Resolved Episodes: {report.get('episodes_resolved',0)} · Wins {report.get('episode_wins',0)} · "
        f"Tier Failed {report.get('tier_failed',0)} · Busts {report.get('busts',0)}\\n\\n"
        f"Total Staked: {int(report.get('total_staked',0)):,} MMK\\n"
        f"Total Returned: {int(report.get('total_returned',0)):,} MMK\\n"
        f"NET P/L: {int(report.get('net_pnl',0)):+,} MMK\\n"
        f"Max Stake: {int(report.get('max_stake',0)):,} MMK\\n"
        f"Deepest: Tier {report.get('max_tier',1)} / Step {report.get('max_step',1)}\\n\\n"
        "Report basis: actual 12-step live settlements only."
    )
'''
new = '''def format_strat_daily_telegram(report):
    report = _enrich_strat_daily_report(report)
    status = "🟢 PROFIT" if report.get("net_pnl",0) > 0 else ("🔴 LOSS" if report.get("net_pnl",0) < 0 else "⚪ FLAT")
    edge = float(report.get("edge_vs_break_even", 0.0))
    return (
        "[12-STEP ENGINE]\\n📊 DAILY REPORT — FINAL\\n\\n"
        f"Date: {report.get('date')}\\nStatus: {status}\\n"
        f"Signals: {report.get('signals',0)} · Open Episodes: {report.get('open_episodes',0)}\\n"
        f"Settled Bets: {report.get('settled_bets',0)} · W {report.get('bet_wins',0)} / L {report.get('bet_losses',0)} "
        f"({report.get('bet_win_rate',0):.1f}% WR)\\n"
        f"Episode WR: {report.get('episode_win_rate',0):.1f}% · Resolved {report.get('episodes_resolved',0)} "
        f"/ Wins {report.get('episode_wins',0)}\\n"
        f"Tier Failed: {report.get('tier_failed',0)} · 12-Step Busts: {report.get('busts',0)}\\n\\n"
        f"Total Staked: {int(report.get('total_staked',0)):,} MMK\\n"
        f"Total Returned: {int(report.get('total_returned',0)):,} MMK\\n"
        f"NET P/L: {int(report.get('net_pnl',0)):+,} MMK\\n"
        f"ROI on Staked: {report.get('roi_pct',0):+.1f}%\\n"
        f"Avg Stake / Bet: {int(report.get('avg_stake',0)):,} MMK\\n"
        f"Avg P/L / Episode: {int(report.get('avg_pnl_per_episode',0)):+,} MMK\\n\\n"
        f"Break-even WR @ 1.96x: {report.get('break_even_win_rate',0):.1f}%\\n"
        f"Edge vs Break-even: {edge:+.1f} pp\\n"
        f"Max Stake: {int(report.get('max_stake',0)):,} MMK\\n"
        f"Deepest: Tier {report.get('max_tier',1)} / Step {report.get('max_step',1)}\\n\\n"
        "Report basis: actual 12-step live settlements only."
    )
'''
if old not in s:
    raise SystemExit('daily telegram formatter target not found')
s = s.replace(old, new)

old = '''        snap = dict(r)
        n=int(snap.get("settled_bets",0)); er=int(snap.get("episodes_resolved",0))
        snap["bet_win_rate"] = round(int(snap.get("bet_wins",0))*100/n,2) if n else 0.0
        snap["episode_win_rate"] = round(int(snap.get("episode_wins",0))*100/er,2) if er else 0.0
        r["telegram_sent"] = True
'''
new = '''        snap = _enrich_strat_daily_report(r)
        r["telegram_sent"] = True
'''
if old not in s:
    raise SystemExit('previous daily telegram enrichment target not found')
s = s.replace(old, new)

old = '''                            strat_pending = {
                                "issue": next_issue,
                                "short_issue": next_issue[-6:] if len(next_issue) >= 6 else next_issue,
                                "target": strat_signal,
                                "tier": strat_state["tier"],
                                "step": strat_state["step"],
                                "stake": stake_amt,
                                "bets": 0, "staked": 0, "returned": 0,
                                "net": 0, "win_step": None, "resolved": False,
                                "outcome": "PENDING",
                            }
'''
new = '''                            trigger_rsi = round(float(rsi_prev_s), 1) if rsi_prev_s is not None else None
                            trigger_rule = (
                                f"Prev RSI ≤ {RSI_STRAT_OVERSOLD:g} + BIG confirm"
                                if strat_signal == "BIG" else
                                f"Prev RSI ≥ {RSI_STRAT_OVERBOUGHT:g} + SMALL confirm"
                            )
                            strat_pending = {
                                "issue": next_issue,
                                "short_issue": next_issue[-6:] if len(next_issue) >= 6 else next_issue,
                                "target": strat_signal,
                                "tier": strat_state["tier"],
                                "step": strat_state["step"],
                                "stake": stake_amt,
                                "bets": 0, "staked": 0, "returned": 0,
                                "net": 0, "win_step": None, "resolved": False,
                                "outcome": "PENDING",
                                # Display-only setup context; strategy logic above is unchanged.
                                "trigger_rsi": trigger_rsi,
                                "trigger_rule": trigger_rule,
                                "confirm_type": t_cur_s,
                                "source_issue": latest["issue"],
                                "source_short_issue": latest["short_issue"],
                                "source_time": latest.get("block_time", ""),
                                "armed_at": now,
                            }
'''
if old not in s:
    raise SystemExit('strat pending creation target not found')
s = s.replace(old, new)

old = '''                            strat_state["pending"] = {
                                "target": strat_signal,
                                "tier": strat_state["tier"] + 1,
                                "step": strat_state["step"] + 1,
                                "stake": stake_amt,
                                "issue": strat_pending["issue"],
                            }
                            tg_notify(
                                f"🎯 12-STEP SIGNAL — {strat_signal}\\n"
                                f"Tier {strat_state['tier']+1} · Step {strat_state['step']+1}\\n"
                                f"Stake: {stake_amt:,} MMK\\n"
                                f"Issue …{strat_pending['short_issue']}")
'''
new = '''                            strat_state["pending"] = {
                                "target": strat_signal,
                                "tier": strat_state["tier"] + 1,
                                "step": strat_state["step"] + 1,
                                "stake": stake_amt,
                                "issue": strat_pending["issue"],
                                "trigger_rsi": trigger_rsi,
                                "trigger_rule": trigger_rule,
                                "confirm_type": t_cur_s,
                                "source_issue": latest["issue"],
                                "source_short_issue": latest["short_issue"],
                                "source_time": latest.get("block_time", ""),
                                "armed_at": now,
                            }
                            tg_notify(
                                f"🎯 12-STEP SIGNAL — {strat_signal}\\n\\n"
                                f"Target Issue: …{strat_pending['short_issue']}\\n"
                                f"Tier {strat_state['tier']+1} · Step {strat_state['step']+1}\\n"
                                f"Stake: {stake_amt:,} MMK\\n"
                                f"Trigger RSI: {trigger_rsi:.1f}\\n"
                                f"Setup: {trigger_rule}\\n"
                                f"Confirmed By: …{latest['short_issue']} · {latest['type']}\\n"
                                f"Source Time: {latest.get('block_time','')}\\n\\n"
                                "Status: 🟢 ARMED — waiting for target issue settlement")
'''
if old not in s:
    raise SystemExit('strat state pending / telegram target not found')
s = s.replace(old, new)

old = '''                                    strat_state["pending"] = {
                                        "target": sp["target"],
                                        "tier": sp["tier"] + 1,
                                        "step": strat_state["step"] + 1,
                                        "stake": next_stake,
                                        "issue": sp["issue"],
                                    }
'''
new = '''                                    strat_state["pending"] = {
                                        "target": sp["target"],
                                        "tier": sp["tier"] + 1,
                                        "step": strat_state["step"] + 1,
                                        "stake": next_stake,
                                        "issue": sp["issue"],
                                        "trigger_rsi": sp.get("trigger_rsi"),
                                        "trigger_rule": sp.get("trigger_rule"),
                                        "confirm_type": sp.get("confirm_type"),
                                        "source_issue": sp.get("source_issue"),
                                        "source_short_issue": sp.get("source_short_issue"),
                                        "source_time": sp.get("source_time"),
                                        "armed_at": sp.get("armed_at"),
                                    }
'''
if old not in s:
    raise SystemExit('ladder pending sync target not found')
s = s.replace(old, new)

old = '''                                event={"issue": next_issue, "target": strat_signal, "tier": strat_state["tier"]+1,
                                       "step": strat_state["step"]+1, "stake": stake_amt, "outcome": "SIGNAL"},
'''
new = '''                                event={"issue": next_issue, "target": strat_signal, "tier": strat_state["tier"]+1,
                                       "step": strat_state["step"]+1, "stake": stake_amt, "outcome": "SIGNAL",
                                       "trigger_rsi": trigger_rsi, "source_issue": latest["issue"]},
'''
if old not in s:
    raise SystemExit('daily signal event target not found')
s = s.replace(old, new)

old = '''    current["engine"] = {
        "tier": int(st.get("tier",0))+1, "step": int(st.get("step",0))+1,
        "pending": pend, "last_result": st.get("last_result"),
    }
'''
new = '''    tier_idx = max(0, min(int(st.get("tier", 0)), len(STAKE_TIERS) - 1))
    step_idx = max(0, min(int(st.get("step", 0)), len(STAKE_TIERS[tier_idx]) - 1))
    current["engine"] = {
        "tier": tier_idx + 1,
        "step": step_idx + 1,
        "pending": pend,
        "last_result": st.get("last_result"),
        "status": "ACTIVE" if pend else "WAITING",
        "next_eligible_stake": int(STAKE_TIERS[tier_idx][step_idx]),
        "signals_session": int(st.get("signals", 0)),
        "busts_session": int(st.get("busts", 0)),
        "rules": {
            "rsi_low": RSI_STRAT_OVERSOLD,
            "rsi_high": RSI_STRAT_OVERBOUGHT,
            "payout": STAKE_PAYOUT,
        },
    }
'''
if old not in s:
    raise SystemExit('daily api engine target not found')
s = s.replace(old, new)

p.write_text(s, encoding='utf-8')

# ---------------- templates/index.html ----------------
p = Path('templates/index.html')
s = p.read_text(encoding='utf-8')
old = '''      <div class="stake-panel mono" id="stake-panel">
        <div class="stake-title-row">
          <span class="stake-title">🎰 12-STEP ENGINE</span>
          <span class="stake-badge" id="st-tier">T1</span>
          <span class="stake-badge" id="st-step">S1</span>
        </div>
        <div class="stake-strip"><span class="stake-k">SIGNAL</span><span id="st-pending">—</span></div>
        <div class="stake-strip"><span class="stake-k">STAKE</span><span id="st-stake">—</span></div>
        <div class="stake-strip"><span class="stake-k">LAST</span><span id="st-last">waiting…</span></div>
        <div class="stake-strip"><span class="stake-k">BUSTS</span><span id="st-busts">0</span></div>
      </div>
'''
new = '''      <div class="stake-panel mono" id="stake-panel">
        <div class="stake-title-row">
          <span class="stake-title">🎰 12-STEP ENGINE</span>
          <span class="stake-mode waiting" id="st-status">WAITING</span>
          <span class="stake-badge" id="st-tier">T1</span>
          <span class="stake-badge" id="st-step">S1</span>
        </div>
        <div class="stake-signal-hero" id="st-signal-hero">
          <span class="stake-hero-dir" id="st-pending">waiting for valid setup…</span>
          <span class="stake-hero-issue" id="st-target-issue">NO ACTIVE TARGET</span>
        </div>
        <div class="stake-detail-grid">
          <div><small>STAKE</small><b id="st-stake">—</b></div>
          <div><small>TRIGGER</small><b id="st-trigger">RSI 32 / 68</b></div>
          <div><small>CONFIRM SOURCE</small><b id="st-source">—</b></div>
          <div><small>LAST RESULT</small><b id="st-last">waiting…</b></div>
        </div>
        <div class="stake-foot"><span>12-STEP BUSTS <b id="st-busts">0</b></span><span id="st-rule">Prev RSI ≤32 + BIG / ≥68 + SMALL</span></div>
      </div>
'''
if old not in s:
    raise SystemExit('stake template target not found')
s = s.replace(old, new)

old = '''      <div class="daily12-panel mono" id="daily12-panel">
        <div class="daily12-head"><span>📊 12-STEP DAILY REPORT</span><span id="d12-date">—</span></div>
        <div class="daily12-grid">
          <div><small>SIGNALS</small><b id="d12-signals">0</b></div>
          <div><small>BET W/L</small><b id="d12-wl">0 / 0</b></div>
          <div><small>WIN RATE</small><b id="d12-wr">0%</b></div>
          <div><small>NET P/L</small><b id="d12-pnl">0 MMK</b></div>
          <div><small>STAKED</small><b id="d12-staked">0</b></div>
          <div><small>RETURNED</small><b id="d12-returned">0</b></div>
        </div>
        <div class="daily12-line" id="d12-episodes">Episodes —</div>
        <div class="daily12-line" id="d12-depth">Deepest —</div>
        <div class="daily12-line" id="d12-status">Engine —</div>
        <div class="daily12-history" id="d12-history"></div>
      </div>
'''
new = '''      <div class="daily12-panel mono" id="daily12-panel">
        <div class="daily12-head"><span>📊 12-STEP DAILY REPORT</span><span id="d12-date">—</span></div>
        <div class="daily12-grid">
          <div><small>SIGNALS</small><b id="d12-signals">0</b></div>
          <div><small>BET W / L</small><b id="d12-wl">0 / 0</b></div>
          <div><small>BET WIN RATE</small><b id="d12-wr">0%</b></div>
          <div><small>EPISODE WR</small><b id="d12-episode-wr">0%</b></div>
          <div class="daily12-focus"><small>NET P/L</small><b id="d12-pnl">0 MMK</b></div>
          <div><small>ROI ON STAKED</small><b id="d12-roi">0%</b></div>
          <div><small>TOTAL STAKED</small><b id="d12-staked">0</b></div>
          <div><small>TOTAL RETURNED</small><b id="d12-returned">0</b></div>
          <div><small>AVG STAKE / BET</small><b id="d12-avg-stake">0</b></div>
          <div><small>OPEN EPISODES</small><b id="d12-open">0</b></div>
        </div>
        <div class="daily12-section-title">SESSION QUALITY</div>
        <div class="daily12-line" id="d12-episodes">Episodes —</div>
        <div class="daily12-line" id="d12-depth">Deepest —</div>
        <div class="daily12-line" id="d12-edge">Break-even —</div>
        <div class="daily12-line daily12-engine" id="d12-status">Engine —</div>
        <div class="daily12-line daily12-updated" id="d12-updated">Updated —</div>
        <div class="daily12-section-title">RECENT ACTIVITY</div>
        <div class="daily12-activity" id="d12-activity"></div>
        <div class="daily12-section-title">PREVIOUS DAYS</div>
        <div class="daily12-history" id="d12-history"></div>
      </div>
'''
if old not in s:
    raise SystemExit('daily template target not found')
s = s.replace(old, new)
s = s.replace("js/daily12.js') }}?v=1", "js/daily12.js') }}?v=2")
s = s.replace("css/style.css') }}?v=42", "css/style.css') }}?v=43")
p.write_text(s, encoding='utf-8')

# ---------------- static/js/app.js ----------------
p = Path('static/js/app.js')
s = p.read_text(encoding='utf-8')
old = '''  /* ---- 🎰 12-step staking panel ---- */
  const st = s.strat || {};
  {
    const tierEl = $("st-tier"), stepEl = $("st-step");
    if (tierEl) {
      tierEl.textContent = "T" + ((st.tier || 0) + 1);
      tierEl.className = "stake-badge" + ((st.tier || 0) > 0 ? " hot" : "");
    }
    if (stepEl) stepEl.textContent = "S" + ((st.step || 0) + 1);
    const pend = s.strat_pending || st.pending;
    const pEl = $("st-pending");
    if (pEl) {
      if (pend) {
        pEl.innerHTML = `<b class="${pend.target === "BIG" ? "red" : "blue"}">${pend.target}</b> → issue …${String(pend.issue).slice(-6)}`;
      } else pEl.textContent = "waiting for signal…";
    }
    const skEl = $("st-stake");
    if (skEl) skEl.textContent = pend ? `${pend.stake.toLocaleString("en-US")} MMK` : "—";
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
      lastEl.innerHTML = `<b class="${cls}">${lt.outcome}</b> T${lt.tier} · net ${lt.net >= 0 ? "+" : ""}${lt.net.toLocaleString("en-US")}`;
    }
  }
'''
new = '''  /* ---- 🎰 12-step staking panel (display-only detail; strategy unchanged) ---- */
  const st = s.strat || {};
  {
    const tierEl = $("st-tier"), stepEl = $("st-step");
    if (tierEl) {
      tierEl.textContent = "T" + ((st.tier || 0) + 1);
      tierEl.className = "stake-badge" + ((st.tier || 0) > 0 ? " hot" : "");
    }
    if (stepEl) stepEl.textContent = "S" + ((st.step || 0) + 1);

    const pend = s.strat_pending || st.pending;
    const modeEl = $("st-status");
    const pEl = $("st-pending");
    const issueEl = $("st-target-issue");
    const skEl = $("st-stake");
    const trigEl = $("st-trigger");
    const srcEl = $("st-source");
    const hero = $("st-signal-hero");

    if (pend) {
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
      if (modeEl) { modeEl.textContent = "WAITING"; modeEl.className = "stake-mode waiting"; }
      if (pEl) { pEl.textContent = "WAITING"; pEl.className = "stake-hero-dir"; }
      if (issueEl) issueEl.textContent = "NO ACTIVE TARGET";
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
'''
if old not in s:
    raise SystemExit('app.js 12-step render target not found')
s = s.replace(old, new)
p.write_text(s, encoding='utf-8')

# ---------------- static/js/daily12.js ----------------
p = Path('static/js/daily12.js')
p.write_text(r'''(() => {
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
      if(x.ok) render(await x.json());
    } catch(_e) {}
  }
  refresh();
  setInterval(refresh, 10000);
})();
''', encoding='utf-8')

# ---------------- static/css/daily12.css ----------------
p = Path('static/css/daily12.css')
p.write_text(r'''.daily12-panel{margin-top:12px;padding:13px;border:1px solid rgba(120,130,150,.28);border-radius:11px;background:rgba(15,20,30,.48)}
.daily12-head{display:flex;justify-content:space-between;gap:8px;font-weight:800;font-size:12px;margin-bottom:11px;letter-spacing:.5px}
.daily12-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.daily12-grid>div{padding:9px;border-radius:8px;background:rgba(255,255,255,.038);display:flex;flex-direction:column;gap:4px;min-width:0}.daily12-grid small{opacity:.58;font-size:8.5px;letter-spacing:.8px}.daily12-grid b{font-size:11px;overflow-wrap:anywhere}.daily12-grid .daily12-focus{background:rgba(8,153,129,.07);border:1px solid rgba(8,153,129,.14)}
.daily12-section-title{margin-top:11px;padding-top:8px;border-top:1px solid rgba(120,130,150,.16);font-size:8px;font-weight:800;letter-spacing:1.2px;opacity:.55}
.daily12-line{font-size:9.5px;opacity:.86;padding-top:6px;line-height:1.5}.daily12-engine{font-weight:700;color:#c9d2e3;opacity:1}.daily12-updated{font-size:8.5px;opacity:.48}.daily12-line.green{color:var(--green);opacity:1}.daily12-line.red{color:var(--red);opacity:1}
.daily12-activity{margin-top:5px;display:flex;flex-direction:column;gap:4px}.d12-activity-row{display:grid;grid-template-columns:auto auto minmax(0,1fr) auto auto;gap:6px;align-items:center;padding:5px 6px;border-radius:6px;background:rgba(255,255,255,.025);font-size:8.5px}.d12-event{font-weight:800;min-width:34px}.d12-empty{padding:6px 0;font-size:8.5px;opacity:.45}
.daily12-history{margin-top:5px}.daily12-history>div{display:grid;grid-template-columns:.9fr 1.45fr .8fr 1fr;gap:6px;padding:5px 0;font-size:8.5px;border-bottom:1px solid rgba(120,130,150,.08)}.daily12-history b{text-align:right}

/* 12-step live signal detail */
.stake-mode{font-size:8px;font-weight:800;letter-spacing:.8px;padding:3px 7px;border-radius:999px;border:1px solid rgba(120,130,150,.28)}.stake-mode.waiting{color:#8d96a8}.stake-mode.active{color:var(--green);border-color:rgba(8,153,129,.38);background:rgba(8,153,129,.09)}
.stake-signal-hero{display:flex;align-items:center;justify-content:space-between;gap:8px;padding:9px 10px;margin:8px 0;border:1px solid rgba(120,130,150,.18);border-radius:8px;background:rgba(255,255,255,.025)}.stake-signal-hero.armed{border-color:rgba(41,98,255,.35);background:rgba(41,98,255,.055)}
.stake-hero-dir{font-size:14px;font-weight:900;letter-spacing:.9px}.stake-hero-issue{font-size:8.5px;opacity:.58;text-align:right}
.stake-detail-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:7px}.stake-detail-grid>div{display:flex;flex-direction:column;gap:3px;padding:6px 7px;background:rgba(255,255,255,.02);border-radius:6px}.stake-detail-grid small{font-size:7.5px;opacity:.48;letter-spacing:.8px}.stake-detail-grid b{font-size:9px;line-height:1.4;overflow-wrap:anywhere}
.stake-foot{display:flex;justify-content:space-between;gap:8px;align-items:center;margin-top:7px;padding-top:6px;border-top:1px solid rgba(120,130,150,.13);font-size:7.5px;opacity:.55}.stake-foot b{font-size:9px}
@media(max-width:700px){.daily12-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.d12-activity-row{grid-template-columns:auto auto minmax(0,1fr);}.d12-activity-row>span:nth-last-child(-n+2){display:none}.daily12-history>div{grid-template-columns:.9fr 1.4fr 1fr}.daily12-history>div span:nth-child(3){display:none}.stake-foot{align-items:flex-start;flex-direction:column}}
''', encoding='utf-8')

# ---------------- tests_daily12.py ----------------
p = Path('tests_daily12.py')
s = p.read_text(encoding='utf-8')
s = s.replace("            assert r['bet_win_rate']==100.0\n", "            assert r['bet_win_rate']==100.0\n            assert r['roi_pct']==96.0 and r['avg_stake']==200\n            assert r['break_even_win_rate']==round(100.0/c.STAKE_PAYOUT,2)\n")
s = s.replace("    assert '[12-STEP ENGINE]' in msg and 'DAILY REPORT' in msg and 'NET P/L: +584 MMK' in msg\n", "    assert '[12-STEP ENGINE]' in msg and 'DAILY REPORT' in msg and 'NET P/L: +584 MMK' in msg\n    assert 'ROI on Staked:' in msg and 'Break-even WR @ 1.96x:' in msg\n")
s = s.replace("    assert 'report' in data and 'history' in data and 'engine' in data['report']\n", "    assert 'report' in data and 'history' in data and 'engine' in data['report']\n    assert 'roi_pct' in data['report'] and 'next_eligible_stake' in data['report']['engine']\n")
p.write_text(s, encoding='utf-8')

# New static contract test ensures richer UI remains wired.
Path('tests_12step_ui_detail.py').write_text(r'''from pathlib import Path

def test_template_ids_and_assets():
    h=Path('templates/index.html').read_text(encoding='utf-8')
    for x in ('st-status','st-trigger','st-source','d12-episode-wr','d12-roi','d12-activity','d12-edge'):
        assert f'id="{x}"' in h, x

def test_js_detail_wiring():
    app=Path('static/js/app.js').read_text(encoding='utf-8')
    daily=Path('static/js/daily12.js').read_text(encoding='utf-8')
    assert 'pend.trigger_rsi' in app and 'pend.trigger_rule' in app
    for x in ('roi_pct','episode_win_rate','edge_vs_break_even','recent_events','next_eligible_stake'):
        assert x in daily, x

def test_strategy_constants_untouched():
    s=Path('app_core.py').read_text(encoding='utf-8')
    assert 'RSI_STRAT_OVERSOLD = 32.0' in s
    assert 'RSI_STRAT_OVERBOUGHT = 68.0' in s
    assert '[200, 400, 600, 1200]' in s
    assert '[2500, 5000, 10000, 20000]' in s
    assert '[40000, 80000, 160000, 320000]' in s

if __name__=='__main__':
    test_template_ids_and_assets(); test_js_detail_wiring(); test_strategy_constants_untouched()
    print('12-STEP UI DETAIL TESTS: ALL PASSED')
''', encoding='utf-8')
