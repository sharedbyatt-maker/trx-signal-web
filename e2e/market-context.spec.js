const {test, expect} = require('@playwright/test');

test('insight tabs support keyboard navigation and preserve the chart', async ({page}, testInfo) => {
  await page.goto('/');
  await expect(page.locator('#mc-rsi')).not.toHaveText('—');
  await expect(page.locator('#market-panel')).toBeVisible();
  await page.locator('#context-tab').focus();
  await page.keyboard.press('ArrowRight');
  await expect(page.locator('#history-tab')).toBeFocused();
  await expect(page.locator('#history-tab')).toHaveAttribute('aria-selected','true');
  await expect(page.locator('#market-panel')).toBeHidden();
  await expect(page.locator('#signal-history-panel')).toBeVisible();
  await page.keyboard.press('Home');
  await expect(page.locator('#context-tab')).toBeFocused();
  await expect(page.locator('#market-panel')).toBeVisible();
  await page.locator('.tf-btn[data-g="5"]').click();
  await expect(page.locator('#mc-timeframe')).toContainText('5m conditions');
  await expect(page.locator('#mc-rsi')).not.toHaveText('—');
  await page.locator('#market-card').scrollIntoViewIfNeeded();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth+1)).toBeTruthy();
  await testInfo.attach('market-context-'+testInfo.project.name,{body:await page.screenshot(),contentType:'image/png'});
});

test('history combines settled engine bets and filters without invented entries', async ({page}) => {
  await page.route('**/api/l1-capital', route=>route.fulfill({json:{ready:true, pending:null, trades:[
    {issue:'20261003103010003',time:'2026-10-03 00:02:00',target:'BIG',stake:500,won:true,pnl:480},
    {issue:'20261003103010001',time:'2026-10-03 00:00:00',target:'SMALL',stake:1000,won:false,pnl:-1000},
  ]}}));
  await page.route('**/api/12step/daily-report**', route=>route.fulfill({json:{report:{recent_events:[
    {issue:'20261003103010004',target:'BIG',stake:500,outcome:'SIGNAL'},
    {issue:'20261003103010002',target:'SMALL',stake:500,outcome:'LOSS',pnl:-500},
  ]},history:[]}}));
  await page.goto('/');
  await page.locator('#history-tab').click();
  await expect(page.locator('#signal-history-body tr')).toHaveCount(3);
  await expect(page.locator('#signal-history-body tr').first()).toContainText('+480');
  await expect(page.locator('#signal-history-body')).not.toContainText('010004');
  await page.locator('[data-engine="12-STEP"]').click();
  await expect(page.locator('#signal-history-body tr')).toHaveCount(1);
  await expect(page.locator('#signal-history-body')).toContainText('-500');
  await page.locator('[data-engine="L1 CAPITAL"]').click();
  await expect(page.locator('#signal-history-body tr')).toHaveCount(2);
  await expect(page.locator('#signal-history-body')).not.toContainText('12-STEP');
  await expect(page.locator('#signal-history-status')).toContainText('model results');
});

test('context hides actionable state when the feed is stale', async ({page}) => {
  await page.route('**/api/state', async route=>{
    const response=await route.fetch(), data=await response.json();
    data.feed_health={status:'STALE'};
    data.strat.pending={target:'BIG',issue:'99999999999999999'};
    await route.fulfill({json:data});
  });
  await page.goto('/');
  await expect(page.locator('#mc-setup')).toHaveText('UNAVAILABLE');
  await expect(page.locator('#mc-rsi')).toHaveText('—');
  await expect(page.locator('#mc-rule')).toContainText('no valid setup');
});

test('context uses EMA and RSI from the selected chart and shows authoritative L1 rule wait', async ({page}) => {
  await page.route('**/api/l1-capital',route=>route.fulfill({json:{ready:true,pending:null,waiting_rule:{rule:'R05'},trades:[]}}));
  await page.goto('/');
  await expect(page.locator('#mc-rule')).toContainText('R05');
  await expect(page.locator('#mc-setup-detail')).toContainText('RULE WAIT');
  await expect(page.locator('#mc-rsi')).not.toHaveText('—');
  const current = await page.evaluate(()=>window.TRXChart.getContext());
  await expect(page.locator('#mc-rsi')).toHaveText(current.rsi.toFixed(1));
  const direction = await page.locator('#mc-trend').textContent();
  await expect(page.locator('#mc-trend-icon')).toHaveText(direction === 'UP' ? '↗' : direction === 'DOWN' ? '↘' : '↔');
  await page.locator('#market-card').scrollIntoViewIfNeeded();
  await expect(page.locator('#mc-rule')).toBeInViewport();
});


