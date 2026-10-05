const {test,expect}=require('@playwright/test');
test('admin access, settings, reports and maintenance work together',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/admin');
  await expect(page.getByRole('heading',{name:'Admin sign in'})).toBeVisible();
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Admin dashboard'})).toBeVisible();
  await expect(page.locator('#notice')).toContainText('Connected.');
  const csrf=await page.locator('meta[name="csrf-token"]').getAttribute('content');
  const original=(await (await page.request.get('/api/admin/settings')).json()).settings;
  try{
    await page.locator('#timeframe').selectOption('5');
    await page.locator('#range').selectOption('10');
    await page.locator('#indicator-hss').check();
    await page.getByRole('button',{name:'Save chart & alert settings'}).click();
    await expect(page.locator('#notice')).toContainText('Settings saved.');
    await page.getByRole('button',{name:'Reload settings'}).click();
    await expect(page.locator('#timeframe')).toHaveValue('5');
    await expect(page.locator('#range')).toHaveValue('10');
    await expect(page.locator('#indicator-hss')).toBeChecked();
    await expect(page.locator('#l1-summary')).toContainText('Bets');
    await expect(page.locator('#step-summary')).toContainText('66.7');
    await page.getByRole('button',{name:'Refresh caches',exact:true}).click();
    await expect(page.locator('#job-status')).toContainText('cache refresh');
    const saved=await (await page.request.get('/api/admin/settings')).json();
    const backup=await (await page.request.get('/api/admin/backup')).json();
    expect(backup.settings.timeframe).toBe(5);
    await page.goto('/');
    await expect(page.locator('.tf-btn.active[data-g]')).toHaveAttribute('data-g','5');
    await expect(page.locator('#history-range-select')).toHaveValue('10');
    await expect(page.locator('#hss-toggle')).toBeChecked();
    await page.request.put('/api/admin/settings',{headers:{'X-CSRF-Token':csrf},data:{revision:saved.revision,settings:original}});
  }finally{
    const current=await (await page.request.get('/api/admin/settings')).json();
    await page.request.put('/api/admin/settings',{headers:{'X-CSRF-Token':csrf},data:{revision:current.revision,settings:original}});
  }
  await page.goto('/admin');
  await page.getByRole('button',{name:'Sign out',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Admin sign in'})).toBeVisible();
  expect(errors).toEqual([]);
});
