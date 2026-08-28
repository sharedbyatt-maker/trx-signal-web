/* Manual Trading Drawing Tools — overlay canvas for Lightweight Charts v4
   Tools: Trend Line · Ray · Horizontal S/R · Vertical Line · Rectangle · Fib Retracement
   Features: color picker · drag-to-move · select + delete · undo/clear ·
             touch support · hint bar · localStorage persistence (label-anchored) */
window.TRXDraw = (() => {
  const STORE_KEY = "trx_drawings_v3";   // v3: anchors use FULL issue numbers
  const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  const FIB_COLORS = ["#787b86", "#f23645", "#ff9800", "#089981", "#2962ff", "#ff9800", "#f23645"];
  const HIT_PX = 9;

  let canvas = null;
  let ctx = null;
  let hintEl = null;
  let wrapEl = null;
  let api = null;               // { chart, series, labels }
  let tool = "cursor";
  let color = "#2962ff";
  let drawings = [];
  let placing = null;           // in-progress drawing
  let placeStage = 0;           // 1 = placed A by press, 2 = awaiting second click
  let hover = null;             // {x,y} css px
  let selectedId = null;
  let downXY = null;
  let drag = null;              // { id, start:{x,y}, orig:[{x,y}] }
  let restored = false;

  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  const $ = (id) => document.getElementById(id);

  const HINTS = {
    cursor: "Cursor — line ပေါ်နှိပ် select / ဖိဆွဲ ရွှေ့ · Del = delete · Z = undo",
    trend: "Trend Line — ဖိဆွဲပြီးလွှတ် (သို့) အမှတ်၂ခုနှိပ်",
    ray: "Ray — ဖိဆွဲပြီးလွှတ် (သို့) အမှတ်၂ခုနှိပ် (ညာဆက်ရှည်)",
    hline: "S/R Line — support/resistance level ထဲ တစ်ချက်နှိပ်",
    vline: "Vertical Line — bar ပေါ် တစ်ချက်နှိပ်",
    rect: "Rectangle — ဖိဆွဲပြီးလွှတ် (သို့) corner ၂ခုနှိပ်",
    fib: "Fibonacci — swing high/low ကနေ ဖိဆွဲပြီးလွှတ်",
  };

  /* ================= storage ================= */
  function labelOf(t) {
    /* MUST return the FULL issue (same keys as api.labelMap).
       Short 6-digit suffixes repeat across days → drawings teleported/vanished. */
    return api && api.fulls && api.fulls[t - 1] ? api.fulls[t - 1] : null;
  }

  function save() {
    try {
      const rows = drawings.map((d) => ({
        id: d.id, type: d.type, color: d.color,
        points: d.points.map((p) => ({ p: p.p, lb: p.lb || labelOf(p.t), t: p.t })),
      }));
      localStorage.setItem(STORE_KEY, JSON.stringify(rows));
    } catch (e) { /* noop */ }
  }

  function needPoints(type) {
    return (type === "hline" || type === "vline") ? 1 : 2;
  }

  function labelIndexMap() {
    if (api.labelMap instanceof Map && api.labelMap.size) return api.labelMap;
    if (api.fulls && api.fulls.length) {
      return new Map(api.fulls.map((lb, i) => [lb, i + 1]).filter((x) => x[0]));
    }
    return new Map((api.labels || []).map((lb, i) => [lb, i + 1]));
  }

  function restore() {
    if (!api || !api.labels) return;
    restored = true;
    const map = labelIndexMap();
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
      drawings = [];
      raw.forEach((d) => {
        const pts = [];
        (d.points || []).forEach((p) => {
          let t = null;
          if (p.lb != null && map.has(p.lb)) t = map.get(p.lb);
          else if (p.t != null) t = p.t;   // free-placed / right-margin point
          pts.push({ t, p: p.p, lb: p.lb != null ? p.lb : null });
        });
        if (pts.length >= needPoints(d.type)) {
          drawings.push({
            id: d.id || uid(), type: d.type, color: d.color,
            points: pts.slice(0, needPoints(d.type)),
          });
        }
      });
    } catch (e) {
      drawings = [];
    }
  }

  /* ================= coordinate helpers ================= */
  function toXY(pt) {
    if (!api || pt == null || pt.t == null || pt.t < 1) return null;
    const x = api.chart.timeScale().timeToCoordinate(pt.t);
    const y = api.series.priceToCoordinate(pt.p);
    if (x == null || y == null) return null;
    return { x, y };
  }

  function xOnly(pt) {
    if (!api || pt == null || pt.t == null || pt.t < 1) return null;
    const x = api.chart.timeScale().timeToCoordinate(pt.t);
    return x == null ? null : { x, y: 0 };
  }

  function fromXY(x, y) {
    if (!api || !api.labels || !api.labels.length) return null;
    const ts = api.chart.timeScale();
    const n = api.labels.length;
    const ct = ts.coordinateToTime(x);
    /* allow placing endpoints slightly beyond the last bar (right margin),
       so lines/rays can point into the future like on TradingView */
    let t = (ct == null || isNaN(ct)) ? n : Math.round(ct);
    t = Math.max(1, Math.min(n + 12, t));
    const p = api.series.coordinateToPrice(y);
    if (p == null || isNaN(p)) return null;
    return { t, p };
  }

  function endpoints(d) {
    const a = d.type === "vline" ? xOnly(d.points[0]) : toXY(d.points[0]);
    const b = d.points.length > 1 ? toXY(d.points[1]) : null;
    return { a, b };
  }

  function distSeg(px, py, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y;
    const len2 = dx * dx + dy * dy;
    let t = len2 ? ((px - a.x) * dx + (py - a.y) * dy) / len2 : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (a.x + t * dx), py - (a.y + t * dy));
  }

  function rayEnd(a, b) {
    const w = canvas.clientWidth;
    const dx = b.x - a.x, dy = b.y - a.y;
    const k = dx !== 0 ? (w + 40 - a.x) / dx : Infinity;
    if (k >= 0 && isFinite(k)) return { x: a.x + dx * k, y: a.y + dy * k };
    return b;
  }

  function setHint(txt) {
    if (hintEl) hintEl.textContent = txt;
  }

  /* ================= chart interaction lock ================= */
  function lockChart(lock) {
    if (api) {
      api.chart.applyOptions({ handleScroll: !lock, handleScale: !lock });
    }
    if (wrapEl) {
      wrapEl.style.cursor = lock ? "crosshair" : "";
      wrapEl.classList.toggle("drawing-active", !!lock);
    }
  }

  function setTool(next) {
    if (placing && tool === next) next = "cursor";   // same tool clicked again = cancel
    placing = null;
    placeStage = 0;
    selectedId = null;
    drag = null;
    tool = next;
    document.querySelectorAll(".dt-btn[data-tool]").forEach((b) =>
      b.classList.toggle("active", b.dataset.tool === next));
    lockChart(next !== "cursor");
    setHint(HINTS[next] || HINTS.cursor);
    redraw();
  }

  /* ================= hit testing ================= */
  function hitTest(px, py) {
    const w = canvas.clientWidth;
    for (let i = drawings.length - 1; i >= 0; i--) {
      const d = drawings[i];
      const { a, b } = endpoints(d);
      if (!a) continue;
      if (d.type === "hline") {
        if (Math.abs(py - a.y) <= HIT_PX) return d.id;
      } else if (d.type === "vline") {
        if (Math.abs(px - a.x) <= HIT_PX) return d.id;
      } else if (d.type === "rect") {
        if (!b) continue;
        const x1 = Math.min(a.x, b.x), x2 = Math.max(a.x, b.x);
        const y1 = Math.min(a.y, b.y), y2 = Math.max(a.y, b.y);
        const nearH = Math.abs(py - y1) <= HIT_PX || Math.abs(py - y2) <= HIT_PX;
        const nearV = Math.abs(px - x1) <= HIT_PX || Math.abs(px - x2) <= HIT_PX;
        if ((nearV && py >= y1 - HIT_PX && py <= y2 + HIT_PX) ||
            (nearH && px >= x1 - HIT_PX && px <= x2 + HIT_PX)) return d.id;
      } else if (d.type === "fib") {
        if (!b) continue;
        if (distSeg(px, py, a, b) <= HIT_PX) return d.id;
        for (const lv of FIB_LEVELS) {
          if (Math.abs(py - (a.y + (b.y - a.y) * lv)) <= 4) return d.id;
        }
      } else {  // trend / ray
        if (!b) continue;
        const end = d.type === "ray" ? rayEnd(a, b) : b;
        if (distSeg(px, py, a, end) <= HIT_PX) return d.id;
      }
    }
    return null;
  }

  /* ================= rendering ================= */
  function resize() {
    if (!canvas || !wrapEl) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = wrapEl.clientWidth * dpr;
    canvas.height = wrapEl.clientHeight * dpr;
    canvas.style.width = wrapEl.clientWidth + "px";
    canvas.style.height = wrapEl.clientHeight + "px";
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    redraw();
  }

  function drawLine(a, b, c, width, dash) {
    ctx.strokeStyle = c;
    ctx.lineWidth = width;
    ctx.setLineDash(dash || []);
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  function priceLabel(y, txt, c) {
    const w = canvas.clientWidth;
    ctx.font = "10px Consolas, monospace";
    const tw = ctx.measureText(txt).width + 10;
    ctx.fillStyle = c;
    ctx.globalAlpha = 0.85;
    ctx.fillRect(w - tw - 58, Math.max(0, Math.min(canvas.clientHeight - 16, y - 8)), tw, 16);
    ctx.globalAlpha = 1;
    ctx.fillStyle = "#fff";
    ctx.textBaseline = "middle";
    ctx.fillText(txt, w - tw - 53, Math.max(8, Math.min(canvas.clientHeight - 8, y + 1)));
  }

  function renderOne(d, ghost) {
    const w = canvas.clientWidth;
    const h = canvas.clientHeight;
    const sel = d.id === selectedId && !ghost;
    const c = d.color || "#2962ff";
    const lw = sel ? 3 : 2;
    const { a, b } = endpoints(d);

    if (d.type === "hline" && a) {
      ctx.globalAlpha = 0.12;
      ctx.fillStyle = c;
      ctx.fillRect(0, a.y - 6, w, 12);
      ctx.globalAlpha = 1;
      drawLine({ x: 0, y: a.y }, { x: w, y: a.y }, c, lw);
      priceLabel(a.y, d.points[0].p.toFixed(1), c);
    } else if (d.type === "vline" && a) {
      drawLine({ x: a.x, y: 0 }, { x: a.x, y: h }, c, lw);
    } else if (a && b) {
      if (d.type === "ray") {
        drawLine(a, rayEnd(a, b), c, lw);
      } else if (d.type === "rect") {
        ctx.strokeStyle = c;
        ctx.lineWidth = lw;
        ctx.strokeRect(Math.min(a.x, b.x), Math.min(a.y, b.y),
          Math.abs(b.x - a.x), Math.abs(b.y - a.y));
        ctx.globalAlpha = 0.08;
        ctx.fillStyle = c;
        ctx.fillRect(Math.min(a.x, b.x), Math.min(a.y, b.y),
          Math.abs(b.x - a.x), Math.abs(b.y - a.y));
        ctx.globalAlpha = 1;
      } else if (d.type === "fib") {
        const x1 = Math.min(a.x, b.x), x2 = Math.max(a.x, b.x);
        FIB_LEVELS.forEach((lv, i) => {
          const yy = a.y + (b.y - a.y) * lv;
          const cc = FIB_COLORS[i] || c;
          drawLine({ x: x1, y: yy }, { x: x2 + 60, y: yy }, cc, 1, [5, 4]);
          ctx.font = "10px Consolas, monospace";
          ctx.fillStyle = cc;
          ctx.textBaseline = "bottom";
          ctx.fillText(lv.toFixed(3) + "  " +
            (d.points[0].p + (d.points[1].p - d.points[0].p) * lv).toFixed(1),
            x1 + 4, Math.max(10, yy - 2));
        });
        drawLine(a, b, "rgba(209,212,220,.55)", 1, []);
      } else {
        drawLine(a, b, c, lw);
      }
    }

    [a, b].forEach((pt) => {
      if (!pt) return;
      if (d.type === "fib" && !ghost && !sel) return;
      ctx.fillStyle = sel || ghost ? "#fff" : c;
      ctx.beginPath();
      ctx.arc(pt.x, pt.y, sel || ghost ? 4 : 3, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  function redraw() {
    if (!ctx || !canvas) return;
    ctx.clearRect(0, 0, canvas.clientWidth, canvas.clientHeight);
    if (!api) return;
    drawings.forEach((d) => renderOne(d));
    if (placing) {
      if (hover && placing.points.length === 1) {
        const cur = fromXY(hover.x, hover.y);
        renderOne({ ...placing, id: "_ghost", points: [placing.points[0], cur || placing.points[0]] }, true);
      } else {
        renderOne(placing, true);
      }
    }
  }

  /* ================= actions ================= */
  function commit(type, pts, c) {
    const d = { id: uid(), type, color: c, points: pts };
    d.points.forEach((p) => { p.lb = labelOf(p.t) || p.lb; });
    drawings.push(d);
    selectedId = d.id;
    save();
  }

  function undo() {
    if (placing) { placing = null; redraw(); return; }
    drawings.pop();
    selectedId = null;
    save();
    redraw();
  }

  function clearAll() {
    drawings = [];
    placing = null;
    selectedId = null;
    drag = null;
    save();
    redraw();
  }

  function deleteSelected() {
    if (!selectedId) return;
    drawings = drawings.filter((d) => d.id !== selectedId);
    selectedId = null;
    save();
    redraw();
  }

  /* ================= pointer events ================= */
  function localXY(ev) {
    const r = canvas.getBoundingClientRect();
    return { x: ev.clientX - r.left, y: ev.clientY - r.top };
  }

  function onDown(x, y, ev) {
    downXY = { x, y };
    if (tool === "cursor") {
      const id = hitTest(x, y);
      if (id) {
        selectedId = id;
        const d = drawings.find((z) => z.id === id);
        if (d) {
          const ptsPx = d.points.map((p) => (d.type === "vline" ? xOnly(p) : toXY(p)));
          if (ptsPx.every((q) => q)) {
            drag = { id, start: { x, y }, orig: ptsPx };
            ev.stopPropagation();   // block chart pan while dragging a drawing
          }
        }
        redraw();
      } else if (selectedId) {
        selectedId = null;
        redraw();
      }
      return;
    }
    // two-point tools: start placement on press so press-drag-release works
    if (!placing && tool !== "hline" && tool !== "vline") {
      const pt = fromXY(x, y);
      if (pt) {
        placing = { type: tool, color, points: [{ ...pt, lb: labelOf(pt.t) }] };
        placeStage = 1;
        redraw();
      }
    }
  }

  function onMove(x, y) {
    hover = { x, y };
    if (drag) {
      const d = drawings.find((z) => z.id === drag.id);
      if (!d) { drag = null; return; }
      const dx = x - drag.start.x, dy = y - drag.start.y;
      d.points = drag.orig.map((o, i) => {
        if (d.type === "hline") {
          const p = api.series.coordinateToPrice(o.y + dy);
          return { ...d.points[i], p: (p == null || isNaN(p)) ? d.points[i].p : p };
        }
        const np = fromXY(o.x + dx, d.type === "vline" ? 0 : o.y + dy);
        if (!np) return d.points[i];
        return d.type === "vline"
          ? { ...d.points[i], t: np.t }
          : { t: np.t, p: np.p, lb: d.points[i].lb };
      });
      d.points.forEach((p) => { p.lb = labelOf(p.t) || p.lb; });
      redraw();
      return;
    }
    if (placing && placing.points.length === 1) redraw();
  }

  function finishTwoPoint(pt) {
    placing.points.push({ ...pt, lb: labelOf(pt.t) });
    commit(placing.type, placing.points, placing.color);
    placing = null;
    placeStage = 0;
    setTool("cursor");
    redraw();
  }

  function onUp(x, y) {
    const moved = downXY ? Math.hypot(x - downXY.x, y - downXY.y) : 0;
    if (drag) {
      if (moved > 1) save();
      drag = null;
      downXY = null;
      return;
    }
    const wasDown = !!downXY;
    downXY = null;
    if (tool === "cursor") return;

    const pt = fromXY(x, y);
    if (!pt) { if (placing && moved <= 8) { /* keep placing for click-click */ } return; }

    if (tool === "hline" || tool === "vline") {
      if (!wasDown || moved > 6) return;
      commit(tool, [{ t: pt.t, p: tool === "hline" ? pt.p : 0, lb: labelOf(pt.t) }]);
      setTool("cursor");
      redraw();
      return;
    }

    // two-point tools: hybrid gestures
    if (!placing) return;
    if (moved > 8) {
      // press-drag-release => commit at release point
      finishTwoPoint(pt);
    } else if (placeStage === 1 && wasDown) {
      placeStage = 2;            // first click done — wait for second click
    } else if (placeStage === 2 && wasDown) {
      const a0 = toXY(placing.points[0]);
      if (!(a0 && Math.hypot(x - a0.x, y - a0.y) < 3)) finishTwoPoint(pt);
    }
  }

  function bindEvents() {
    // capture phase: intercept pointer before the chart sees it (for drag)
    wrapEl.addEventListener("pointerdown", (ev) => {
      if (ev.button !== 0) return;
      const p = localXY(ev);
      if (tool === "cursor" && hitTest(p.x, p.y)) ev.stopPropagation();
      onDown(p.x, p.y, ev);
    }, true);
    wrapEl.addEventListener("pointermove", (ev) => {
      const p = localXY(ev);
      onMove(p.x, p.y);
    });
    wrapEl.addEventListener("pointerup", (ev) => {
      const p = localXY(ev);
      if (tool === "cursor" && drag) ev.stopPropagation();
      onUp(p.x, p.y);
    }, true);
    wrapEl.addEventListener("pointerleave", () => { hover = null; });
    wrapEl.addEventListener("contextmenu", (ev) => {
      if (tool !== "cursor") { ev.preventDefault(); setTool("cursor"); }
    });

    document.querySelectorAll(".dt-btn[data-tool]").forEach((btn) =>
      btn.addEventListener("click", () => setTool(btn.dataset.tool)));

    document.querySelectorAll(".dt-swatch").forEach((sw) =>
      sw.addEventListener("click", () => {
        color = sw.dataset.color;
        document.querySelectorAll(".dt-swatch").forEach((s) =>
          s.classList.toggle("active", s.dataset.color === color));
        if (placing) placing.color = color;
      }));

    const bind = (id, fn) => { const el = $(id); if (el) el.addEventListener("click", fn); };
    bind("dt-undo", undo);
    bind("dt-clear", clearAll);
    bind("dt-del", deleteSelected);

    document.addEventListener("keydown", (ev) => {
      if (/input|textarea|select/i.test((document.activeElement || {}).tagName || "")) return;
      if ((ev.key === "Delete" || ev.key === "Backspace") && selectedId && !drag) {
        ev.preventDefault(); deleteSelected();
      }
      if (ev.key === "Escape") setTool("cursor");
      if ((ev.key === "z" || ev.key === "Z") && !ev.ctrlKey && !ev.metaKey && tool === "cursor") undo();
      if ((ev.key === "z" || ev.key === "Z") && (ev.ctrlKey || ev.metaKey)) { ev.preventDefault(); undo(); }
      const hotkeys = { t: "trend", r: "ray", h: "hline", v: "vline", b: "rect", f: "fib" };
      const k = ev.key.toLowerCase();
      if (hotkeys[k] && !ev.ctrlKey && !ev.metaKey && !ev.altKey) setTool(hotkeys[k]);
    });

    new ResizeObserver(resize).observe(wrapEl);
  }

  /* ================= public ================= */
  function onData(next) {
    const newLabels = next.labels || [];
    const map = next.labelMap instanceof Map && next.labelMap.size
      ? next.labelMap
      : (next.fulls && next.fulls.length
          ? new Map(next.fulls.map((lb, i) => [lb, i + 1]).filter((x) => x[0]))
          : new Map(newLabels.map((lb, i) => [lb, i + 1])));

    if (drawings.length) {
      // re-anchor every drawing to its round (full issue) in the new frame.
      // label-less points (right-margin / future placements) keep their numeric
      // slot; labels temporarily outside the buffer stay detached instead of
      // being deleted — they re-appear automatically if the label returns.
      drawings.forEach((d) => d.points.forEach((p) => {
        if (p.lb != null) {
          p.t = map.has(p.lb) ? map.get(p.lb) : null;
        } else if (p.t == null || p.t < 1) {
          p.t = null;
        }
      }));
    }
    api = next;
    if (!restored) restore();
    redraw();
  }

  function init() {
    if (canvas) return;
    wrapEl = $("tv-chart");
    if (!wrapEl) return;
    canvas = document.createElement("canvas");
    canvas.className = "draw-overlay";
    wrapEl.appendChild(canvas);
    ctx = canvas.getContext("2d");

    hintEl = document.createElement("div");
    hintEl.className = "draw-hint";
    hintEl.textContent = HINTS.cursor;
    wrapEl.appendChild(hintEl);

    bindEvents();
    resize();
  }

  document.addEventListener("DOMContentLoaded", init);
  if (document.readyState !== "loading") init();

  return {
    onData, redraw, undo, clearAll,
    _dbg: (x, y) => ({
      tool, apiReady: !!api, labels: api ? api.labels.length : 0,
      count: drawings.length, selectedId, dragging: !!drag,
      placing: !!placing,
      hitAt: (x != null) ? hitTest(x, y) : null,
      hlY: (() => { const d = drawings.find(z => z.type === "hline"); if (!d) return null; const q = toXY(d.points[0]); return q ? q.y : "null"; })(),
      hlP: (() => { const d = drawings.find(z => z.type === "hline"); return d ? d.points[0].p : null; })(),
    }),
  };
})();