test('12-Step report displays the real settled-bet count', async ({page}) => {
  await page.route('**/api/12step/daily-report**', route=>route.fulfill({json:{report:{settled_bets:49,bet_wins:24,bet_losses:25,recent_events:[]},history:[]}}));
  await page.goto('/');
  await expect(page.locator('#d12-bets')).toHaveText('49');
});

test('setup checklist exposes engine waits and rejects expired target issues', async ({page}) => {
  await page.route('**/api/l1-capital',route=>route.fulfill({json:{ready:true,source_issue:'20260913000000360',pending:{issue:'20260913000000359',target:'BIG',stake:500},waiting_rule:{rule:'R05'},risk_status:'OBSERVE ONLY — DAILY TP REACHED',trades:[]}}));
  await page.goto('/');
  await expect(page.locator('#check-l1-status')).toHaveText('RULE WAIT');
  await expect(page.locator('#check-l1-list')).toContainText('R05');
  await expect(page.locator('#check-l1-list')).toContainText('No current target issue');
  await expect(page.locator('#check-l1-list')).toContainText('DAILY TP REACHED');
  await expect(page.locator('#mc-rule')).not.toContainText('signal armed');
  await expect(page.locator('#check-step-status')).toHaveText('WAITING');
});

test('armed checklist uses real trigger/source metadata and zero-based 12-Step levels', async ({page}) => {
  await page.route('**/api/state',async route=>{
    const response=await route.fetch(), data=await response.json();
    data.strat_pending={issue:data.next_issue,target:'SMALL',stake:750,tier:1,step:2,trigger_rsi:71.2,confirm_type:'SMALL',source_issue:data.history.at(-1).issue};
    await route.fulfill({json:data});
  });
  await page.goto('/');
  await expect(page.locator('#check-step-status')).toHaveText('ARMED');
  await expect(page.locator('#check-step-list')).toContainText('71.2');
  await expect(page.locator('#check-step-list')).toContainText('T2 / S3');
  await expect(page.locator('#check-step-list')).toContainText('SMALL at source issue');
  await page.locator('.tf-btn[data-g="15"]').click();
  await expect(page.locator('#check-step-list')).toContainText('71.2');
});

test('timeframe comparison matches chart math and marks partial and complete buckets', async ({page}) => {
  let truncate=true;
  await page.route('**/api/history**',async route=>{
    const response=await route.fetch(),data=await response.json();
    if(truncate)data.history=data.history.slice(0,-2);
    await route.fulfill({json:data});
  });
  await page.route('**/api/state',async route=>{
    const response=await route.fetch(),data=await response.json();
    if(truncate)data.history=data.history.slice(0,-2);
    await route.fulfill({json:data});
  });
  await page.route('**/api/latest',route=>route.fulfill({json:{round:null}}));
  await page.goto('/');
  await expect(page.locator('#mc-timeframes tr')).toHaveCount(3);
  await expect(page.locator('#mc-timeframes tr[data-timeframe="5"]')).toContainText('FORMING');
  await expect(page.locator('#mc-timeframes tr[data-timeframe="15"]')).toContainText('FORMING');
  for(const tf of [1,5,15]) {
    await page.locator(`.tf-btn[data-g="${tf}"]`).click();
    await expect.poll(async()=>Number(await page.locator(`#mc-timeframes tr[data-timeframe="${tf}"] [data-rsi]`).textContent())).toBeCloseTo(await page.evaluate(()=>window.TRXChart.getContext().rsi),1);
  }
  truncate=false;
  await page.reload();
  await expect(page.locator('#mc-timeframes tr[data-timeframe="5"]')).toContainText('COMPLETE');
  await expect(page.locator('#mc-timeframes tr[data-timeframe="15"]')).toContainText('COMPLETE');
  await page.locator('#market-card').scrollIntoViewIfNeeded();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
});

