const {test,expect}=require('@playwright/test');

async function openAdmin(page,section='system'){
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await page.goto('/admin#'+section);
  await expect(page.locator('#notice')).toContainText('Connected.');
}

test('partial refresh identifies the failed component and waits for every request before polling again',async({page})=>{
  await page.clock.install();
  await openAdmin(page);
  const apiBadge=await page.locator('#api-runtime-badge').textContent();
  const original=await (await page.request.get('/api/admin/status')).json();
  let calls=0,release;
  const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/admin/status',async route=>{calls++;await gate;await route.fulfill({json:original});});
  await page.route('**/api/admin/events?**',route=>route.fulfill({status:503,json:{error:'Audit temporarily unavailable.'}}));
  try{
    await page.clock.fastForward(10000);
    await expect.poll(()=>calls).toBe(1);
    await page.clock.fastForward(10000);
    expect(calls).toBe(1);
    release();
    await expect(page.locator('#sync-state')).toHaveText('Partial refresh');
    await expect(page.locator('#notice')).toContainText('Audit / delivery: Audit temporarily unavailable.');
    await expect(page.locator('#api-runtime-badge')).toHaveText(apiBadge);
    await expect(page.locator('#health-badge')).not.toHaveText('Refresh failed');
    await page.unroute('**/api/admin/status');
    await page.unroute('**/api/admin/events?**');
    await page.route('**/api/admin/status',route=>route.fulfill({status:502,contentType:'text/html',body:'<html>private upstream error details</html>'}));
    await page.evaluate(()=>window.dispatchEvent(new Event('online')));
    await expect(page.locator('#health-badge')).toHaveText('Refresh failed');
    await expect(page.locator('#notice')).toContainText('Request failed (502)');
    await expect(page.locator('#notice')).not.toContainText('private upstream');
    await expect(page.locator('#api-runtime-badge')).toHaveText(apiBadge);
    await page.unroute('**/api/admin/status');
    await page.evaluate(()=>window.dispatchEvent(new Event('offline')));
    await expect(page.locator('#sync-state')).toHaveText('Offline');
    await page.evaluate(()=>window.dispatchEvent(new Event('online')));
    await expect(page.locator('#sync-state')).toHaveText('Up to date');
    await expect(page.locator('#sync-time')).toContainText('Last complete refresh:');
  }finally{release();}
});

test('restore requires every settings revision and retry keeps other unsaved drafts',async({page})=>{
  await openAdmin(page,'chart');
  let fail=true;
  await page.route('**/api/admin/telegram/messages',route=>fail?route.fulfill({status:503,json:{error:'Message settings unavailable.'}}):route.continue());
  await page.reload();
  await expect(page.locator('#notice')).toContainText('Message settings unavailable.');
  await expect(page.locator('#restore-backup')).toBeDisabled();
  const draft=await page.locator('#timeframe').inputValue()==='5'?'15':'5';
  await page.locator('#timeframe').selectOption(draft);
  fail=false;
  await page.locator('#refresh-all').click();
  await expect(page.locator('#notice')).toContainText('Status and reports refreshed.');
  await expect(page.locator('#restore-backup')).toBeEnabled();
  await expect(page.locator('#timeframe')).toHaveValue(draft);
  await expect(page.locator('#draft-summary')).toContainText('Chart');
});

test('maintenance controls remain locked during requests and a running job',async({page},testInfo)=>{
  await openAdmin(page,'maintenance');
  const original=await (await page.request.get('/api/admin/status')).json();
  let release;
  const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/admin/maintenance',async route=>{await gate;await route.fulfill({json:{ok:true}});});
  await page.route('**/api/admin/status',route=>route.fulfill({json:{...original,maintenance:{action:'cache_refresh',status:'running',updated:'2026-10-10T14:00:00Z',error:null}}}));
  try{
    await page.locator('[data-action="cache_refresh"]').click();
    await expect(page.locator('#admin-work-state')).toBeVisible();
    await expect(page.locator('[data-action="history_refresh"]')).toBeDisabled();
    await expect(page.locator('[data-action="cache_refresh"]')).toBeDisabled();
    release();
    await expect(page.locator('#admin-work-state')).toBeHidden();
    await expect(page.locator('#job-status')).toContainText('running');
    await expect(page.locator('[data-action="history_refresh"]')).toBeDisabled();
    await page.unroute('**/api/admin/status');
    await page.locator('#refresh-all').click();
    await expect(page.locator('#notice')).toContainText('Status and reports refreshed.');
    await expect(page.locator('[data-action="history_refresh"]')).toBeEnabled();
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:testInfo.outputPath('admin-reliability.png'),fullPage:true});
  }finally{release();}
});
