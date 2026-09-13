from pathlib import Path
p=Path('static/js/chart.js')
s=p.read_text()

s=s.replace('''  let curStochValues = [];\n''','''  let curStochValues = [];\n  let liveInd = null;\n''',1)

needle='''  /* ================= bars from BIG/SMALL walk ================= */\n'''
helpers=r'''  function seedLiveIndicators(closes) {
    if (!closes.length) { liveInd = null; return; }
    const ema5 = calcEma(closes, 5), ema15 = calcEma(closes, 15), ema100 = calcEma(closes, 100);
    const rsi = calcRsi(closes, 14);
    const macd = calcMacd(closes, 12, 26, 9);
    const st = calcStoch(closes, 14, 3, 3);

    // Wilder RSI state, seeded exactly like calcRsi().
    let ag = null, al = null;
    if (closes.length >= 15) {
      let g = 0, l = 0;
      for (let i = 1; i <= 14; i++) {
        const d = closes[i] - closes[i - 1];
        if (d > 0) g += d; else l -= d;
      }
      ag = g / 14; al = l / 14;
      for (let i = 15; i < closes.length; i++) {
        const d = closes[i] - closes[i - 1];
        ag = (ag * 13 + Math.max(d, 0)) / 14;
        al = (al * 13 + Math.max(-d, 0)) / 14;
      }
    }

    liveInd = {
      ema5: ema5.at(-1), ema15: ema15.at(-1), ema100: ema100.at(-1),
      ema12: calcEma(closes, 12).at(-1), ema26: calcEma(closes, 26).at(-1),
      rsiAg: ag, rsiAl: al,
      macdSignal: macd.signal.at(-1),
      stochRaw: [], stochK: [],
      lastClose: closes.at(-1), count: closes.length,
    };
    const raw = new Array(closes.length).fill(null);
    for (let i = 13; i < closes.length; i++) {
      let hh=-Infinity,ll=Infinity;
      for (let j=i-13;j<=i;j++){ if(closes[j]>hh)hh=closes[j]; if(closes[j]<ll)ll=closes[j]; }
      raw[i]=hh===ll?50:((closes[i]-ll)/(hh-ll))*100;
    }
    liveInd.stochRaw = raw.slice(-3).filter((v)=>v!=null);
    liveInd.stochK = st.k.slice(-3).filter((v)=>v!=null);
    curRsiValues = rsi.slice();
    curMacdValues = macd.macd.slice();
    curStochValues = st.k.slice();
  }

  function emaNext(prev, value, period, countBefore, closes) {
    if (countBefore + 1 < period) return null;
    if (countBefore + 1 === period) {
      const tail = closes.slice(-period);
      return tail.reduce((a,b)=>a+b,0)/period;
    }
    if (prev == null) return calcEma(closes, period).at(-1);
    const k=2/(period+1);
    return value*k + prev*(1-k);
  }

  function updateLiveIndicators(close, time) {
    if (!liveInd || group !== 1) return false;
    const closes = curBars.map((b)=>b.c);
    const before = liveInd.count;
    const prevClose = liveInd.lastClose;

    liveInd.ema5 = emaNext(liveInd.ema5, close, 5, before, closes);
    liveInd.ema15 = emaNext(liveInd.ema15, close, 15, before, closes);
    liveInd.ema100 = emaNext(liveInd.ema100, close, 100, before, closes);
    liveInd.ema12 = emaNext(liveInd.ema12, close, 12, before, closes);
    liveInd.ema26 = emaNext(liveInd.ema26, close, 26, before, closes);

    if (liveInd.ema5 != null) emaFastSeries.update({time,value:liveInd.ema5});
    if (liveInd.ema15 != null) emaSlowSeries.update({time,value:liveInd.ema15});
    if (liveInd.ema100 != null) emaLongSeries.update({time,value:liveInd.ema100});

    let rsiVal=null;
    if (before >= 14 && liveInd.rsiAg != null && liveInd.rsiAl != null) {
      const d=close-prevClose;
      liveInd.rsiAg=(liveInd.rsiAg*13+Math.max(d,0))/14;
      liveInd.rsiAl=(liveInd.rsiAl*13+Math.max(-d,0))/14;
      rsiVal=liveInd.rsiAl===0?100:100-100/(1+liveInd.rsiAg/liveInd.rsiAl);
    }
    curRsiValues.push(rsiVal);
    if (rsiVal!=null && rsiSeries) rsiSeries.update({time,value:rsiVal});
    if (opts.rsi) updateRsiLegend(rsiVal);

    let macdVal=null, sigVal=null, histVal=null;
    if (liveInd.ema12!=null && liveInd.ema26!=null) {
      macdVal=liveInd.ema12-liveInd.ema26;
      const k=2/10;
      liveInd.macdSignal=liveInd.macdSignal==null?macdVal:macdVal*k+liveInd.macdSignal*(1-k);
      sigVal=liveInd.macdSignal; histVal=macdVal-sigVal;
    }
    curMacdValues.push(macdVal);
    if (macdVal!=null && macdLineSeries) macdLineSeries.update({time,value:macdVal});
    if (sigVal!=null && macdSigSeries) macdSigSeries.update({time,value:sigVal});
    if (histVal!=null && macdHistSeries) macdHistSeries.update({time,value:histVal,color:histVal>=0?'rgba(8,153,129,.55)':'rgba(242,54,69,.5)'});
    if (opts.macd) updateMacdLegend(macdVal);

    let raw=null,kVal=null,dVal=null;
    if (closes.length>=14) {
      const tail=closes.slice(-14), hh=Math.max(...tail), ll=Math.min(...tail);
      raw=hh===ll?50:((close-ll)/(hh-ll))*100;
      liveInd.stochRaw.push(raw); if(liveInd.stochRaw.length>3)liveInd.stochRaw.shift();
      if(liveInd.stochRaw.length===3) kVal=liveInd.stochRaw.reduce((a,b)=>a+b,0)/3;
      if(kVal!=null){ liveInd.stochK.push(kVal); if(liveInd.stochK.length>3)liveInd.stochK.shift(); }
      if(liveInd.stochK.length===3) dVal=liveInd.stochK.reduce((a,b)=>a+b,0)/3;
    }
    curStochValues.push(kVal);
    if(kVal!=null && stochKSeries) stochKSeries.update({time,value:kVal});
    if(dVal!=null && stochDSeries) stochDSeries.update({time,value:dVal});
    if(opts.stoch) updateStochLegend(kVal);

    liveInd.lastClose=close; liveInd.count=before+1;
    return true;
  }

'''
if needle not in s: raise SystemExit('bars needle missing')
s=s.replace(needle,helpers+needle,1)

