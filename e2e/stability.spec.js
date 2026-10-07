const {test,expect}=require('@playwright/test');
const next='20260913000000361';
const armed={target:'BIG',issue:next,stake:500,tier:1,step:1};

test('unchanged history reuses timeframe summaries and older corrections rebuild them',async({page})=>{
  await page.goto('/');
  await expect(page.locator('#mc-rsi')).not.toHaveText('—');
  const result=await page.evaluate(()=>{
    const history=Array.from({length:2000},(_,i)=>({issue:String(10000+i),
      type:i%3?'BIG':'SMALL',number:i%3?8:2,
      block_time:new Date(Date.UTC(2026,8,13,0,i)).toISOString().slice(0,19).replace('T',' ')}));
    window.TRXChart.update({history,log:[]});
    const original=window.TRXChart.getComparisons();
    window.TRXChart.update({history:history.map(r=>({...r})),log:[]});
    const reused=window.TRXChart.getComparisons()===original;
    const corrected=history.map(r=>({...r}));
    corrected[0].type='BIG'; corrected[0].number=8;
    window.TRXChart.update({history:corrected,log:[]});
    const after=window.TRXChart.getComparisons();
    return {reused,changed:after!==original,delta:after.frames[0].ema5-original.frames[0].ema5,
      chartEma:window.TRXChart.getContext().ema5,comparisonEma:after.frames[0].ema5};
  });
  expect(result.reused).toBe(true);
  expect(result.changed).toBe(true);
  expect(result.delta).toBeCloseTo(2,6);
  expect(result.chartEma).toBeCloseTo(result.comparisonEma,6);
});

test('a hung L1 response body cannot stop signal polling permanently',async({page})=>{
  await page.addInitScript(()=>{
    const nativeFetch=window.fetch;
    let first=true;
    window.fetch=async(...args)=>{
      if(first&&String(args[0])==='/api/l1-capital'){
        first=false;
        return {ok:true,json:()=>new Promise(()=>{})};
      }
      return nativeFetch(...args);
    };
  });
  await page.route('**/api/l1-capital',route=>route.fulfill({json:{ready:true,pending:armed,trades:[]}}));
  await page.goto('/');
  await expect(page.locator('#conn-txt')).toHaveText('LIVE');
  await expect(page.locator('#l1-pending')).toHaveText('BIG',{timeout:12000});
});

test('latest chart fallback cannot make a failed state connection appear live',async({page})=>{
  let failState=false,advance=false;
  await page.route('**/api/state',route=>failState?route.abort():route.continue());
  await page.route('**/api/latest',route=>route.fulfill({json:{round:{
    issue:advance?next:'20260913000000360',number:8,
    block_time:advance?'2026-09-13 14:00:00':'2026-09-13 13:59:00'}}}));
  await page.goto('/');
  await expect(page.locator('#conn-txt')).toHaveText('LIVE');
  await expect(page.locator('#mc-rsi')).not.toHaveText('—');
  await page.evaluate(()=>{window.TRXChart.appendLatest=()=>false;});
  failState=true;
  await expect(page.locator('#conn-txt')).toContainText('Connection error:');
  advance=true;
  await expect.poll(()=>page.evaluate(()=>window.TRXChart.getComparisons().latestIssue)).toBe(next);
  await expect(page.locator('#conn-txt')).toContainText('Connection error:');
  await expect(page.locator('#mc-rsi')).toHaveText('—');
});

test('a slow history request cannot block state, chart controls or polling',async({page})=>{
  let release;
  const gate=new Promise(resolve=>{release=resolve;});
  await page.route('**/api/history**',async route=>{await gate;await route.continue();});
  try {
    await page.goto('/');
    await expect(page.locator('#conn-txt')).toHaveText('LIVE');
    await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
    await page.locator('.tf-btn[data-g="5"]').click();
    await expect(page.locator('#lg-tf')).toHaveText('5m');
  } finally {release();}
});

test('a hung state request times out and subsequent polling recovers',async({page})=>{
  let calls=0;
  await page.route('**/api/state',async route=>{
    calls++;
    if(calls===1){await new Promise(resolve=>setTimeout(resolve,8500));try{await route.abort();}catch{}return;}
    await route.continue();
  });
  await page.goto('/');
  await expect(page.locator('#conn-txt')).toHaveText('LIVE',{timeout:15000});
  expect(calls).toBeGreaterThan(1);
  await expect(page.locator('#mc-rsi')).not.toHaveText('—');
});

test('offline state clears both sidebar and focus signals then recovers',async({page})=>{
  let offline=false;
  await page.route('**/api/state',async route=>{
    const r=await route.fetch(),d=await r.json();
    d.connected=!offline;d.feed_health.status=offline?'STALE':'LIVE';
    d.strat_pending={...armed,tier:0,step:0};
    await route.fulfill({json:d});
  });
  await page.route('**/api/l1-capital',route=>route.fulfill({json:{ready:true,pending:armed,trades:[]}}));
  await page.goto('/');
  await expect(page.locator('#l1-pending')).toHaveText('BIG');
  await expect(page.locator('#st-pending')).toHaveText('BIG');
  offline=true;
  await expect(page.locator('#st-pending')).toHaveText('UNAVAILABLE');
  await expect(page.locator('#l1-stake')).toHaveText('—');
  await expect(page.locator('#focus-step')).not.toContainText('BIG');
  await expect(page.locator('#focus-l1')).not.toContainText('BIG');
  await expect(page.locator('#focus-next')).toHaveText('—');
  offline=false;
  await expect(page.locator('#st-pending')).toHaveText('BIG');
  await expect(page.locator('#l1-pending')).toHaveText('BIG');
});

