const {test,expect}=require('@playwright/test');
const next='20260913000000361';
const armed={target:'BIG',issue:next,stake:500,tier:1,step:1};

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
