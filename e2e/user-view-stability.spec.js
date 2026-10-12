const {test,expect}=require('@playwright/test');
const end='20260913000000360',next='20260913000000361',later='20260913000000362';
const armed={issue:next,target:'BIG',stake:500,tier:1,step:1};
const latest=(issue=end,number=8,time='2026-09-13 13:59:00')=>({round:{issue,number,block_time:time}});
const snapshot=page=>page.evaluate(()=>window.TRXChart._qa.displaySnapshot());
async function ready(page){await page.goto('/');await expect(page.locator('#conn-txt')).toHaveText('LIVE');await expect.poll(()=>page.evaluate(()=>window.TRXChart?._qa.displaySnapshot().bars.length||0)).toBeGreaterThan(300);}
async function draw(page){await page.locator('#dt-toggle-btn').click();await page.locator('[data-tool="hline"]').click();const b=await page.locator('#tv-chart').boundingBox();await page.mouse.click(b.x+b.width*.4,b.y+b.height*.5);await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().count)).toBe(1);}

test('an already observed latest round is applied when the initial state finally arrives',async({page})=>{
  let release,calls=0;const gate=new Promise(r=>release=r);
  await page.route('**/api/state',async r=>{await gate;return r.continue();});
  await page.route('**/api/latest',r=>{calls++;return r.fulfill({json:latest(next,8,'2026-09-13 14:00:00')});});
  try{await page.goto('/');await expect.poll(()=>calls).toBeGreaterThan(1);release();await expect.poll(()=>page.evaluate(()=>window.TRXChart?.getComparisons()?.latestIssue)).toBe(next);expect((await snapshot(page)).bars.length).toBe(361);}finally{release();}
});

test('failed gap recovery keeps the old walk and retries the same latest issue',async({page})=>{
  let advance=false,recover=false;
  await page.route('**/api/state',async r=>{const x=await r.fetch(),d=await x.json();d.strat_pending={...armed,tier:0,step:0};return r.fulfill({json:d});});
  await page.route('**/api/l1-capital',r=>r.fulfill({json:{ready:true,pending:armed,trades:[]}}));
  await page.route('**/api/latest',r=>r.fulfill({json:advance?latest(later,2,'2026-09-13 14:01:00'):latest()}));
  await page.route('**/api/history*',async r=>{
    if(advance&&!recover)return r.fulfill({status:503,json:{error:'temporary outage'}});
    const x=await r.fetch(),d=await x.json();if(advance)d.history.push([next,8,'2026-09-13 14:00:00'],[later,2,'2026-09-13 14:01:00']);return r.fulfill({json:d});
  });
  await ready(page);const before=(await snapshot(page)).bars.at(-1).c;await expect(page.locator('#st-pending')).toHaveText('BIG');advance=true;
  await expect(page.locator('#chart-update-status')).toContainText('Chart history delayed');expect((await snapshot(page)).bars.length).toBe(360);
  await expect(page.locator('#st-pending')).toHaveText('UNAVAILABLE');await expect(page.locator('#l1-stake')).toHaveText('—');
  recover=true;await expect.poll(()=>page.evaluate(()=>window.TRXChart.getComparisons().latestIssue),{timeout:10000}).toBe(later);
  expect((await snapshot(page)).bars.length).toBe(362);expect((await snapshot(page)).bars.at(-1).c).toBe(before);
  await expect(page.locator('#chart-update-status')).toBeHidden();expect(await page.evaluate(()=>lastResultTime)).toBe('2026-09-13 14:01:00');
});

test('malformed latest and state data retain the chart and recover without a new issue',async({page})=>{
  let mode='normal',badState=false;
  await page.route('**/api/latest',r=>r.fulfill({json:mode==='normal'?latest():latest(next,mode==='bad'?99:8,'2026-09-13 14:00:00')}));
  await page.route('**/api/state',async r=>{const x=await r.fetch(),d=await x.json();if(badState)d.history=[null];return r.fulfill({json:d});});
  await ready(page);mode='bad';await expect(page.locator('#chart-update-status')).toContainText('Latest chart update unavailable');expect((await snapshot(page)).bars.length).toBe(360);
  mode='good';await expect.poll(()=>page.evaluate(()=>window.TRXChart.getComparisons().latestIssue)).toBe(next);await expect(page.locator('#chart-update-status')).toBeHidden();
  badState=true;await expect(page.locator('#conn-txt')).toContainText('Connection error:');expect((await snapshot(page)).bars.length).toBe(361);
  badState=false;await expect(page.locator('#conn-txt')).toHaveText('LIVE');
});

