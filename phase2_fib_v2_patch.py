from pathlib import Path

p = Path('static/js/draw.js')
s = p.read_text(encoding='utf-8')

# Header + fib constants/helpers.
s = s.replace(
'''/* Manual Drawing Tools v2 — isolated overlay for Lightweight Charts v4\n   Phase 1 scope only: precise endpoint editing, OHLC magnet snap, mobile handles,\n   per-object lock/hide/duplicate/style/extension settings. Chart/strategy logic unchanged. */''',
'''/* Manual Drawing Tools v2 + Fibonacci v2 — isolated overlay for Lightweight Charts v4\n   Phase 2 adds per-object Fib levels/extensions/reverse/labels/fill/right-extension.\n   Chart, signals, strategy, feed and indicator calculations remain unchanged. */''', 1)

s = s.replace(
'''  const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];\n  const FIB_COLORS = ["#787b86", "#f23645", "#ff9800", "#089981", "#2962ff", "#ff9800", "#f23645"];''',
'''  const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];\n  const FIB_EXT_LEVELS = [1.272, 1.414, 1.618, 2.0];\n  const FIB_COLORS = ["#787b86", "#f23645", "#ff9800", "#089981", "#2962ff", "#ff9800", "#f23645", "#00bcd4", "#9c27b0", "#e91e63", "#607d8b"];\n  const DEFAULT_FIB_LEVELS = [...FIB_LEVELS, ...FIB_EXT_LEVELS];\n\n  function normalizeFibLevels(levels) {\n    const src = Array.isArray(levels) && levels.length ? levels : FIB_LEVELS;\n    const seen = new Set();\n    return src.map((x) => typeof x === "number" ? { value: x, enabled: true } : x)\n      .filter((x) => x && Number.isFinite(Number(x.value)))\n      .map((x) => ({ value: Number(x.value), enabled: x.enabled !== false }))\n      .filter((x) => { const k = x.value.toFixed(6); if (seen.has(k)) return false; seen.add(k); return true; })\n      .sort((a, b) => a.value - b.value);\n  }\n  function activeFibLevels(d) { return normalizeFibLevels(d.fibLevels).filter((x) => x.enabled); }\n  function fibPrice(d, lv) {\n    const p0 = d.points[0].p, p1 = d.points[1].p;\n    const a = d.fibReverse ? p1 : p0, b = d.fibReverse ? p0 : p1;\n    return a + (b - a) * lv;\n  }''', 1)

# Add fib defaults.
s = s.replace(
'''      extendLeft: !!d.extendLeft,\n      extendRight: d.type === "ray" ? d.extendRight !== false : !!d.extendRight,\n    };''',
'''      extendLeft: !!d.extendLeft,\n      extendRight: d.type === "ray" ? d.extendRight !== false : !!d.extendRight,\n      fibLevels: d.type === "fib" ? normalizeFibLevels(d.fibLevels) : d.fibLevels,\n      fibReverse: d.type === "fib" ? !!d.fibReverse : false,\n      fibLabelSide: d.type === "fib" && d.fibLabelSide === "right" ? "right" : "left",\n      fibFill: d.type === "fib" ? Math.max(0, Math.min(0.25, Number(d.fibFill ?? 0.06))) : 0,\n      fibExtendRight: d.type === "fib" ? !!d.fibExtendRight : false,\n    };''', 1)

# Persist fib settings.
s = s.replace(
'''        locked: !!d.locked, hidden: !!d.hidden, extendLeft: !!d.extendLeft,\n        extendRight: !!d.extendRight,\n        points: d.points.map((p) => ({ p: p.p, lb: p.lb || labelOf(p.t), t: p.t })),''',
'''        locked: !!d.locked, hidden: !!d.hidden, extendLeft: !!d.extendLeft,\n        extendRight: !!d.extendRight,\n        fibLevels: d.type === "fib" ? normalizeFibLevels(d.fibLevels) : undefined,\n        fibReverse: d.type === "fib" ? !!d.fibReverse : undefined,\n        fibLabelSide: d.type === "fib" ? d.fibLabelSide : undefined,\n        fibFill: d.type === "fib" ? d.fibFill : undefined,\n        fibExtendRight: d.type === "fib" ? !!d.fibExtendRight : undefined,\n        points: d.points.map((p) => ({ p: p.p, lb: p.lb || labelOf(p.t), t: p.t })),''', 1)

