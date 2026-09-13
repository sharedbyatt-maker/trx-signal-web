/* Manual Drawing Tools v2 — isolated overlay for Lightweight Charts v4
   Phase 1 scope only: precise endpoint editing, OHLC magnet snap, mobile handles,
   per-object lock/hide/duplicate/style/extension settings. Chart/strategy logic unchanged. */
window.TRXDraw = (() => {
  const STORE_KEY = "trx_drawings_v3"; // keep existing drawings backward-compatible
  const PREF_KEY = "trx_draw_v2_prefs";
  const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  const FIB_COLORS = ["#787b86", "#f23645", "#ff9800", "#089981", "#2962ff", "#ff9800", "#f23645"];
  const HIT_PX = 9;
  const HANDLE_PX = 7;
  const HANDLE_TOUCH_PX = 13;
  const SNAP_PX = 12;

  let canvas = null, ctx = null, hintEl = null, wrapEl = null, panelEl = null, api = null;
  let tool = "cursor", color = "#2962ff", drawings = [], placing = null, placeStage = 0;
  let hover = null, selectedId = null, downXY = null, drag = null, restored = false;
  let magnet = true;

  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  const $ = (id) => document.getElementById(id);
  const coarse = () => !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
  const handleRadius = () => coarse() ? HANDLE_TOUCH_PX : HANDLE_PX;

  const HINTS = {
    cursor: "Cursor — select · endpoint ကိုဆွဲပြင် · line ကိုဆွဲရွှေ့ · Del delete",
    trend: "Trend Line — drag or click 2 points · Magnet snaps to candle OHLC",
    ray: "Ray — drag or click 2 points · extends right",
    hline: "S/R Line — click one level",
    vline: "Vertical Line — click one bar",
    rect: "Rectangle — drag or click 2 corners",
    fib: "Fibonacci — drag swing high/low",
  };

  function defaults(d) {
    return {
      ...d,
      width: Math.max(1, Math.min(4, Number(d.width || 2))),
      style: ["solid", "dashed", "dotted"].includes(d.style) ? d.style : "solid",
      locked: !!d.locked,
      hidden: !!d.hidden,
      extendLeft: !!d.extendLeft,
      extendRight: d.type === "ray" ? d.extendRight !== false : !!d.extendRight,
    };
  }

  function loadPrefs() {
    try { const p = JSON.parse(localStorage.getItem(PREF_KEY) || "{}"); magnet = p.magnet !== false; }
    catch (_e) { magnet = true; }
  }
  function savePrefs() {
    try { localStorage.setItem(PREF_KEY, JSON.stringify({ magnet })); } catch (_e) {}
  }

  function labelOf(t) {
    return api && api.fulls && api.fulls[t - 1] ? api.fulls[t - 1] : null;
  }
  function save() {
    try {
      const rows = drawings.map((d) => ({
        id: d.id, type: d.type, color: d.color, width: d.width, style: d.style,
        locked: !!d.locked, hidden: !!d.hidden, extendLeft: !!d.extendLeft,
        extendRight: !!d.extendRight,
        points: d.points.map((p) => ({ p: p.p, lb: p.lb || labelOf(p.t), t: p.t })),
      }));
      localStorage.setItem(STORE_KEY, JSON.stringify(rows));
    } catch (_e) {}
  }
  function needPoints(type) { return (type === "hline" || type === "vline") ? 1 : 2; }
  function labelIndexMap() {
    if (api && api.labelMap instanceof Map && api.labelMap.size) return api.labelMap;
    if (api && api.fulls && api.fulls.length) return new Map(api.fulls.map((lb, i) => [lb, i + 1]).filter(x => x[0]));
    return new Map(((api && api.labels) || []).map((lb, i) => [lb, i + 1]));
  }
  function restore() {
    if (!api || !api.labels) return;
    restored = true;
    const map = labelIndexMap();
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
      drawings = [];
      raw.forEach((row) => {
        const pts = [];
        (row.points || []).forEach((p) => {
          let t = null;
          if (p.lb != null && map.has(p.lb)) t = map.get(p.lb);
          else if (p.t != null) t = p.t;
          pts.push({ t, p: p.p, lb: p.lb != null ? p.lb : null });
        });
        if (pts.length >= needPoints(row.type)) drawings.push(defaults({
          ...row, id: row.id || uid(), color: row.color || "#2962ff",
          points: pts.slice(0, needPoints(row.type)),
        }));
      });
    } catch (_e) { drawings = []; }
    updatePanel();
  }

  function toXY(pt) {
    if (!api || !pt || pt.t == null || pt.t < 1) return null;
    const x = api.chart.timeScale().timeToCoordinate(pt.t);
    const y = api.series.priceToCoordinate(pt.p);
    return x == null || y == null ? null : { x, y };
  }
  function xOnly(pt) {
    if (!api || !pt || pt.t == null || pt.t < 1) return null;
    const x = api.chart.timeScale().timeToCoordinate(pt.t);
    return x == null ? null : { x, y: 0 };
  }
  function nearestOHLC(t, rawP, y) {
    if (!magnet || !api || !Array.isArray(api.bars) || t < 1 || t > api.bars.length) return rawP;
    const b = api.bars[t - 1];
    if (!b) return rawP;
    const vals = [b.o, b.h, b.l, b.c].filter(v => Number.isFinite(v));
    let best = rawP, bestPx = SNAP_PX + 1;
    vals.forEach((v) => {
      const yy = api.series.priceToCoordinate(v);
      if (yy == null) return;
      const d = Math.abs(yy - y);
      if (d < bestPx) { bestPx = d; best = v; }
    });
    return bestPx <= SNAP_PX ? best : rawP;
  }
  function fromXY(x, y, snap = true) {
    if (!api || !api.labels || !api.labels.length) return null;
    const n = api.labels.length;
    const ct = api.chart.timeScale().coordinateToTime(x);
    let t = (ct == null || isNaN(ct)) ? n : Math.round(ct);
    t = Math.max(1, Math.min(n + 12, t));
    let p = api.series.coordinateToPrice(y);
    if (p == null || isNaN(p)) return null;
    if (snap) p = nearestOHLC(t, p, y);
    return { t, p };
  }
  function endpoints(d) {
    const a = d.type === "vline" ? xOnly(d.points[0]) : toXY(d.points[0]);
    const b = d.points.length > 1 ? toXY(d.points[1]) : null;
    return { a, b };
  }
  function distSeg(px, py, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy;
    let t = len2 ? ((px - a.x) * dx + (py - a.y) * dy) / len2 : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (a.x + t * dx), py - (a.y + t * dy));
  }
  function extendedEnds(d, a, b) {
    if (!a || !b || !canvas) return { a, b };
    const w = canvas.clientWidth, dx = b.x - a.x, dy = b.y - a.y;
    let aa = a, bb = b;
    if (d.extendLeft && dx !== 0) {
      const k = (0 - a.x) / dx;
      aa = { x: 0, y: a.y + dy * k };
    }
    if ((d.type === "ray" || d.extendRight) && dx !== 0) {
      const k = (w + 40 - a.x) / dx;
      if (k >= 0) bb = { x: w + 40, y: a.y + dy * k };
    }
    return { a: aa, b: bb };
  }
  function dashOf(d) { return d.style === "dashed" ? [8, 5] : d.style === "dotted" ? [2, 4] : []; }
  function setHint(txt) { if (hintEl) hintEl.textContent = txt; }

  function lockChart(lock) {
    if (api) api.chart.applyOptions({ handleScroll: !lock, handleScale: !lock });
    if (wrapEl) {
      wrapEl.style.cursor = lock ? "crosshair" : "";
      wrapEl.classList.toggle("drawing-active", !!lock);
    }
  }
  function setTool(next) {
    if (placing && tool === next) next = "cursor";
    placing = null; placeStage = 0; drag = null; tool = next;
    if (next !== "cursor") selectedId = null;
    document.querySelectorAll(".dt-btn[data-tool]").forEach((b) => b.classList.toggle("active", b.dataset.tool === next));
    lockChart(next !== "cursor"); setHint(HINTS[next] || HINTS.cursor); updatePanel(); redraw();
  }

  function selected() { return drawings.find(d => d.id === selectedId) || null; }
  function handleHit(px, py) {
    const d = selected();
    if (!d || d.hidden || d.locked) return null;
    const { a, b } = endpoints(d); const r = handleRadius() + 5;
    if (a && Math.hypot(px - a.x, py - a.y) <= r) return { id: d.id, index: 0 };
    if (b && Math.hypot(px - b.x, py - b.y) <= r) return { id: d.id, index: 1 };
    return null;
  }
  function hitTest(px, py) {
    for (let i = drawings.length - 1; i >= 0; i--) {
      const d = drawings[i]; if (d.hidden) continue;
      const { a, b } = endpoints(d); if (!a) continue;
      if (d.type === "hline") { if (Math.abs(py - a.y) <= HIT_PX) return d.id; }
      else if (d.type === "vline") { if (Math.abs(px - a.x) <= HIT_PX) return d.id; }
      else if (d.type === "rect") {
        if (!b) continue;
        const x1 = Math.min(a.x,b.x), x2 = Math.max(a.x,b.x), y1 = Math.min(a.y,b.y), y2 = Math.max(a.y,b.y);
        const nearH = Math.abs(py-y1)<=HIT_PX || Math.abs(py-y2)<=HIT_PX;
        const nearV = Math.abs(px-x1)<=HIT_PX || Math.abs(px-x2)<=HIT_PX;
        if ((nearV && py>=y1-HIT_PX && py<=y2+HIT_PX) || (nearH && px>=x1-HIT_PX && px<=x2+HIT_PX)) return d.id;
      } else if (d.type === "fib") {
        if (!b) continue;
        if (distSeg(px,py,a,b)<=HIT_PX) return d.id;
        for (const lv of FIB_LEVELS) if (Math.abs(py-(a.y+(b.y-a.y)*lv))<=5) return d.id;
      } else if (b) {
        const ee = extendedEnds(d,a,b);
        if (distSeg(px,py,ee.a,ee.b)<=HIT_PX) return d.id;
      }
    }
    return null;
  }

  function resize() {
    if (!canvas || !wrapEl) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(wrapEl.clientWidth*dpr));
    canvas.height = Math.max(1, Math.round(wrapEl.clientHeight*dpr));
    canvas.style.width = wrapEl.clientWidth+"px"; canvas.style.height = wrapEl.clientHeight+"px";
    ctx.setTransform(dpr,0,0,dpr,0,0); redraw();
  }
  function drawLine(a,b,c,width,dash) {
    ctx.strokeStyle=c; ctx.lineWidth=width; ctx.setLineDash(dash||[]); ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); ctx.setLineDash([]);
  }
  function priceLabel(y,txt,c) {
    const w=canvas.clientWidth; ctx.font="10px Consolas, monospace"; const tw=ctx.measureText(txt).width+10;
    ctx.fillStyle=c; ctx.globalAlpha=.85; ctx.fillRect(w-tw-58,Math.max(0,Math.min(canvas.clientHeight-16,y-8)),tw,16);
    ctx.globalAlpha=1; ctx.fillStyle="#fff"; ctx.textBaseline="middle"; ctx.fillText(txt,w-tw-53,Math.max(8,Math.min(canvas.clientHeight-8,y+1)));
  }
  function drawHandle(pt, locked) {
    if (!pt) return; const r=handleRadius();
    ctx.save(); ctx.fillStyle=locked?"#787b86":"#fff"; ctx.strokeStyle=locked?"#aaa":"#2962ff"; ctx.lineWidth=2;
    ctx.beginPath(); ctx.arc(pt.x,pt.y,r,0,Math.PI*2); ctx.fill(); ctx.stroke(); ctx.restore();
  }
  function renderOne(d, ghost=false) {
    if (d.hidden && !ghost) return;
    const w=canvas.clientWidth,h=canvas.clientHeight,sel=d.id===selectedId&&!ghost,c=d.color||"#2962ff";
    const lw=ghost?2:(d.width||2)+(sel?1:0), dash=dashOf(d), {a,b}=endpoints(d);
    ctx.save(); if (d.locked) ctx.globalAlpha=.72;
    if (d.type==="hline"&&a) {
      ctx.globalAlpha=d.locked?.08:.12; ctx.fillStyle=c; ctx.fillRect(0,a.y-6,w,12); ctx.globalAlpha=d.locked?.72:1;
      drawLine({x:0,y:a.y},{x:w,y:a.y},c,lw,dash); priceLabel(a.y,d.points[0].p.toFixed(1),c);
    } else if (d.type==="vline"&&a) drawLine({x:a.x,y:0},{x:a.x,y:h},c,lw,dash);
    else if (a&&b) {
      if (d.type==="rect") {
        ctx.strokeStyle=c; ctx.lineWidth=lw; ctx.setLineDash(dash); ctx.strokeRect(Math.min(a.x,b.x),Math.min(a.y,b.y),Math.abs(b.x-a.x),Math.abs(b.y-a.y)); ctx.setLineDash([]);
        ctx.globalAlpha=.08; ctx.fillStyle=c; ctx.fillRect(Math.min(a.x,b.x),Math.min(a.y,b.y),Math.abs(b.x-a.x),Math.abs(b.y-a.y)); ctx.globalAlpha=d.locked?.72:1;
      } else if (d.type==="fib") {
        const x1=Math.min(a.x,b.x),x2=Math.max(a.x,b.x);
        FIB_LEVELS.forEach((lv,i)=>{ const yy=a.y+(b.y-a.y)*lv,cc=FIB_COLORS[i]||c; drawLine({x:x1,y:yy},{x:x2+60,y:yy},cc,1,[5,4]); ctx.font="10px Consolas, monospace"; ctx.fillStyle=cc; ctx.textBaseline="bottom"; ctx.fillText(lv.toFixed(3)+"  "+(d.points[0].p+(d.points[1].p-d.points[0].p)*lv).toFixed(1),x1+4,Math.max(10,yy-2)); });
        drawLine(a,b,"rgba(209,212,220,.55)",1,[]);
      } else { const ee=extendedEnds(d,a,b); drawLine(ee.a,ee.b,c,lw,dash); }
    }
    ctx.restore();
    if ((sel||ghost)&&!d.hidden) { drawHandle(a,d.locked); if (b) drawHandle(b,d.locked); }
  }
  function redraw() {
    if(!ctx||!canvas)return; ctx.clearRect(0,0,canvas.clientWidth,canvas.clientHeight); if(!api)return;
    drawings.forEach(d=>renderOne(d));
    if(placing){ if(hover&&placing.points.length===1){ const cur=fromXY(hover.x,hover.y,true); renderOne({...placing,id:"_ghost",points:[placing.points[0],cur||placing.points[0]]},true);} else renderOne(placing,true); }
  }

  function commit(type,pts,c) {
    const d=defaults({id:uid(),type,color:c,points:pts,width:2,style:"solid",locked:false,hidden:false,extendLeft:false,extendRight:type==="ray"});
    d.points.forEach(p=>{p.lb=labelOf(p.t)||p.lb;}); drawings.push(d); selectedId=d.id; save(); updatePanel();
  }
  function undo(){ if(placing){placing=null;redraw();return;} drawings.pop(); selectedId=null; save(); updatePanel(); redraw(); }
  function clearAll(){ drawings=[]; placing=null; selectedId=null; drag=null; save(); updatePanel(); redraw(); }
  function deleteSelected(){ if(!selectedId)return; drawings=drawings.filter(d=>d.id!==selectedId); selectedId=null; save(); updatePanel(); redraw(); }
  function duplicateSelected(){ const d=selected(); if(!d)return; const cp=defaults(JSON.parse(JSON.stringify(d))); cp.id=uid(); cp.locked=false; cp.hidden=false; cp.points=cp.points.map(p=>({ ...p,t:p.t==null?p.t:p.t+1,p:Number.isFinite(p.p)?p.p+.5:p.p,lb:null })); cp.points.forEach(p=>{p.lb=labelOf(p.t)||null;}); drawings.push(cp); selectedId=cp.id; save(); updatePanel(); redraw(); }
  function toggleLock(){ const d=selected(); if(!d)return; d.locked=!d.locked; drag=null; save(); updatePanel(); redraw(); }
  function toggleHide(){ const d=selected(); if(!d)return; d.hidden=true; selectedId=null; save(); updatePanel(); redraw(); }
  function showAll(){ drawings.forEach(d=>d.hidden=false); save(); updatePanel(); redraw(); }
  function setSelectedStyle(key,value){ const d=selected(); if(!d)return; if(key==="width") d.width=Math.max(1,Math.min(4,Number(value)||2)); else if(key==="style"&&["solid","dashed","dotted"].includes(value)) d.style=value; else if(key==="extendLeft") d.extendLeft=!!value; else if(key==="extendRight") d.extendRight=!!value; save(); updatePanel(); redraw(); }

  function panelButton(text,id,title){ const b=document.createElement("button"); b.type="button"; b.id=id; b.textContent=text; b.title=title||text; b.style.cssText="height:26px;padding:0 7px;border:1px solid #363a45;border-radius:4px;background:#1e222d;color:#d1d4dc;font:11px Consolas,monospace;cursor:pointer"; return b; }
  function buildPanel(){
    panelEl=document.createElement("div"); panelEl.id="draw-v2-panel"; panelEl.style.cssText="position:absolute;z-index:25;right:8px;top:36px;display:none;align-items:center;gap:5px;flex-wrap:wrap;max-width:min(96%,620px);padding:5px 6px;background:rgba(19,23,34,.96);border:1px solid #363a45;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.25)";
    const width=document.createElement("select"); width.id="dt-v2-width"; width.title="Line width"; width.style.cssText="height:26px;background:#1e222d;color:#d1d4dc;border:1px solid #363a45;border-radius:4px;font:11px Consolas"; [1,2,3,4].forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=`${v}px`;width.appendChild(o);});
    const style=document.createElement("select"); style.id="dt-v2-style"; style.title="Line style"; style.style.cssText=width.style.cssText; [["solid","Solid"],["dashed","Dash"],["dotted","Dot"]].forEach(([v,t])=>{const o=document.createElement("option");o.value=v;o.textContent=t;style.appendChild(o);});
    const left=panelButton("← EXT","dt-v2-left","Extend left"), right=panelButton("EXT →","dt-v2-right","Extend right"), lock=panelButton("🔒","dt-v2-lock","Lock / unlock"), hide=panelButton("👁−","dt-v2-hide","Hide selected"), dup=panelButton("⧉","dt-v2-dup","Duplicate selected"), show=panelButton("SHOW HIDDEN","dt-v2-show","Show all hidden drawings"), mag=panelButton("MAGNET","dt-v2-mag","Snap endpoints to candle OHLC");
    panelEl.append(width,style,left,right,lock,hide,dup,show,mag); wrapEl.appendChild(panelEl);
    width.addEventListener("change",()=>setSelectedStyle("width",width.value)); style.addEventListener("change",()=>setSelectedStyle("style",style.value));
    left.addEventListener("click",()=>{const d=selected();if(d)setSelectedStyle("extendLeft",!d.extendLeft);}); right.addEventListener("click",()=>{const d=selected();if(d)setSelectedStyle("extendRight",!d.extendRight);}); lock.addEventListener("click",toggleLock); hide.addEventListener("click",toggleHide); dup.addEventListener("click",duplicateSelected); show.addEventListener("click",showAll); mag.addEventListener("click",()=>{magnet=!magnet;savePrefs();updatePanel();});
  }
  function updatePanel(){
    if(!panelEl)return; const d=selected(), hidden=drawings.some(x=>x.hidden); panelEl.style.display=(d||hidden)?"flex":"none";
    const q=(id)=>document.getElementById(id), active=(el,on)=>{if(!el)return;el.style.background=on?"#2962ff":"#1e222d";el.style.color=on?"#fff":"#d1d4dc";};
    const w=q("dt-v2-width"),s=q("dt-v2-style"); if(w)w.disabled=!d;if(s)s.disabled=!d;if(d&&w)w.value=String(d.width||2);if(d&&s)s.value=d.style||"solid";
    ["dt-v2-left","dt-v2-right","dt-v2-lock","dt-v2-hide","dt-v2-dup"].forEach(id=>{const e=q(id);if(e)e.disabled=!d;});
    active(q("dt-v2-left"),!!(d&&d.extendLeft)); active(q("dt-v2-right"),!!(d&&(d.type==="ray"||d.extendRight))); active(q("dt-v2-lock"),!!(d&&d.locked)); active(q("dt-v2-mag"),magnet); const sh=q("dt-v2-show");if(sh)sh.style.display=hidden?"inline-block":"none";
    if(d)setHint(`${d.type.toUpperCase()} selected${d.locked?" · LOCKED":""} · drag handles to edit endpoints · Magnet ${magnet?"ON":"OFF"}`); else setHint(HINTS[tool]||HINTS.cursor);
  }

  function localXY(ev){const r=canvas.getBoundingClientRect();return{x:ev.clientX-r.left,y:ev.clientY-r.top};}
  function onDown(x,y,ev){
    downXY={x,y};
    if(tool==="cursor"){
      const hh=handleHit(x,y);
      if(hh){const d=selected();drag={id:hh.id,mode:"handle",index:hh.index};ev.stopPropagation();redraw();return;}
      const id=hitTest(x,y);
      if(id){selectedId=id;const d=selected();if(d&&!d.locked){const ptsPx=d.points.map(p=>d.type==="vline"?xOnly(p):toXY(p));if(ptsPx.every(Boolean))drag={id,mode:"move",start:{x,y},origPx:ptsPx,origData:JSON.parse(JSON.stringify(d.points))};}ev.stopPropagation();updatePanel();redraw();}
      else if(selectedId){selectedId=null;updatePanel();redraw();}
      return;
    }
    if(!placing&&tool!=="hline"&&tool!=="vline"){const pt=fromXY(x,y,true);if(pt){placing=defaults({type:tool,color,points:[{...pt,lb:labelOf(pt.t)}],width:2,style:"solid",extendRight:tool==="ray"});placeStage=1;redraw();}}
  }
  function onMove(x,y){
    hover={x,y};
    if(drag){const d=drawings.find(z=>z.id===drag.id);if(!d||d.locked){drag=null;return;}
      if(drag.mode==="handle"){
        const np=fromXY(x,y,true);if(np){if(d.type==="vline")d.points[drag.index]={...d.points[drag.index],t:np.t,lb:labelOf(np.t)||null};else if(d.type==="hline")d.points[0]={...d.points[0],p:np.p};else d.points[drag.index]={t:np.t,p:np.p,lb:labelOf(np.t)||null};redraw();}return;
      }
      const dx=x-drag.start.x,dy=y-drag.start.y;d.points=drag.origPx.map((o,i)=>{if(d.type==="hline"){const p=api.series.coordinateToPrice(o.y+dy);return{...drag.origData[i],p:(p==null||isNaN(p))?drag.origData[i].p:p};}const np=fromXY(o.x+dx,d.type==="vline"?0:o.y+dy,false);if(!np)return drag.origData[i];return d.type==="vline"?{...drag.origData[i],t:np.t,lb:labelOf(np.t)||null}:{t:np.t,p:np.p,lb:labelOf(np.t)||null};});redraw();return;
    }
    if(placing&&placing.points.length===1)redraw();
  }
  function finishTwoPoint(pt){placing.points.push({...pt,lb:labelOf(pt.t)});commit(placing.type,placing.points,placing.color);placing=null;placeStage=0;setTool("cursor");redraw();}
  function onUp(x,y){
    const moved=downXY?Math.hypot(x-downXY.x,y-downXY.y):0;
    if(drag){if(moved>1)save();drag=null;downXY=null;updatePanel();redraw();return;}
    const wasDown=!!downXY;downXY=null;if(tool==="cursor")return;const pt=fromXY(x,y,true);if(!pt)return;
    if(tool==="hline"||tool==="vline"){if(!wasDown||moved>6)return;commit(tool,[{t:pt.t,p:tool==="hline"?pt.p:0,lb:labelOf(pt.t)}]);setTool("cursor");redraw();return;}
    if(!placing)return;if(moved>8)finishTwoPoint(pt);else if(placeStage===1&&wasDown)placeStage=2;else if(placeStage===2&&wasDown){const a0=toXY(placing.points[0]);if(!(a0&&Math.hypot(x-a0.x,y-a0.y)<3))finishTwoPoint(pt);}
  }

  function bindEvents(){
    wrapEl.addEventListener("pointerdown",ev=>{if(ev.button!==0)return;const p=localXY(ev);if(tool!=="cursor"||handleHit(p.x,p.y)||hitTest(p.x,p.y)){try{wrapEl.setPointerCapture(ev.pointerId);}catch(_e){} ev.stopPropagation();}onDown(p.x,p.y,ev);},true);
    wrapEl.addEventListener("pointermove",ev=>{const p=localXY(ev);onMove(p.x,p.y);});
    const finish=(ev)=>{const p=localXY(ev);if(tool==="cursor"&&drag)ev.stopPropagation();onUp(p.x,p.y);try{if(wrapEl.hasPointerCapture(ev.pointerId))wrapEl.releasePointerCapture(ev.pointerId);}catch(_e){}};
    wrapEl.addEventListener("pointerup",finish,true);wrapEl.addEventListener("pointercancel",ev=>{drag=null;downXY=null;placing=null;placeStage=0;try{if(wrapEl.hasPointerCapture(ev.pointerId))wrapEl.releasePointerCapture(ev.pointerId);}catch(_e){}redraw();},true);
    wrapEl.addEventListener("pointerleave",()=>{hover=null;});wrapEl.addEventListener("contextmenu",ev=>{if(tool!=="cursor"){ev.preventDefault();setTool("cursor");}});
    document.querySelectorAll(".dt-btn[data-tool]").forEach(btn=>btn.addEventListener("click",()=>setTool(btn.dataset.tool)));
    document.querySelectorAll(".dt-swatch").forEach(sw=>sw.addEventListener("click",()=>{color=sw.dataset.color;document.querySelectorAll(".dt-swatch").forEach(s=>s.classList.toggle("active",s.dataset.color===color));const d=selected();if(d){d.color=color;save();redraw();}if(placing)placing.color=color;}));
    const bind=(id,fn)=>{const el=$(id);if(el)el.addEventListener("click",fn);};bind("dt-undo",undo);bind("dt-clear",clearAll);bind("dt-del",deleteSelected);
    document.addEventListener("keydown",ev=>{if(/input|textarea|select/i.test((document.activeElement||{}).tagName||""))return;if((ev.key==="Delete"||ev.key==="Backspace")&&selectedId&&!drag){ev.preventDefault();deleteSelected();}if(ev.key==="Escape")setTool("cursor");if((ev.key==="z"||ev.key==="Z")&&(ev.ctrlKey||ev.metaKey)){ev.preventDefault();undo();}const hotkeys={t:"trend",r:"ray",h:"hline",v:"vline",b:"rect",f:"fib"};const k=ev.key.toLowerCase();if(hotkeys[k]&&!ev.ctrlKey&&!ev.metaKey&&!ev.altKey)setTool(hotkeys[k]);});
    new ResizeObserver(resize).observe(wrapEl);
  }

  function onData(next){
    const newLabels=next.labels||[];const map=next.labelMap instanceof Map&&next.labelMap.size?next.labelMap:(next.fulls&&next.fulls.length?new Map(next.fulls.map((lb,i)=>[lb,i+1]).filter(x=>x[0])):new Map(newLabels.map((lb,i)=>[lb,i+1])));
    if(drawings.length)drawings.forEach(d=>d.points.forEach(p=>{if(p.lb!=null)p.t=map.has(p.lb)?map.get(p.lb):null;else if(p.t==null||p.t<1)p.t=null;}));
    api=next;if(!restored)restore();updatePanel();redraw();
  }
  function init(){
    if(canvas)return;wrapEl=$("tv-chart");if(!wrapEl)return;loadPrefs();canvas=document.createElement("canvas");canvas.className="draw-overlay";wrapEl.appendChild(canvas);ctx=canvas.getContext("2d");
    hintEl=document.createElement("div");hintEl.className="draw-hint";hintEl.textContent=HINTS.cursor;wrapEl.appendChild(hintEl);buildPanel();bindEvents();resize();
  }
  document.addEventListener("DOMContentLoaded",init);if(document.readyState!=="loading")init();
  return {onData,redraw,undo,clearAll,_dbg:()=>({tool,apiReady:!!api,count:drawings.length,selectedId,dragging:!!drag,placing:!!placing,magnet,selected:selected()?{type:selected().type,locked:selected().locked,hidden:selected().hidden,width:selected().width,style:selected().style,extendLeft:selected().extendLeft,extendRight:selected().extendRight}:null,hidden:drawings.filter(d=>d.hidden).length})};
})();