test('invalid full history cannot replace the chart or saved drawings',async({page})=>{
  await ready(page);await draw(page);const before=JSON.stringify(await snapshot(page)),stored=await page.evaluate(()=>localStorage.getItem('trx_drawings_v3'));
  await page.route('**/api/history*',r=>r.fulfill({json:{history:[[end,null,'2026-09-13 13:59:00']]}}));
  await page.locator('#chart-refresh').click();await expect(page.locator('#chart-refresh-status')).toContainText('Refresh failed');expect(JSON.stringify(await snapshot(page))).toBe(before);expect(await page.evaluate(()=>localStorage.getItem('trx_drawings_v3'))).toBe(stored);
});

test('forming higher timeframe candles retain their bucket start and first issue',async({page})=>{
  await ready(page);await page.locator('.tf-btn[data-g="5"]').click();
  await page.evaluate(ids=>{window.TRXChart.appendLatest({issue:ids[0],number:8,type:'BIG',block_time:'2026-09-13 14:00:54'});},[next,later]);
  let s=await snapshot(page);expect(s.latestTime).toBe('2026-09-13 14:00:00');expect(s.latestAnchor).toBe(next);const count=s.bars.length;
  await page.evaluate(id=>{window.TRXChart.appendLatest({issue:id,number:2,type:'SMALL',block_time:'2026-09-13 14:01:54'});},later);
  s=await snapshot(page);expect(s.latestTime).toBe('2026-09-13 14:00:00');expect(s.latestAnchor).toBe(next);expect(s.bars.length).toBe(count);
});

test('a one-off native chart render failure is retried for unchanged source data',async({page})=>{
  await page.addInitScript(()=>{
    let api;Object.defineProperty(window,'LightweightCharts',{configurable:true,get:()=>api,set:library=>{
      api={...library,createChart(...args){const chart=library.createChart(...args),add=chart.addCandlestickSeries.bind(chart);chart.addCandlestickSeries=(...a)=>{const series=add(...a),set=series.setData.bind(series);series.setData=data=>{if(window.__failChartOnce){window.__failChartOnce=false;throw new Error('one-off renderer failure');}set(data);window.__nativeChartClose=data.at(-1)?.close;};return series;};return chart;}};
    }});
  });
  await ready(page);
  const result=await page.evaluate(()=>{const old=window.__nativeChartClose,history=window.TRXChart.studyInfo().rows.map(r=>({...r}));history[0].number=2;history[0].type='SMALL';const state={history,log:[]};window.__failChartOnce=true;let failed=false;try{window.TRXChart.update(state);}catch{failed=true;}const retained=window.__nativeChartClose;window.TRXChart.update({...state,history:history.map(r=>({...r}))});return {old,failed,retained,recovered:window.__nativeChartClose};});
  expect(result.failed).toBe(true);expect(result.retained).toBe(result.old);expect(result.recovered).toBe(result.old-2);
});

test('local save failure is visible and retry keeps the in-memory drawing',async({page})=>{
  await page.addInitScript(()=>{window.__failDrawingSaves=true;const original=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(k==='trx_drawings_v3'&&window.__failDrawingSaves)throw new DOMException('full','QuotaExceededError');return original.call(this,k,v);};});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));await ready(page);await draw(page);
  await expect(page.locator('#drawing-save-status')).toContainText('Drawing save failed');await expect(page.locator('#drawing-save-retry')).toBeVisible();expect(await page.evaluate(()=>localStorage.getItem('trx_drawings_v3'))).toBeNull();
  await page.evaluate(()=>window.__failDrawingSaves=false);await page.locator('#drawing-save-retry').click();await expect(page.locator('#drawing-save-status')).toContainText('Drawings saved locally');expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3')).length)).toBe(1);expect(errors).toEqual([]);
});

