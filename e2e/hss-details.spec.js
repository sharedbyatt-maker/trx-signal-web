const {test,expect}=require('@playwright/test');

test('H/SS evidence is selectable and scoped to closed 5m signals',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  // Deterministic 1m source data, grouped by the production chart code.
  let seed=73;
  const rows=Array.from({length:1500},(_,i)=>{
    seed=(Math.imul(seed,1664525)+1013904223)>>>0;
    const number=seed/4294967296>.5?8:2;
    return [String(20260913103010001n+BigInt(i)),number,new Date(Date.UTC(2026,8,13,0,i)).toISOString().slice(0,19).replace('T',' ')];
  });
  await page.route('**/api/history**',r=>r.fulfill({json:{history:rows,meta:{days:30},incremental:false}}));
  await page.route('**/api/latest',r=>r.fulfill({json:{round:{issue:rows.at(-1)[0],number:rows.at(-1)[1],block_time:rows.at(-1)[2]}}}));
  await page.goto('/');
  await expect(page.locator('#lg-ohlc')).not.toHaveText('');
  await page.locator('.tf-btn[data-g="5"]').click();
  await page.locator('#ind-toggle-btn').click();
  await page.locator('#hss-toggle').check();
  await expect(page.locator('#hss-details')).toBeVisible();
  await expect.poll(()=>page.locator('#hss-signal-select option').count()).toBeGreaterThan(1);
  const ids=await page.locator('#hss-signal-select option').evaluateAll(opts=>opts.map(o=>o.value));
  for(const id of [ids[0],ids.at(-1)]){
    await page.locator('#hss-signal-select').selectOption(id);
    await expect(page.locator('#hss-evidence')).toContainText('Closed 5m candle:');
    await expect(page.locator('#hss-evidence')).toContainText('wick / body');
    await expect(page.locator('#hss-evidence')).toContainText('earlier candles only');
    await expect(page.locator('#hss-evidence')).toContainText('Confirmed when the next bucket appeared:');
  }
  await page.locator('.tf-btn[data-g="1"]').click();
  await expect(page.locator('#hss-evidence')).toHaveText('Switch to 5m to inspect H / SS signals.');
  await page.locator('#hss-toggle').uncheck();
  await expect(page.locator('#hss-details')).toBeHidden();
  expect(errors).toEqual([]);
});