# Hit test all enabled fib levels using real price coordinates.
s = s.replace(
'''        if (distSeg(px,py,a,b)<=HIT_PX) return d.id;\n        for (const lv of FIB_LEVELS) if (Math.abs(py-(a.y+(b.y-a.y)*lv))<=5) return d.id;''',
'''        if (distSeg(px,py,a,b)<=HIT_PX) return d.id;\n        for (const it of activeFibLevels(d)) {\n          const yy = api.series.priceToCoordinate(fibPrice(d, it.value));\n          if (yy != null && Math.abs(py - yy) <= 5) return d.id;\n        }''', 1)

old_render = '''      } else if (d.type==="fib") {\n        const x1=Math.min(a.x,b.x),x2=Math.max(a.x,b.x);\n        FIB_LEVELS.forEach((lv,i)=>{ const yy=a.y+(b.y-a.y)*lv,cc=FIB_COLORS[i]||c; drawLine({x:x1,y:yy},{x:x2+60,y:yy},cc,1,[5,4]); ctx.font="10px Consolas, monospace"; ctx.fillStyle=cc; ctx.textBaseline="bottom"; ctx.fillText(lv.toFixed(3)+"  "+(d.points[0].p+(d.points[1].p-d.points[0].p)*lv).toFixed(1),x1+4,Math.max(10,yy-2)); });\n        drawLine(a,b,"rgba(209,212,220,.55)",1,[]);'''
new_render = '''      } else if (d.type==="fib") {\n        const x1=Math.min(a.x,b.x), x2=Math.max(a.x,b.x);\n        const right = d.fibExtendRight ? w : Math.min(w, x2 + 60);\n        const levels = activeFibLevels(d);\n        const rendered = levels.map((it,i) => ({\n          value: it.value, price: fibPrice(d,it.value), color: FIB_COLORS[i % FIB_COLORS.length] || c\n        })).map((it) => ({ ...it, y: api.series.priceToCoordinate(it.price) })).filter((it) => it.y != null);\n        if (d.fibFill > 0 && rendered.length > 1) {\n          const sorted = [...rendered].sort((u,v)=>u.y-v.y);\n          ctx.save(); ctx.globalAlpha = d.fibFill;\n          for (let i=0;i<sorted.length-1;i++) {\n            ctx.fillStyle = sorted[i].color;\n            ctx.fillRect(x1, sorted[i].y, Math.max(1,right-x1), Math.max(0,sorted[i+1].y-sorted[i].y));\n          }\n          ctx.restore();\n        }\n        rendered.forEach((it)=>{\n          drawLine({x:x1,y:it.y},{x:right,y:it.y},it.color,1,[5,4]);\n          const levelTxt = Number.isInteger(it.value) ? it.value.toFixed(1) : it.value.toFixed(3).replace(/0+$/,"").replace(/\\.$/,"");\n          const txt = levelTxt + "  " + it.price.toFixed(1);\n          ctx.font="10px Consolas, monospace"; ctx.fillStyle=it.color; ctx.textBaseline="bottom";\n          if (d.fibLabelSide === "right") {\n            const tw=ctx.measureText(txt).width; ctx.fillText(txt,Math.max(x1+2,right-tw-4),Math.max(10,it.y-2));\n          } else ctx.fillText(txt,x1+4,Math.max(10,it.y-2));\n        });\n        drawLine(a,b,"rgba(209,212,220,.55)",1,[]);'''
if old_render not in s:
    raise SystemExit('fib render target not found')
s = s.replace(old_render, new_render, 1)

# New fib objects get retracement defaults only (extensions available in settings).
s = s.replace(
'''const d=defaults({id:uid(),type,color:c,points:pts,width:2,style:"solid",locked:false,hidden:false,extendLeft:false,extendRight:type==="ray"});''',
'''const d=defaults({id:uid(),type,color:c,points:pts,width:2,style:"solid",locked:false,hidden:false,extendLeft:false,extendRight:type==="ray",fibLevels:type==="fib"?FIB_LEVELS.map(value=>({value,enabled:true})):undefined});''', 1)

