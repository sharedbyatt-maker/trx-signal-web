(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const text = (id, fallback = "—") => {
    const el = $(id);
    return el && el.textContent.trim() ? el.textContent.trim() : fallback;
  };

  function classify(value) {
    const v = String(value || "").toUpperCase();
    if (v.includes("BIG")) return ["is-big", "▲"];
    if (v.includes("SMALL")) return ["is-small", "▼"];
    if (v.includes("ARMED") || v.includes("READY") || v.includes("ACTIVE")) return ["is-ready", "●"];
    if (v.includes("STOP") || v.includes("OFFLINE") || v.includes("BANKROLL")) return ["is-stopped", "!"];
    return ["is-waiting", "◷"];
  }

  function paintState(id, label, value) {
    const el = $(id);
    if (!el) return;
    const [cls, icon] = classify(value);
    el.className = "focus-state " + cls;
    const iconEl = el.querySelector(".focus-state-icon");
    const labelEl = el.querySelector("span:not(.focus-state-icon)");
    const valueEl = el.querySelector("b");
    if (iconEl) iconEl.textContent = icon;
    if (labelEl) labelEl.textContent = label;
    if (valueEl) valueEl.textContent = value || "WAITING";
  }

  function sync() {
    const issue = $("focus-issue");
    if (issue) issue.textContent = text("tk-issue");

    const next = $("focus-next");
    if (next) {
      const raw = text("ctb-next");
      next.textContent = raw.replace(/^NEXT ISSUE ETA:\s*/i, "") || "—";
    }

    const stepMode = text("st-status", "WAITING");
    const stepTarget = text("st-pending", "WAITING");
    paintState("focus-step", "12-STEP", /BIG|SMALL/i.test(stepTarget) ? stepTarget : stepMode);

    const robustValue = text("rb-status", "NO TRADE");
    paintState("focus-robust", "ROBUST", robustValue);

    const conn = $("focus-connection");
    if (conn) {
      const value = text("conn-txt", "OFFLINE");
      const delayed = /DELAY|STALE|LAG/i.test(value);
      const offline = /OFFLINE|ERROR|DISCONNECT/i.test(value) || $("dot")?.classList.contains("off");
      conn.className = "focus-connection " + (offline ? "is-offline" : delayed ? "is-delayed" : "is-live");
      const b = conn.querySelector("b");
      if (b) b.textContent = offline ? "OFFLINE" : delayed ? "DELAYED" : "LIVE";
    }
  }

  const observer = new MutationObserver(sync);
  observer.observe(document.body, { childList: true, subtree: true, characterData: true, attributes: true, attributeFilter: ["class"] });
  sync();
  window.setInterval(sync, 1000);
})();