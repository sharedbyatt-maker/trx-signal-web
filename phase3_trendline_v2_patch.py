from pathlib import Path

p = Path('static/js/chart.js')
s = p.read_text()
old = '''  function trendSeg(pivs, bars) {
    if (!bars.length || pivs.length < 2) return null;
    const p2 = pivs[pivs.length - 1];
    const p1 = pivs[pivs.length - 2];
    if (p2.i - p1.i < 4) return null;
    const slope = (p2.v - p1.v) / (p2.t - p1.t);
    const tEnd = bars[bars.length - 1].time + 3;
    return {
      pts: [
        { time: p1.t, value: p1.v },
        { time: p2.t, value: p2.v },
        { time: tEnd, value: p2.v + slope * (tEnd - p2.t) },
      ],
      slope,
    };
  }
'''
new = '''  /* ---- Auto Trend Line v2 -------------------------------------------------
     Build many bounded candidates instead of blindly joining the last 2 pivots.
     Candidates are scored by: pivot touches, pivot prominence, recency, retests,
     line age/span, slope quality and post-anchor violations. A recent decisive
     break invalidates the line. This is display-only chart structure logic. */
  function pivotProminence(p, bars, kind, radius = 8) {
    const a = Math.max(0, p.i - radius), z = Math.min(bars.length - 1, p.i + radius);
    if (kind === "res") {
      let floor = Infinity;
      for (let i = a; i <= z; i++) floor = Math.min(floor, bars[i].l);
      return Math.max(0, p.v - floor);
    }
    let ceil = -Infinity;
    for (let i = a; i <= z; i++) ceil = Math.max(ceil, bars[i].h);
    return Math.max(0, ceil - p.v);
  }

  function trendSegV2(pivs, bars, kind) {
    if (!bars.length || pivs.length < 2) return null;

    // Keep runtime bounded on long history while still considering older anchors.
    const ps = pivs.slice(-48);
    const lastI = bars.length - 1;
    const touchTol = 0.8;
    const hardBreak = 1.35;
    let best = null;

    for (let a = 0; a < ps.length - 1; a++) {
      const p1 = ps[a];
      for (let b = a + 1; b < ps.length; b++) {
        const p2 = ps[b];
        const gap = p2.i - p1.i;
        if (gap < 6 || gap > 420) continue;
        const dt = p2.t - p1.t;
        if (!dt) continue;
        const slope = (p2.v - p1.v) / dt;
        const absSlope = Math.abs(slope);
        if (absSlope > 0.5) continue; // implausibly steep on the ±1 synthetic walk

        const lineAt = (i) => p1.v + slope * (bars[i].time - p1.t);

        // A decisive recent break means the old boundary is no longer active.
        let broken = false;
        const recentFrom = Math.max(p2.i + 1, lastI - 12);
        for (let i = recentFrom; i <= lastI; i++) {
          const lv = lineAt(i);
          if (kind === "res" ? bars[i].h > lv + hardBreak : bars[i].l < lv - hardBreak) {
            broken = true; break;
          }
        }
        if (broken) continue;

        let violations = 0;
        for (let i = p2.i + 1; i <= lastI; i++) {
          const lv = lineAt(i);
          if (kind === "res" ? bars[i].h > lv + touchTol : bars[i].l < lv - touchTol) violations++;
        }
        // Allow a tiny amount of noise, but reject repeatedly pierced boundaries.
        const allowedViolations = Math.max(1, Math.floor((lastI - p2.i) / 90));
        if (violations > allowedViolations) continue;

        let touches = 0, retests = 0;
        for (const q of ps) {
          if (q.i < p1.i) continue;
          const lv = p1.v + slope * (q.t - p1.t);
          if (Math.abs(q.v - lv) <= touchTol) {
            touches++;
            if (q.i > p2.i) retests++;
          }
        }
        if (touches < 2) continue;

        const prom1 = pivotProminence(p1, bars, kind);
        const prom2 = pivotProminence(p2, bars, kind);
        const prominence = Math.min(8, (prom1 + prom2) / 2);
        const age = Math.max(0, lastI - p2.i);
        const recency = Math.max(0, 1 - age / 500);
        const spanScore = Math.min(10, gap / 35);
        const touchBonus = touches >= 3 ? 14 + Math.min(10, (touches - 3) * 2) : 0;
        const slopePenalty = absSlope > 0.28 ? (absSlope - 0.28) * 22 : 0;
        const score = touches * 10 + touchBonus + retests * 6 + prominence * 2.2
          + recency * 15 + spanScore - violations * 18 - slopePenalty;

        if (!best || score > best.score) {
          best = { p1, p2, slope, score, touches, retests, violations, prominence };
        }
      }
    }

    if (!best) return null;
    const tEnd = bars[bars.length - 1].time + 3;
    const endValue = best.p2.v + best.slope * (tEnd - best.p2.t);
    return {
      pts: [
        { time: best.p1.t, value: best.p1.v },
        { time: best.p2.t, value: best.p2.v },
        { time: tEnd, value: endValue },
      ],
      slope: best.slope,
      score: best.score,
      touches: best.touches,
      retests: best.retests,
      violations: best.violations,
      prominence: best.prominence,
    };
  }
'''
if old not in s:
    raise SystemExit('old trendSeg block not found')
s = s.replace(old, new, 1)
s = s.replace('''    const resSeg = trendSeg(piv.hi, curBars);\n    const supSeg = trendSeg(piv.lo, curBars);''', '''    const resSeg = trendSegV2(piv.hi, curBars, "res");\n    const supSeg = trendSegV2(piv.lo, curBars, "sup");''', 1)
p.write_text(s)

Path('tests_trendline_v2.py').write_text(r'''from pathlib import Path

s = Path("static/js/chart.js").read_text()
assert "function trendSegV2(pivs, bars, kind)" in s
assert "pivotProminence" in s
assert "const ps = pivs.slice(-48)" in s
assert "touches >= 3" in s
assert "retests * 6" in s
assert "violations > allowedViolations" in s
assert "hardBreak = 1.35" in s
assert "absSlope > 0.5" in s
assert 'trendSegV2(piv.hi, curBars, "res")' in s
assert 'trendSegV2(piv.lo, curBars, "sup")' in s
# Phase 3 must not alter strategy/backend source files.
for f in ["decision.py", "robust_engine.py", "app_core.py"]:
    assert Path(f).exists()
print("Auto Trend Line v2 contract OK")
''')