test('history expands real details, paginates and filters by viewer local date', async ({page},testInfo) => {
  await page.route('**/api/l1-capital',route=>route.fulfill({json:{ready:true,pending:null,trades:Array.from({length:25},(_,i)=>({issue:String(20261003000010000n+BigInt(i)),time:i===0?'2026-10-02T23:50:00Z':'2026-10-03T12:00:00Z',target:'BIG',actual:'BIG',tier:1,step:1,stake:500,won:true,pnl:480}))}}));
  await page.route('**/api/12step/daily-report**',route=>route.fulfill({json:{report:{recent_events:[]},history:[]}}));
  await page.goto('/');
  await page.locator('#history-tab').click();
  await expect(page.locator('#signal-history-body .history-result')).toHaveCount(20);
  await page.locator('#history-more').click();
  await expect(page.locator('#signal-history-body .history-result')).toHaveCount(25);
  await expect(page.locator('#history-more')).toBeHidden();
  await page.locator('.history-detail-button').first().click();
  await expect(page.locator('.history-detail-row')).toContainText('T1 / S1');
  await expect(page.locator('.history-detail-row')).toContainText('Not recorded');
  await expect(page.locator('.history-detail-row')).toContainText('Actual result');
  const date=await page.evaluate(()=>{const d=new Date('2026-10-02T23:50:00Z');return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;});
  await page.locator('#history-date').fill(date);
  const expected=await page.evaluate(()=>new Date('2026-10-02T23:50:00Z').getDate()===new Date('2026-10-03T12:00:00Z').getDate()?25:1);
  await expect(page.locator('#signal-history-body .history-result')).toHaveCount(Math.min(20,expected));
  await expect(page.locator('.history-detail-row')).toHaveCount(0);
  await page.locator('#history-date-clear').click();
  await expect(page.locator('#history-count')).toContainText('of 25');
  await page.locator('.history-detail-button').first().click();
  await page.locator('#market-card').scrollIntoViewIfNeeded();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBeTruthy();
  await testInfo.attach('history-upgrade-'+testInfo.project.name,{body:await page.screenshot(),contentType:'image/png'});
});

test('data quality reports real coverage gaps and unknown timestamps', async ({page},testInfo) => {
  await page.route('**/api/history**',async route=>{
    const response=await route.fetch(),data=await response.json();
    data.history.splice(10,2);data.history[30][2]='';
    await route.fulfill({json:data});
  });
  await page.goto('/');
  await page.locator('#market-quality summary').click();
  await expect(page.locator('#mc-quality-coverage')).toContainText('358 rounds');
  await expect(page.locator('#mc-quality-gaps')).toContainText('2 estimated missing minutes');
  await expect(page.locator('#mc-quality-gaps')).toContainText('1 unknown timestamps');
  await expect(page.locator('#mc-quality-status')).toHaveText('CHECK GAPS');
  await page.locator('#market-card').scrollIntoViewIfNeeded();
  await testInfo.attach('context-upgrade-'+testInfo.project.name,{body:await page.screenshot({fullPage:true}),contentType:'image/png'});
});

test('stale context hides timeframe values and both checklists', async ({page}) => {
  await page.route('**/api/state',async route=>{
    const response=await route.fetch(),data=await response.json();data.feed_health.status='STALE';await route.fulfill({json:data});
  });
  await page.goto('/');
  await expect(page.locator('#check-l1-status')).toHaveText('UNAVAILABLE');
  await expect(page.locator('#check-step-status')).toHaveText('UNAVAILABLE');
  await expect(page.locator('#mc-timeframes')).not.toContainText('RISING');
  await expect(page.locator('#mc-timeframes')).toContainText('UNAVAILABLE');
  await expect(page.locator('#mc-quality-status')).toHaveText('UNAVAILABLE');
});

test('latest-round fast path expires targets before state reconciliation', async ({page}) => {
  await page.route('**/api/state',async route=>{
    const response=await route.fetch(),data=await response.json();
    data.strat_pending={issue:data.next_issue,target:'BIG',stake:500,tier:0,step:0,trigger_rsi:31};
    await route.fulfill({json:data});
  });
  await page.route('**/api/latest',route=>route.fulfill({json:{round:{issue:'20260913000000361',number:8,block_time:'2026-09-13 14:00:00'}}}));
  await page.goto('/');
  await expect.poll(()=>page.evaluate(()=>window.TRXChart.getComparisons().latestIssue)).toBe('20260913000000361');
  await expect(page.locator('#check-step-status')).toHaveText('WAITING');
  await expect(page.locator('#check-step-list')).toContainText('No current target issue');
});