test('a completed target disappears from all signal surfaces before state catches up',async({page})=>{
  let advance=false;
  await page.route('**/api/state',async route=>{
    const r=await route.fetch(),d=await r.json();d.strat_pending={...armed,tier:0,step:0};await route.fulfill({json:d});
  });
  await page.route('**/api/l1-capital',route=>route.fulfill({json:{ready:true,pending:armed,trades:[]}}));
  await page.route('**/api/latest',route=>route.fulfill({json:{round:{issue:advance?next:'20260913000000360',number:8,block_time:advance?'2026-09-13 14:00:00':'2026-09-13 13:59:00'}}}));
  await page.goto('/');await expect(page.locator('#st-pending')).toHaveText('BIG');await expect(page.locator('#l1-pending')).toHaveText('BIG');
  advance=true;
  await expect(page.locator('#st-pending')).toHaveText('WAITING');
  await expect(page.locator('#l1-pending')).toHaveText('WAITING');
  await expect(page.locator('#l1-stake')).toHaveText('—');
});

test('browser storage restrictions cannot crash sound controls or live updates',async({page})=>{
  await page.addInitScript(()=>{
    Storage.prototype.getItem=()=>{throw new DOMException('Disabled','SecurityError');};
    Storage.prototype.setItem=()=>{throw new DOMException('Disabled','SecurityError');};
  });
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/');await expect(page.locator('#conn-txt')).toHaveText('LIVE');
  await page.locator('#bell-btn').click();await expect(page.locator('#bell-btn')).not.toHaveClass(/off/);
  await page.locator('#bell-btn').click();await expect(page.locator('#bell-btn')).toHaveClass(/off/);
  expect(errors).toEqual([]);
});

test('drawing saves serialize concurrent writes instead of conflicting with themselves',async({page})=>{
  await page.addInitScript(()=>localStorage.setItem('trx_draw_sync_token','local-test'));
  let revision=0,active=0,maxActive=0,writes=0;
  await page.route('**/api/drawings',async route=>{
    if(route.request().method()==='GET')return route.fulfill({json:{ok:true,revision,drawings:[]}});
    active++;maxActive=Math.max(maxActive,active);writes++;
    const data=route.request().postDataJSON();
    await new Promise(resolve=>setTimeout(resolve,250));
    const correct=data.expected_revision===revision;
    if(correct)revision++;
    active--;
    await route.fulfill({status:correct?200:409,json:{ok:correct,revision}});
  });
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().serverRevision)).toBe(0);
  await page.evaluate(()=>Promise.all([window.TRXDraw.pushServer(),window.TRXDraw.pushServer()]));
  await expect.poll(()=>writes).toBe(2);
  expect(maxActive).toBe(1);
  await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().serverConflict)).toBe(false);
});

test('daily report failures are visible and settled history remains available',async({page})=>{
  let calls=0;
  await page.route('**/api/12step/daily-report**',route=>{calls++;return route.fulfill({status:503,json:{error:'temporarily unavailable'}});});
  await page.goto('/');
  await expect(page.locator('#d12-status')).toHaveText('Report unavailable · last loaded results retained');
  await page.locator('#history-tab').click();
  await expect(page.locator('#signal-history-status')).toContainText('12-Step history temporarily unavailable');
  expect(calls).toBe(1);
});

test('enabled bell alerts each current engine signal once without polling duplicates',async({page})=>{
  await page.addInitScript(()=>{
    window.__notices=[];
    window.Notification=class {
      static permission='granted';
      constructor(_title,options){window.__notices.push(options.body);}
    };
  });
  await page.route('**/api/state',async route=>{
    const r=await route.fetch(),d=await r.json();d.strat_pending={...armed,tier:0,step:0};await route.fulfill({json:d});
  });
  await page.route('**/api/l1-capital',route=>route.fulfill({json:{ready:true,pending:armed,trades:[]}}));
  await page.goto('/');await expect(page.locator('#st-pending')).toHaveText('BIG');
  await page.locator('#bell-btn').click();
  await expect.poll(()=>page.evaluate(()=>window.__notices.length)).toBe(2);
  await page.waitForTimeout(1700);
  expect(await page.evaluate(()=>window.__notices.length)).toBe(2);
  expect(await page.evaluate(()=>window.__notices.some(x=>x.startsWith('L1 CAPITAL BIG')))).toBe(true);
  expect(await page.evaluate(()=>window.__notices.some(x=>x.startsWith('12-STEP BIG')))).toBe(true);
});
