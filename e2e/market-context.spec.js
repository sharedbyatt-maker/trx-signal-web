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
  await page.locator('#market-card').scrollIntoViewIfNeeded();
  await expect(page.locator('#mc-rule')).toBeInViewport();
});