# Insert Fib editor helpers before panelButton.
marker = '''  function panelButton(text,id,title){'''
fib_editor = r'''  function ensureFibLevel(d,value,enabled=true){
    if(!d||d.type!=="fib"||!Number.isFinite(Number(value)))return;
    const v=Number(value); d.fibLevels=normalizeFibLevels(d.fibLevels);
    const found=d.fibLevels.find(x=>Math.abs(x.value-v)<1e-9);
    if(found) found.enabled=enabled; else d.fibLevels.push({value:v,enabled});
    d.fibLevels=normalizeFibLevels(d.fibLevels);
  }
  function setFibLevelEnabled(value,enabled){const d=selected();if(!d||d.type!=="fib")return;ensureFibLevel(d,value,enabled);save();updateFibPanel();redraw();}
  function removeCustomFibLevel(value){const d=selected();if(!d||d.type!=="fib")return;const fixed=new Set(DEFAULT_FIB_LEVELS.map(v=>v.toFixed(6)));d.fibLevels=normalizeFibLevels(d.fibLevels).filter(x=>fixed.has(x.value.toFixed(6))||Math.abs(x.value-value)>1e-9);save();updateFibPanel();redraw();}
  function setFibOption(key,value){const d=selected();if(!d||d.type!=="fib")return;
    if(key==="reverse")d.fibReverse=!!value;
    else if(key==="label")d.fibLabelSide=value==="right"?"right":"left";
    else if(key==="fill")d.fibFill=Math.max(0,Math.min(.25,Number(value)||0));
    else if(key==="extendRight")d.fibExtendRight=!!value;
    save();updateFibPanel();redraw();
  }
  let fibPanelEl=null;
  function fibMiniButton(text,title){const b=document.createElement("button");b.type="button";b.textContent=text;b.title=title||text;b.style.cssText="height:25px;padding:0 7px;border:1px solid #363a45;border-radius:4px;background:#1e222d;color:#d1d4dc;font:10px Consolas,monospace;cursor:pointer";return b;}
  function buildFibPanel(){
    fibPanelEl=document.createElement("div");fibPanelEl.id="fib-v2-panel";
    fibPanelEl.style.cssText="position:absolute;z-index:26;right:8px;top:72px;display:none;min-width:280px;max-width:min(96%,520px);padding:8px;background:rgba(19,23,34,.98);border:1px solid #434651;border-radius:7px;box-shadow:0 6px 22px rgba(0,0,0,.32);color:#d1d4dc;font:11px Consolas,monospace";
    wrapEl.appendChild(fibPanelEl);
  }
  function updateFibPanel(){
    if(!fibPanelEl)return;const d=selected();if(!d||d.type!=="fib"){fibPanelEl.style.display="none";fibPanelEl.innerHTML="";return;}
    fibPanelEl.style.display="block";fibPanelEl.innerHTML="";
    const title=document.createElement("div");title.textContent="FIBONACCI v2";title.style.cssText="font-weight:700;margin-bottom:7px;color:#fff";fibPanelEl.appendChild(title);
    const levelWrap=document.createElement("div");levelWrap.style.cssText="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:7px";
    const levels=normalizeFibLevels(d.fibLevels);const fixed=[...DEFAULT_FIB_LEVELS];
    fixed.forEach((lv)=>{const found=levels.find(x=>Math.abs(x.value-lv)<1e-9);const lab=document.createElement("label");lab.style.cssText="display:flex;align-items:center;gap:3px;padding:2px 4px;border:1px solid #363a45;border-radius:4px";const cb=document.createElement("input");cb.type="checkbox";cb.checked=!!(found&&found.enabled);cb.addEventListener("change",()=>setFibLevelEnabled(lv,cb.checked));lab.append(cb,document.createTextNode(String(lv)));levelWrap.appendChild(lab);});
    fibPanelEl.appendChild(levelWrap);
    const customTitle=document.createElement("div");customTitle.textContent="CUSTOM LEVELS";customTitle.style.cssText="margin:4px 0;color:#9aa0aa";fibPanelEl.appendChild(customTitle);
    const customs=levels.filter(x=>!fixed.some(v=>Math.abs(v-x.value)<1e-9));
    const customRow=document.createElement("div");customRow.style.cssText="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:6px";
    customs.forEach((it)=>{const chip=fibMiniButton(`${it.enabled?"✓":"○"} ${it.value} ×`,`Toggle / remove custom level`);chip.addEventListener("click",(ev)=>{if(ev.shiftKey)removeCustomFibLevel(it.value);else setFibLevelEnabled(it.value,!it.enabled);});customRow.appendChild(chip);});fibPanelEl.appendChild(customRow);
    const addRow=document.createElement("div");addRow.style.cssText="display:flex;gap:5px;margin-bottom:8px";const inp=document.createElement("input");inp.type="number";inp.step="0.001";inp.placeholder="custom e.g. 2.618";inp.style.cssText="width:145px;height:25px;background:#11151d;color:#fff;border:1px solid #363a45;border-radius:4px;padding:0 5px";const add=fibMiniButton("+ ADD","Add custom Fib level");add.addEventListener("click",()=>{const v=Number(inp.value);if(Number.isFinite(v)){ensureFibLevel(d,v,true);save();updateFibPanel();redraw();}});addRow.append(inp,add);fibPanelEl.appendChild(addRow);
    const opts=document.createElement("div");opts.style.cssText="display:flex;flex-wrap:wrap;gap:5px;align-items:center";
    const rev=fibMiniButton(d.fibReverse?"REVERSE ✓":"REVERSE","Reverse Fib anchors");rev.addEventListener("click",()=>setFibOption("reverse",!d.fibReverse));
    const side=fibMiniButton(`LABEL ${d.fibLabelSide==="right"?"RIGHT":"LEFT"}`,"Toggle label side");side.addEventListener("click",()=>setFibOption("label",d.fibLabelSide==="right"?"left":"right"));
    const ext=fibMiniButton(d.fibExtendRight?"EXT RIGHT ✓":"EXT RIGHT","Extend Fib levels to right edge");ext.addEventListener("click",()=>setFibOption("extendRight",!d.fibExtendRight));
    const fill=document.createElement("input");fill.type="range";fill.min="0";fill.max="0.25";fill.step="0.01";fill.value=String(d.fibFill??.06);fill.title="Background opacity";fill.addEventListener("input",()=>setFibOption("fill",fill.value));
    const fillLab=document.createElement("span");fillLab.textContent=`FILL ${Math.round((d.fibFill||0)*100)}%`;
    const close=fibMiniButton("DONE","Close Fib settings");close.addEventListener("click",()=>{fibPanelEl.style.display="none";});
    opts.append(rev,side,ext,fillLab,fill,close);fibPanelEl.appendChild(opts);
  }

'''
if marker not in s:
    raise SystemExit('panel marker not found')
