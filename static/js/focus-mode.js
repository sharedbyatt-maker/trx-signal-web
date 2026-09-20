(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const text = (id, fallback = "—") => {
    const el = $(id);
    return el && el.textContent.trim() ? el.textContent.trim() : fallback;
  };
  const setText = (el, value) => {
    if (el && el.textContent !== value) el.textContent = value;
  };
  const setClass = (el, value) => {
    if (el && el.className !== value) el.className = value;
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
    setClass(el, "focus-state " + cls);
    setText(el.querySelector(".focus-state-icon"), icon);
    setText(el.querySelector("span:not(.focus-state-icon)"), label);
    setText(el.querySelector("b"), value || "WAITING");
  }

  function sync() {
    setText($("focus-issue"), text("tk-issue"));

    const raw = text("ctb-next");
    setText($("focus-next"), raw.replace(/^NEXT ISSUE ETA:\s*/i, "") || "—");

    const stepMode = text("st-status", "WAITING");
    const stepTarget = text("st-pending", "WAITING");
    paintState("focus-step", "12-STEP", /BIG|SMALL/i.test(stepTarget) ? stepTarget : stepMode);

    paintState("focus-l1", "L1 CAPITAL", text("l1-status", "WAITING"));

    const conn = $("focus-connection");
    if (conn) {
      const value = text("conn-txt", "OFFLINE");
      const delayed = /DELAY|STALE|LAG/i.test(value);
      const offline = /OFFLINE|ERROR|DISCONNECT/i.test(value) || $("dot")?.classList.contains("off");
      setClass(conn, "focus-connection " + (offline ? "is-offline" : delayed ? "is-delayed" : "is-live"));
      setText(conn.querySelector("b"), offline ? "OFFLINE" : delayed ? "DELAYED" : "LIVE");
    }
  }

  // Observe only source elements. Observing document.body made sync() react to
  // its own focus-bar writes and could create a MutationObserver feedback loop.
  const observer = new MutationObserver(sync);
  ["tk-issue", "ctb-next", "st-status", "st-pending", "l1-status", "conn-txt", "dot"].forEach((id) => {
    const el = $(id);
    if (el) observer.observe(el, { childList: true, subtree: true, characterData: true, attributes: id === "dot", attributeFilter: id === "dot" ? ["class"] : undefined });
  });
  sync();
  window.setInterval(sync, 1000);
})();