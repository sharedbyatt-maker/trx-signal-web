from pathlib import Path
p=Path('static/js/chart.js')
s=p.read_text()
start=s.index('  /* ---- support/resistance horizontal levels (pivot clustering) ---- */')
end=s.index('  /* ================= signal markers (WIN/LOSS) ================= */')
new=r'''  /* ---- Auto Support / Resistance v2 --------------------------------------
     Adaptive clustering + touch/rejection/recency scoring + break/retest and
     support<->resistance role-flip detection. Display-only chart structure. */
  function srAdaptiveTolerance(bars) {
    const tail = bars.slice(-180);
    if (!tail.length) return 1.0;
    let rangeSum = 0;
    tail.forEach((b) => { rangeSum += Math.max(0.1, b.h - b.l); });
    const avgRange = rangeSum / tail.length;
    return Math.max(0.65, Math.min(2.4, avgRange * 1.15));
  }

  function srLevelStats(level, bars, tol) {
    let touches = 0, rejections = 0, lastTouch = -1, breaksUp = 0, breaksDown = 0;
    let lastBreakUp = -1, lastBreakDown = -1, retests = 0;
    for (let i = 1; i < bars.length; i++) {
      const b = bars[i], prev = bars[i - 1];
      const near = b.l <= level + tol && b.h >= level - tol;
      if (near) {
        touches++; lastTouch = i;
        const rejectUp = b.h >= level - tol && b.c < level - tol * 0.15;
        const rejectDown = b.l <= level + tol && b.c > level + tol * 0.15;
        if (rejectUp || rejectDown) rejections++;
      }
      if (prev.c <= level + tol * 0.2 && b.c > level + tol * 0.75) {
        breaksUp++; lastBreakUp = i;
      }
      if (prev.c >= level - tol * 0.2 && b.c < level - tol * 0.75) {
        breaksDown++; lastBreakDown = i;
      }
    }
    if (lastBreakUp >= 0) {
      for (let i = lastBreakUp + 1; i < bars.length; i++) {
        if (bars[i].l <= level + tol && bars[i].c >= level) { retests++; break; }
      }
    }
    if (lastBreakDown >= 0) {
      for (let i = lastBreakDown + 1; i < bars.length; i++) {
        if (bars[i].h >= level - tol && bars[i].c <= level) { retests++; break; }
      }
    }
    const age = lastTouch < 0 ? bars.length : bars.length - 1 - lastTouch;
    const recency = Math.max(0, 1 - age / 700);
    return { touches, rejections, lastTouch, breaksUp, breaksDown, lastBreakUp, lastBreakDown, retests, recency };
  }

  function srLevels(bars, maxLevels = 6) {
    const lim = bars.slice(-2500);
    if (lim.length < 25) return [];
    const close = lim[lim.length - 1].c;
    const tol = srAdaptiveTolerance(lim);
    const piv = findPivots(lim, Math.max(3, Math.min(6, Math.floor(lim.length / 60))));
    const pts = [
      ...piv.hi.map((p) => ({ v:p.v, i:p.i, kind:'H' })),
      ...piv.lo.map((p) => ({ v:p.v, i:p.i, kind:'L' })),
      ...lim.slice(-60).map((b, j) => ({ v:b.h, i:lim.length-60+j, kind:'H' })),
      ...lim.slice(-60).map((b, j) => ({ v:b.l, i:lim.length-60+j, kind:'L' })),
    ].filter((x) => Number.isFinite(x.v));
    if (!pts.length) return [];

    pts.sort((a,b)=>a.v-b.v);
    const clusters=[]; let cur=[pts[0]];
    for (let i=1;i<pts.length;i++) {
      const mean=cur.reduce((s,x)=>s+x.v,0)/cur.length;
      if (Math.abs(pts[i].v-mean)<=tol) cur.push(pts[i]);
      else { clusters.push(cur); cur=[pts[i]]; }
    }
    clusters.push(cur);

    const scored=clusters.map((cl)=>{
      const L=cl.reduce((s,x)=>s+x.v,0)/cl.length;
      const st=srLevelStats(L,lim,tol);
      const hiTouches=cl.filter(x=>x.kind==='H').length, loTouches=cl.filter(x=>x.kind==='L').length;
      let role=L<close?'S':'R'; let flipped=false;
      if (st.lastBreakUp>=0 && st.lastBreakUp>st.lastBreakDown && close>=L-tol*0.35) { role='S'; flipped=true; }
      if (st.lastBreakDown>=0 && st.lastBreakDown>st.lastBreakUp && close<=L+tol*0.35) { role='R'; flipped=true; }
      const sideQuality=role==='S'?loTouches:hiTouches;
      const score=st.touches*5 + st.rejections*4 + st.retests*9 + sideQuality*2.5 + st.recency*12 + (flipped?8:0) - (st.breaksUp+st.breaksDown)*1.5;
      const strength=score>=70?'STRONG':score>=42?'MEDIUM':'WEAK';
      return { L, c:st.touches, score, strength, role, flipped, retests:st.retests, rejections:st.rejections, tol };
    }).filter(x=>x.c>=2 || Math.abs(x.L-close)<=tol*2.5);

    const picked=[];
    for (const it of scored.sort((a,b)=>b.score-a.score)) {
      if (picked.every((p)=>Math.abs(p.L-it.L)>=Math.max(2.2,tol*1.6))) picked.push(it);
      if (picked.length>=maxLevels) break;
    }
    // Ensure one useful level on each side when available.
    if (!picked.some(x=>x.L<close)) {
      const q=scored.filter(x=>x.L<close).sort((a,b)=>Math.abs(close-a.L)-Math.abs(close-b.L))[0]; if(q)picked.push(q);
    }
    if (!picked.some(x=>x.L>=close)) {
      const q=scored.filter(x=>x.L>=close).sort((a,b)=>Math.abs(close-a.L)-Math.abs(close-b.L))[0]; if(q)picked.push(q);
    }
    return picked.sort((a,b)=>a.L-b.L).slice(0,maxLevels+2);
  }

  function drawSrLines(levels) {
    srLines.forEach((pl)=>{ try { candleSeries.removePriceLine(pl); } catch(e){} });
    srLines=[]; if(!opts.sr) return;
    levels.forEach((lv)=>{
      const isSup=(lv.role|| (lv.L<curBars[curBars.length-1].c?'S':'R'))==='S';
      const strong=lv.strength==='STRONG', medium=lv.strength==='MEDIUM';
      const alpha=strong?.88:medium?.68:.48;
      const color=isSup?`rgba(8,153,129,${alpha})`:`rgba(242,54,69,${alpha})`;
      const cls=strong?'●●●':medium?'●●':'●';
      const flip=lv.flipped?' FLIP':'';
      srLines.push(candleSeries.createPriceLine({
        price:lv.L, color,
        lineWidth: strong?2:1,
        lineStyle: strong?LightweightCharts.LineStyle.Solid:LightweightCharts.LineStyle.Dashed,
        axisLabelVisible:true,
        title:`${isSup?'S':'R'} ${cls}${flip} T${lv.c||0} Rj${lv.rejections||0}`,
      }));
    });
  }

'''
s=s[:start]+new+s[end:]
p.write_text(s)
Path('tests_sr_v2.py').write_text('''from pathlib import Path\ns=Path("static/js/chart.js").read_text()\nfor x in ["srAdaptiveTolerance","srLevelStats","rejections","retests","flipped","STRONG","MEDIUM","FLIP","role=L<close"]: assert x in s, x\nfor f in ["decision.py","robust_engine.py","app_core.py"]: assert Path(f).exists()\nprint("Auto S/R v2 contract OK")\n''')