s = s.replace(marker, fib_editor + marker, 1)

# Add FIB button to selected object panel and wire it.
s = s.replace(
'''const left=panelButton("← EXT","dt-v2-left","Extend left"), right=panelButton("EXT →","dt-v2-right","Extend right"), lock=panelButton("🔒","dt-v2-lock","Lock / unlock"), hide=panelButton("👁−","dt-v2-hide","Hide selected"), dup=panelButton("⧉","dt-v2-dup","Duplicate selected"), show=panelButton("SHOW HIDDEN","dt-v2-show","Show all hidden drawings"), mag=panelButton("MAGNET","dt-v2-mag","Snap endpoints to candle OHLC");\n    panelEl.append(width,style,left,right,lock,hide,dup,show,mag);''',
'''const left=panelButton("← EXT","dt-v2-left","Extend left"), right=panelButton("EXT →","dt-v2-right","Extend right"), lock=panelButton("🔒","dt-v2-lock","Lock / unlock"), hide=panelButton("👁−","dt-v2-hide","Hide selected"), dup=panelButton("⧉","dt-v2-dup","Duplicate selected"), fib=panelButton("FIB ⚙","dt-v2-fib","Fibonacci v2 settings"), show=panelButton("SHOW HIDDEN","dt-v2-show","Show all hidden drawings"), mag=panelButton("MAGNET","dt-v2-mag","Snap endpoints to candle OHLC");\n    panelEl.append(width,style,left,right,lock,hide,dup,fib,show,mag);''', 1)
s = s.replace(
'''left.addEventListener("click",()=>{const d=selected();if(d)setSelectedStyle("extendLeft",!d.extendLeft);}); right.addEventListener("click",()=>{const d=selected();if(d)setSelectedStyle("extendRight",!d.extendRight);}); lock.addEventListener("click",toggleLock); hide.addEventListener("click",toggleHide); dup.addEventListener("click",duplicateSelected); show.addEventListener("click",showAll); mag.addEventListener("click",()=>{magnet=!magnet;savePrefs();updatePanel();});''',
'''left.addEventListener("click",()=>{const d=selected();if(d)setSelectedStyle("extendLeft",!d.extendLeft);}); right.addEventListener("click",()=>{const d=selected();if(d)setSelectedStyle("extendRight",!d.extendRight);}); lock.addEventListener("click",toggleLock); hide.addEventListener("click",toggleHide); dup.addEventListener("click",duplicateSelected); fib.addEventListener("click",()=>{const d=selected();if(d&&d.type==="fib"){updateFibPanel();fibPanelEl.style.display="block";}}); show.addEventListener("click",showAll); mag.addEventListener("click",()=>{magnet=!magnet;savePrefs();updatePanel();});''', 1)