old='''    const closes = curBars.map((b) => b.c);\n\n    const emaFpts = linePoints(calcEma(closes, 5));\n'''
new='''    const closes = curBars.map((b) => b.c);\n    seedLiveIndicators(closes);\n\n    const emaFpts = linePoints(calcEma(closes, 5));\n'''
if old not in s: raise SystemExit('closes seed spot missing')
s=s.replace(old,new,1)

old2='''    curLabelMap.set(issue, time);\n    lastLen = curBars.length;\n    updateLegend(curBars[curBars.length - 1]);\n\n    if (window.TRXDraw && window.TRXDraw.onData) {\n'''
new2='''    curLabelMap.set(issue, time);\n    lastLen = curBars.length;\n    try { updateLiveIndicators(close, time); } catch (e) { /* full state refresh will reconcile */ }\n    updateLegend(curBars[curBars.length - 1]);\n\n    if (window.TRXDraw && window.TRXDraw.onData) {\n'''
if old2 not in s: raise SystemExit('append spot missing')
s=s.replace(old2,new2,1)

s=s.replace('''  /* ---- ultra-fast 1m candle append ----\n     /api/latest uses this path so a fresh result does not rebuild 10 days of\n     candles/indicators just to paint one bar. The normal /api/state refresh\n     follows shortly and performs the authoritative full indicator rebuild. */\n''','''  /* ---- ultra-fast 1m candle + indicator append ----\n     /api/latest updates the fresh candle plus EMA/RSI/MACD/Stoch immediately.\n     The normal /api/state refresh remains the authoritative full reconciliation. */\n''',1)

p.write_text(s)
Path('tests_fast_live_indicators_v2.py').write_text(r'''from pathlib import Path
s=Path("static/js/chart.js").read_text()
for x in [
 "let liveInd = null","function seedLiveIndicators(closes)","function updateLiveIndicators(close, time)",
 "function emaNext(prev, value, period, countBefore, closes)","emaFastSeries.update({time,value:liveInd.ema5})",
 "rsiSeries.update({time,value:rsiVal})","macdLineSeries.update({time,value:macdVal})",
 "macdSigSeries.update({time,value:sigVal})","macdHistSeries.update({time,value:histVal",
 "stochKSeries.update({time,value:kVal})","stochDSeries.update({time,value:dVal})",
 "updateLiveIndicators(close, time)","seedLiveIndicators(closes);"
]: assert x in s, x
assert "The normal /api/state refresh remains the authoritative full reconciliation" in s
for f in ["decision.py","robust_engine.py","app_core.py"]: assert Path(f).exists()
print("Fast Live Indicator Update contract OK")
''')
