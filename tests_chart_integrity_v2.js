global.window = {};
global.document = { getElementById: () => null, querySelectorAll: () => [], addEventListener: () => {} };
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

const hammer = qa.hssShape({o:10,c:11,h:11.2,l:7});
const shootingStar = qa.hssShape({o:11,c:10,h:14,l:9.8});
if (hammer !== 'H') throw new Error(`Hammer geometry not detected: ${hammer}`);
if (shootingStar !== 'SS') throw new Error(`Shooting Star geometry not detected: ${shootingStar}`);
if (qa.hssShape({o:10,c:10,h:11,l:9}) !== null) throw new Error('Doji must not be labeled Hammer / Shooting Star');

const closes = [105,106,107,106,104,102,101,102,104,106,107,106,104,102,101,102,104,106,107,106,104,102,101,102,104,106,107,106,104,102,101,102,104,106,107,106];
const hssBars = closes.map((c,i) => ({time:i+1,o:c-(i%2?1:-1),h:c+1,l:c-1,c}));
hssBars[31]={time:32,o:107,c:106,h:108,l:105};
hssBars[32]={time:33,o:106,c:105,h:107,l:104};
hssBars[33]={time:34,o:105,c:104,h:106,l:103};
hssBars[34]={time:35,o:104,c:103,h:105,l:102};
hssBars[35]={time:36,o:101,c:102,h:102.2,l:98};
hssBars.push({time:37,o:102,c:103,h:104,l:101});
const fullBuckets = Array(hssBars.length).fill(5);
const candidates = qa.detectHssCandidates(hssBars, fullBuckets, 5);
if (!candidates.some(m => m.time === 36 && m.text === 'H@S')) throw new Error('Closed Hammer at prior support was not marked');
const mirroredBars = hssBars.map(b => ({time:b.time,o:200-b.o,c:200-b.c,h:200-b.l,l:200-b.h}));
if (!qa.detectHssCandidates(mirroredBars, fullBuckets, 5).some(m => m.time === 36 && m.text === 'SS@R')) throw new Error('Closed Shooting Star at prior resistance was not marked');
const incomplete = fullBuckets.slice(); incomplete[35]=4;
if (qa.detectHssCandidates(hssBars, incomplete, 5).some(m => m.time === 36)) throw new Error('Incomplete 5m bucket was marked');
if (qa.detectHssCandidates(hssBars, fullBuckets, 1).length) throw new Error('H/SS study must stay scoped to 5m');

const cases = [[20000,1,4320],[20000,5,2880],[20000,15,960],[20000,60,240],[100,1,100]];
for (const [avail, tf, want] of cases) {
  const got = qa.structuralLookbackBars(avail, tf);
  if (got !== want) throw new Error(`lookback ${tf}m expected ${want}, got ${got}`);
}
console.log('Chart Analysis Integrity v2 QA passed');