for(const kind of ['issue','future'])test(`sync ignores derived ${kind} anchor positions and JSON field order`,async({page})=>{
  const point=kind==='issue'?{p:99,t:10,lb:'20260913000000300',anchorLb:null,offset:null}:{p:99,t:400,lb:null,anchorLb:'20260913000000359',offset:40,futureTime:Date.UTC(2026,8,13,14,30)/60000};
  const row={id:'saved',type:'hline',color:'#2962ff',width:2,style:'solid',locked:false,hidden:false,extendLeft:false,extendRight:false,points:[point]};
  await page.addInitScript(r=>{localStorage.setItem('trx_draw_sync_token','fixture-token');localStorage.setItem('trx_drawings_v3',JSON.stringify([r]));},row);
  await page.route('**/api/drawings',r=>r.fulfill({json:{ok:true,revision:7,drawings:[row]}}));await ready(page);
  await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().serverRevision)).toBe(7);expect(await page.evaluate(()=>window.TRXDraw._dbg().serverConflict)).toBe(false);expect(await page.evaluate(()=>window.TRXDraw._dbg().count)).toBe(1);
});

test('a real remote drawing edit remains a conflict and preserves the local version',async({page})=>{
  const row={id:'saved',type:'hline',color:'#2962ff',width:2,style:'solid',locked:false,hidden:false,extendLeft:false,extendRight:false,points:[{p:99,t:10,lb:'20260913000000300',anchorLb:null,offset:null}]};
  await page.addInitScript(r=>{localStorage.setItem('trx_draw_sync_token','fixture-token');localStorage.setItem('trx_drawings_v3',JSON.stringify([r]));},row);
  await page.route('**/api/drawings',r=>r.fulfill({json:{ok:true,revision:7,drawings:[{...row,points:[{...row.points[0],p:101}]}]}}));await ready(page);
  await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().serverConflict)).toBe(true);expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3'))[0].points[0].p)).toBe(99);
});

test('hidden/offline tabs reduce polling and resume all public snapshots immediately',async({page})=>{
  const counts={state:0,latest:0,l1:0,daily:0};page.on('request',r=>{const p=new URL(r.url()).pathname;if(p==='/api/state')counts.state++;if(p==='/api/latest')counts.latest++;if(p==='/api/l1-capital')counts.l1++;if(p==='/api/12step/daily-report')counts.daily++;});
  await ready(page);await expect(page.locator('#d12-date')).not.toHaveText('—');
  await page.evaluate(()=>{window.__hidden=true;Object.defineProperty(document,'hidden',{configurable:true,get:()=>window.__hidden});document.dispatchEvent(new Event('visibilitychange'));});
  const hidden={...counts};await page.waitForTimeout(1800);expect(counts.latest-hidden.latest).toBeLessThanOrEqual(1);expect(counts.state-hidden.state).toBeLessThanOrEqual(1);
  await page.evaluate(()=>{window.__online=false;Object.defineProperty(navigator,'onLine',{configurable:true,get:()=>window.__online});window.dispatchEvent(new Event('offline'));});await expect(page.locator('#conn-txt')).toContainText('browser connection lost');
  const offline={...counts};await page.waitForTimeout(1800);expect(counts.latest).toBe(offline.latest);expect(counts.state).toBe(offline.state);
  await page.evaluate(()=>{window.__hidden=false;window.__online=true;window.dispatchEvent(new Event('online'));});await expect(page.locator('#conn-txt')).toHaveText('LIVE');await expect.poll(()=>counts.daily,{timeout:3000}).toBeGreaterThan(offline.daily);
});

test('unsynced drawings retry after connection recovery without losing local data',async({page})=>{
  await page.addInitScript(()=>localStorage.setItem('trx_draw_sync_token','fixture-token'));
  let failed=true,writes=0;await page.route('**/api/drawings',r=>{if(r.request().method()==='GET')return r.fulfill({json:{ok:true,revision:0,drawings:[]}});writes++;return r.fulfill({status:failed?503:200,json:failed?{error:'outage'}:{ok:true,revision:1}});});
  await ready(page);await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().serverRevision)).toBe(0);await draw(page);await expect.poll(()=>writes).toBe(1);
  failed=false;await page.evaluate(()=>window.dispatchEvent(new Event('trx:view-resume')));await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().serverRevision)).toBe(1);expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3')).length)).toBe(1);
});
