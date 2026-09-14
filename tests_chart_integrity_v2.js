global.window = {};
global.document = { getElementById: () => null, querySelectorAll: () => [] };
require('./static/js/chart.js');
const qa = window.TRXChart._qa;
if (!qa) throw new Error('QA helpers unavailable');

function bars(wick) {
  const out = [];
  for (let i = 0; i < 18; i++) {
    const c = 10 + i;
    out.push({time:i+1,o:c-1,h:c+wick,l:c-wick,c});
  }
  return out;
}
const tight = qa.calcStoch(bars(1), 14, 3, 3);
const wide = qa.calcStoch(bars(6), 14, 3, 3);
const kt = tight.k.at(-1), kw = wide.k.at(-1);
if (!(Number.isFinite(kt) && Number.isFinite(kw))) throw new Error('Stoch did not produce finite K');
if (Math.abs(kt - kw) < 1) throw new Error('Stoch is not responding to candle high/low wicks');
if (!Number.isFinite(wide.d.at(-1))) throw new Error('Stoch D smoothing missing');

const cases = [[20000,1,4320],[20000,5,2880],[20000,15,960],[20000,60,240],[100,1,100]];
for (const [avail, tf, want] of cases) {
  const got = qa.structuralLookbackBars(avail, tf);
  if (got !== want) throw new Error(`lookback ${tf}m expected ${want}, got ${got}`);
}
console.log('Chart Analysis Integrity v2 QA passed');
