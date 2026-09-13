from pathlib import Path

p=Path('static/js/chart.js')
s=p.read_text()
start=s.index('  function detectPatterns(ph, pl, bars) {\n')
end=s.index('  /* ---- Auto Support / Resistance v2', start)
new=r'''  function clampScore(v) { return Math.max(0, Math.min(100, Math.round(v))); }
  function patternMark(t, v, position, shape, color, code, score, confirmed=true) {
    const c = clampScore(score);
    const flag = confirmed ? "✓" : "?";
    return mk(t, v, position, shape, color, `${code}${flag} ${c}%`);
  }
  function minLowBetween(bars, a, b) {
    let v = Infinity, idx = -1;
    for (let i = Math.max(0,a); i <= Math.min(bars.length-1,b); i++) {
      if (bars[i].l < v) { v = bars[i].l; idx = i; }
    }
    return { v, i: idx };
  }
  function maxHighBetween(bars, a, b) {
    let v = -Infinity, idx = -1;
    for (let i = Math.max(0,a); i <= Math.min(bars.length-1,b); i++) {
      if (bars[i].h > v) { v = bars[i].h; idx = i; }
    }
    return { v, i: idx };
  }
  function firstCloseBreak(bars, from, to, level, dir, clear) {
    for (let i = Math.max(1,from); i <= Math.min(bars.length-1,to); i++) {
      const prev = bars[i-1].c, cur = bars[i].c;
      if (dir < 0 && prev >= level-clear*.25 && cur < level-clear) return i;
      if (dir > 0 && prev <= level+clear*.25 && cur > level+clear) return i;
    }
    return -1;
  }
  function breakoutOutcome(bars, breakI, level, dir, tol) {
    let retestI=-1, failedI=-1, continuation=0;
    const end=Math.min(bars.length-1, breakI+8);
    for(let i=breakI+1;i<=end;i++){
      const b=bars[i];
      if(dir>0){
        if(b.l<=level+tol && b.c>=level-tol*.15 && retestI<0) retestI=i;
        if(b.c<level-tol*.55){failedI=i;break;}
        if(b.c>level+tol*.8) continuation++;
      }else{
        if(b.h>=level-tol && b.c<=level+tol*.15 && retestI<0) retestI=i;
        if(b.c>level+tol*.55){failedI=i;break;}
        if(b.c<level-tol*.8) continuation++;
      }
    }
    return {retestI,failedI,continuation,confirmed:failedI<0&&(retestI>=0||continuation>=2)};
  }

  /* ---- Pattern Engine v2 --------------------------------------------------
     Structural patterns require neckline/level confirmation before receiving a
     confirmed badge. Scores combine symmetry, swing depth, recency and break
     quality. Breakouts are classified as confirmed/retested or failed instead
     of treating every close through a pivot as equally valid. */
  function detectPatterns(ph, pl, bars) {
    const marks = [];
    const n = bars.length;
    if (n < 12) return marks;
    const scale = structureScale(bars);
    const patternTol = Math.max(PAT_TOL, Math.min(5.0, scale * 0.75));
    const minSwing = Math.max(2.5, scale * 2.0);
    const breakoutNear = Math.max(0.3, Math.min(2.5, scale * 0.25));
    const breakoutClear = Math.max(0.4, Math.min(3.5, scale * 0.45));
    const from = Math.max(0, n - 500);
    const hh = ph.filter((p) => p.i >= from);
    const ll = pl.filter((p) => p.i >= from);
    const recencyScore = (i) => Math.max(0, 12 - (n-1-i)/35);

    /* Double Top — second top is only confirmed after neckline close break. */
    let lastDT=-1;
    for(let a=1;a<hh.length;a++){
      const p=hh[a-1], q=hh[a];
      const span=q.i-p.i;
      if(span<5||span>100||p.i<=lastDT)continue;
      const neck=minLowBetween(bars,p.i,q.i);
      const height=Math.max(p.v,q.v)-neck.v;
      const tol=Math.max(patternTol,height*.16);
      const symmetry=Math.max(0,1-Math.abs(q.v-p.v)/Math.max(tol,0.01));
      if(Math.abs(q.v-p.v)>tol||height<minSwing)continue;
      const br=firstCloseBreak(bars,q.i+1,q.i+35,neck.v,-1,breakoutClear*.65);
      const breakQuality=br>=0?Math.min(20,Math.max(0,(neck.v-bars[br].c)/Math.max(scale,.1))*8+10):0;
      const score=48+symmetry*18+Math.min(14,height/Math.max(scale,.1)*3)+breakQuality+recencyScore(q.i);
      const confirmed=br>=0;
      if(confirmed||q.i>=n-18){
        const t=confirmed?bars[br].time:q.t, v=confirmed?bars[br].l:q.v;
        marks.push(patternMark(t,v,confirmed?"belowBar":"aboveBar","circle","#ff9800","DT",score,confirmed));
        lastDT=q.i;
      }
    }

    /* Double Bottom — mirror of Double Top. */
    let lastDB=-1;
    for(let a=1;a<ll.length;a++){
      const p=ll[a-1], q=ll[a];
      const span=q.i-p.i;
      if(span<5||span>100||p.i<=lastDB)continue;
      const neck=maxHighBetween(bars,p.i,q.i);
      const depth=neck.v-Math.min(p.v,q.v);
      const tol=Math.max(patternTol,depth*.16);
      const symmetry=Math.max(0,1-Math.abs(q.v-p.v)/Math.max(tol,0.01));
      if(Math.abs(q.v-p.v)>tol||depth<minSwing)continue;
      const br=firstCloseBreak(bars,q.i+1,q.i+35,neck.v,1,breakoutClear*.65);
      const breakQuality=br>=0?Math.min(20,Math.max(0,(bars[br].c-neck.v)/Math.max(scale,.1))*8+10):0;
      const score=48+symmetry*18+Math.min(14,depth/Math.max(scale,.1)*3)+breakQuality+recencyScore(q.i);
      const confirmed=br>=0;
      if(confirmed||q.i>=n-18){
        const t=confirmed?bars[br].time:q.t, v=confirmed?bars[br].h:q.v;
        marks.push(patternMark(t,v,confirmed?"aboveBar":"belowBar","circle","#ff9800","DB",score,confirmed));
        lastDB=q.i;
      }
    }

    /* Head & Shoulders — shoulder symmetry + two neckline troughs + break. */
    let lastHS=-1;
    for(let b=1;b<hh.length-1;b++){
      const L=hh[b-1],M=hh[b],R=hh[b+1];
      if(R.i-L.i<10||R.i-L.i>150||M.i<=lastHS)continue;
      const leftNeck=minLowBetween(bars,L.i,M.i), rightNeck=minLowBetween(bars,M.i,R.i);
      const neck=(leftNeck.v+rightNeck.v)/2;
      const shoulderTol=Math.max(patternTol,scale*.9);
      const headLift=M.v-Math.max(L.v,R.v);
      const spacingRatio=(M.i-L.i)/Math.max(1,R.i-M.i);
      const shoulderSym=Math.max(0,1-Math.abs(L.v-R.v)/Math.max(shoulderTol,.1));
      const spacingSym=Math.max(0,1-Math.abs(1-spacingRatio)/1.2);
      if(headLift<Math.max(scale*.8,minSwing*.25)||Math.abs(L.v-R.v)>shoulderTol*1.6||spacingRatio<.45||spacingRatio>2.2)continue;
      const br=firstCloseBreak(bars,R.i+1,R.i+40,neck,-1,breakoutClear*.7);
      const score=50+shoulderSym*13+spacingSym*10+Math.min(12,headLift/Math.max(scale,.1)*5)+(br>=0?18:0)+recencyScore(R.i);
      const confirmed=br>=0;
      if(confirmed||R.i>=n-20){
        marks.push(patternMark(confirmed?bars[br].time:M.t,confirmed?bars[br].l:M.v,confirmed?"belowBar":"aboveBar","square",DOWN,"HS",score,confirmed));
        lastHS=R.i;
      }
    }

    /* Inverse Head & Shoulders. */
    let lastIHS=-1;
    for(let b=1;b<ll.length-1;b++){
      const L=ll[b-1],M=ll[b],R=ll[b+1];
      if(R.i-L.i<10||R.i-L.i>150||M.i<=lastIHS)continue;
      const leftNeck=maxHighBetween(bars,L.i,M.i), rightNeck=maxHighBetween(bars,M.i,R.i);
      const neck=(leftNeck.v+rightNeck.v)/2;
      const shoulderTol=Math.max(patternTol,scale*.9);
      const headDrop=Math.min(L.v,R.v)-M.v;
      const spacingRatio=(M.i-L.i)/Math.max(1,R.i-M.i);
      const shoulderSym=Math.max(0,1-Math.abs(L.v-R.v)/Math.max(shoulderTol,.1));
      const spacingSym=Math.max(0,1-Math.abs(1-spacingRatio)/1.2);
      if(headDrop<Math.max(scale*.8,minSwing*.25)||Math.abs(L.v-R.v)>shoulderTol*1.6||spacingRatio<.45||spacingRatio>2.2)continue;
      const br=firstCloseBreak(bars,R.i+1,R.i+40,neck,1,breakoutClear*.7);
      const score=50+shoulderSym*13+spacingSym*10+Math.min(12,headDrop/Math.max(scale,.1)*5)+(br>=0?18:0)+recencyScore(R.i);
      const confirmed=br>=0;
      if(confirmed||R.i>=n-20){
        marks.push(patternMark(confirmed?bars[br].time:M.t,confirmed?bars[br].h:M.v,confirmed?"aboveBar":"belowBar","square",UP,"IHS",score,confirmed));
        lastIHS=R.i;
      }
    }

    /* Breakout / retest / failed-break classification. */
    const evts=[...hh.map(p=>({...p,kind:"H"})),...ll.map(p=>({...p,kind:"L"}))].sort((a,b)=>a.i-b.i);
    let ei=0,res=null,sup=null,lastBo=-10;
    for(let i=Math.max(1,from);i<n;i++){
      while(ei<evts.length&&evts[ei].i<=i-PIVOT_K){const e=evts[ei++];if(e.kind==="H")res=e;else sup=e;}
      if(i-lastBo<=3)continue;
      const c=bars[i],pc=bars[i-1].c;
      let level=null,dir=0;
      if(res&&pc<=res.v+breakoutNear&&c.c>res.v+breakoutClear){level=res.v;dir=1;res=null;}
      else if(sup&&pc>=sup.v-breakoutNear&&c.c<sup.v-breakoutClear){level=sup.v;dir=-1;sup=null;}
      if(!dir)continue;
      const out=breakoutOutcome(bars,i,level,dir,Math.max(patternTol*.55,scale*.45));
      const distance=Math.abs(c.c-level)/Math.max(scale,.1);
      const baseScore=55+Math.min(18,distance*12)+Math.min(12,out.continuation*5)+(out.retestI>=0?12:0)+recencyScore(i);
      if(out.failedI>=0){
        const fb=bars[out.failedI];
        marks.push(patternMark(fb.time,dir>0?fb.h:fb.l,dir>0?"aboveBar":"belowBar",dir>0?"arrowDown":"arrowUp",dir>0?DOWN:UP,dir>0?"FB↓":"FB↑",Math.max(58,baseScore-18),true));
      }else{
        const code=out.retestI>=0?(dir>0?"BO+RT↑":"BO+RT↓"):(dir>0?"BO↑":"BO↓");
        marks.push(patternMark(c.time,dir>0?c.h:c.l,dir>0?"aboveBar":"belowBar",dir>0?"arrowUp":"arrowDown",dir>0?UP:DOWN,code,baseScore,out.confirmed));
      }
      lastBo=i;
    }

    /* Momentum runs — retain simple sequence context but score by run length. */
    const momentum=[];
    const runStart=Math.max(2,n-260);
    let rl=0,rd=0,rEnd=-1;
    const flushRun=()=>{
      if(rl>=4&&rEnd>=runStart){
        const b=bars[rEnd],score=clampScore(52+Math.min(36,(rl-4)*7)+recencyScore(rEnd));
        momentum.push(patternMark(b.time,rd===1?b.h:b.l,rd===1?"aboveBar":"belowBar",rd===1?"arrowUp":"arrowDown",rd===1?UP:DOWN,rd===1?`MOM↑×${rl}`:`MOM↓×${rl}`,score,true));
      }
    };
    for(let i=runStart;i<n;i++){
      const dir=bars[i].c>bars[i].o?1:bars[i].c<bars[i].o?-1:0;
      if(dir===0){flushRun();rd=0;rl=0;rEnd=-1;continue;}
      if(dir===rd){rl++;rEnd=i;}else{flushRun();rd=dir;rl=1;rEnd=i;}
    }
    flushRun();

    // De-dup and avoid hiding structural signals under momentum markers.
    const seen=new Set(),clean=[];
    const pushMark=(m)=>{const key=m.time+"|"+m.text.replace(/\s\d+%$/,'');if(seen.has(key))return false;seen.add(key);clean.push(m);return true;};
    marks.filter(m=>{const q=Number((m.text.match(/(\d+)%$/)||[])[1]||0);return q>=55;}).forEach(pushMark);
    const structTimes=clean.map(m=>m.time);
    let added=0;
    for(let i=momentum.length-1;i>=0&&added<10;i--){const m=momentum[i];if(structTimes.some(t=>Math.abs(t-m.time)<=2))continue;if(pushMark(m))added++;}
    clean.sort((a,b)=>a.time-b.time);
    return clean;
  }

'''
s=s[:start]+new+s[end:]
p.write_text(s)

Path('tests_pattern_engine_v2.py').write_text(r'''from pathlib import Path
s=Path('static/js/chart.js').read_text()
for token in [
 'function patternMark(', 'function firstCloseBreak(', 'function breakoutOutcome(',
 'Pattern Engine v2', 'BO+RT↑', 'BO+RT↓', 'FB↓', 'FB↑',
 'const shoulderSym=', 'const spacingSym=', 'const confirmed=br>=0',
 'q>=55', 'MOM↑×', 'MOM↓×'
]: assert token in s, token
assert 'DT ▼' not in s[s.index('function detectPatterns'):s.index('Auto Support / Resistance v2')]
assert 'DB ▲' not in s[s.index('function detectPatterns'):s.index('Auto Support / Resistance v2')]
for f in ['decision.py','robust_engine.py','app_core.py','drawings_persistence.py']:
    assert Path(f).exists()
print('Pattern Engine v2 contract OK')
''')
