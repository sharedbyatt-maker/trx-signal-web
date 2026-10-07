const {test,expect}=require('@playwright/test');

test('streak controls preview, save and reload without changing strategy controls',async({page},testInfo)=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await page.goto('/admin#notifications');
  await expect(page.locator('#notice')).toContainText('Connected.');
  const original=await (await page.request.get('/api/admin/telegram')).json();
  const l1=await (await page.request.get('/api/admin/strategies/l1')).json();
  const twelve=await (await page.request.get('/api/admin/strategies/twelve')).json();
  const csrf=await page.locator('meta[name="csrf-token"]').getAttribute('content');
  try{
    await expect(page.locator('#streak-start')).toHaveValue('8');
    await expect(page.locator('#streak-interval-label')).toBeHidden();
    await page.locator('#streak-start').fill('6');
    await page.locator('#streak-repeat').selectOption('interval');
    await expect(page.locator('#streak-interval-label')).toBeVisible();
    await page.locator('#streak-interval').fill('2');
    await page.locator('#streak-side').selectOption('SMALL');
    await page.locator('#policy-types-streak').check();
    await expect(page.locator('#streak-summary')).toContainText('6, 8, 10, 12');
    await expect(page.locator('#draft-summary')).toContainText('Delivery policy');
    await page.locator('#preview-streak').click();
    await expect(page.locator('#streak-preview')).toContainText('SMALL (S) × 6');
    await expect(page.locator('#notice')).toContainText('No message sent');
    expect((await (await page.request.get('/api/admin/telegram')).json()).revision).toBe(original.revision);
    await page.locator('#save-policy').click();
    await expect(page.locator('#notice')).toContainText('Telegram delivery policy saved');
    await page.reload();
    await expect(page.locator('#notice')).toContainText('Connected.');
    await expect(page.locator('#streak-start')).toHaveValue('6');
    await expect(page.locator('#streak-repeat')).toHaveValue('interval');
    await expect(page.locator('#streak-side')).toHaveValue('SMALL');
    await page.locator('#streak-repeat').selectOption('once');
    await expect(page.locator('#streak-summary')).toContainText('Alert at 6 consecutive');
    await expect(page.locator('#streak-interval-label')).toBeHidden();
    await page.locator('#policy-types-streak').uncheck();
    await expect(page.locator('#streak-summary')).toHaveText('Streak alerts disabled');
    await page.locator('#reload-policy').click();
    await expect(page.locator('#policy-types-streak')).toBeChecked();
    expect((await (await page.request.get('/api/admin/strategies/l1')).json()).settings).toEqual(l1.settings);
    expect((await (await page.request.get('/api/admin/strategies/twelve')).json()).settings).toEqual(twelve.settings);
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.locator('#streak-controls').screenshot({path:testInfo.outputPath('streak-alert-controls.png')});
    expect(errors).toEqual([]);
  }finally{
    const current=await (await page.request.get('/api/admin/telegram')).json();
    await page.request.put('/api/admin/telegram',{headers:{'X-CSRF-Token':csrf},data:{revision:current.revision,settings:original.settings}});
  }
});