# Panel visibility for fib button and update fib settings whenever selection changes.
s = s.replace(
'''["dt-v2-left","dt-v2-right","dt-v2-lock","dt-v2-hide","dt-v2-dup"].forEach(id=>{const e=q(id);if(e)e.disabled=!d;});''',
'''["dt-v2-left","dt-v2-right","dt-v2-lock","dt-v2-hide","dt-v2-dup"].forEach(id=>{const e=q(id);if(e)e.disabled=!d;});\n    const fibBtn=q("dt-v2-fib");if(fibBtn){fibBtn.disabled=!(d&&d.type==="fib");fibBtn.style.display=(d&&d.type==="fib")?"inline-block":"none";}\n    if(!(d&&d.type==="fib")&&fibPanelEl)fibPanelEl.style.display="none";''', 1)

# Build fib panel at init, after normal panel.
s = s.replace('''buildPanel(); loadPrefs(); updatePanel();''', '''buildPanel(); buildFibPanel(); loadPrefs(); updatePanel();''', 1)

# Ensure public debug exposes fib selected settings for tests/manual verification.
s = s.replace(
'''      count:drawings.length,selectedId,dragging:!!drag,placing:!!placing,magnet,''',
'''      count:drawings.length,selectedId,dragging:!!drag,placing:!!placing,magnet,\n      fibSelected:(()=>{const d=selected();return d&&d.type==="fib"?{levels:normalizeFibLevels(d.fibLevels),reverse:d.fibReverse,labelSide:d.fibLabelSide,fill:d.fibFill,extendRight:d.fibExtendRight}:null;})(),''', 1)

p.write_text(s, encoding='utf-8')

Path('tests_fibonacci_v2.py').write_text(r'''from pathlib import Path
s = Path("static/js/draw.js").read_text(encoding="utf-8")
assert "FIB_EXT_LEVELS = [1.272, 1.414, 1.618, 2.0]" in s
assert "normalizeFibLevels" in s and "activeFibLevels" in s and "fibPrice" in s
assert "fibReverse" in s and "fibLabelSide" in s and "fibFill" in s and "fibExtendRight" in s
assert 'id="fib-v2-panel"' in s
assert '"FIB ⚙"' in s
assert 'CUSTOM LEVELS' in s and '+ ADD' in s
assert 'REVERSE ✓' in s and 'LABEL ${d.fibLabelSide' in s and 'EXT RIGHT ✓' in s
assert 'localStorage.setItem(STORE_KEY' in s
# Phase 1 safety contracts remain present.
for token in ["handleHit", "nearestOHLC", "toggleLock", "duplicateSelected", "setPointerCapture"]:
    assert token in s, token
print("FIBONACCI V2 TESTS: ALL PASSED")
''', encoding='utf-8')
