const {test,expect}=require('@playwright/test');

test('connected real orders are available without a checkbox; confirmation, demo and uncertain outcomes remain distinct',async({page})=>{
  let posts=0;
  await page.route('**/api/admin/trxchart-account',route=>route.fulfill({json:{revision:1,active:true,status:'connected',worker_alive:true,balance:'12500.50',balance_current:true,balance_at:'2026-10-11T08:00:00Z'}}));
  await page.route('**/api/admin/trxchart-order',async route=>{
    if(route.request().method()==='POST'){
      posts++;
      const body=route.request().postDataJSON();
      expect(body).toMatchObject({direction:'BIG',amount:1600,mode:'real',confirm:true});
      expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
      expect(route.request().headers()['x-csrf-token']).toBeTruthy();
      await route.fulfill({json:{ok:false,outcome:'unknown',message:'Order outcome is unknown. Check REAL history before another order.'}});
    }else await route.fulfill({json:{enabled:true,mode:'real',unrestricted:true,settings_revision:0,max_amount:0,daily_max_count:0,daily_max_total:0,today_count:posts,today_total:posts*1600,retry_after_sec:0}});
  });
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  if(await page.locator('#menu-toggle').isVisible())await page.locator('#menu-toggle').click();
  await page.getByRole('link',{name:'↗ Trade',exact:true}).click();
  await expect(page.locator('#order-status')).toContainText('Real orders enabled');
  await expect(page.locator('#trade-balance')).toContainText('12,500.50');
  await expect(page.locator('#order-big')).toBeEnabled();
  await page.locator('#order-amount').fill('1600');
  await expect(page.locator('#order-big')).toBeEnabled();
  page.once('dialog',dialog=>dialog.dismiss());
  await page.locator('#order-big').click();
  await expect(page.locator('#notice')).toContainText('Order cancelled');
  expect(posts).toBe(0);
  page.once('dialog',dialog=>{expect(dialog.message()).toContain('REAL');return dialog.accept();});
  await page.locator('#order-big').click();
  await expect(page.locator('#order-result')).toContainText('outcome is unknown');
  await expect(page.locator('#order-big')).toBeEnabled();
  expect(posts).toBe(1);
  await page.locator('#trade').getByRole('link',{name:'View results ↗'}).click();
  await expect(page.locator('#order-big')).toBeHidden();
  await page.locator('#journal-mode').selectOption('demo');
  await page.locator('#journal').getByRole('link',{name:'Go to Trade ↗'}).click();
  await expect(page.locator('#order-big')).toBeEnabled();
  await expect(page.locator('#order-small')).toBeEnabled();
  expect(posts).toBe(1);
});

test('disconnected account keeps orders unavailable despite enabled default',async({page})=>{
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  if(await page.locator('#menu-toggle').isVisible())await page.locator('#menu-toggle').click();
  await page.getByRole('link',{name:'↗ Trade',exact:true}).click();
  await expect(page.locator('#order-status')).toContainText('Connect TRXChart');
  await expect(page.locator('#order-big')).toBeDisabled();
});


test('owner can enable orders and remove old server caps without sending a bet',async({page})=>{
  let enabled=false, changes=0;
  await page.route('**/api/admin/trxchart-account',route=>route.fulfill({json:{revision:1,active:true,status:'connected',worker_alive:true}}));
  const status=()=>({enabled,unrestricted:enabled,settings_revision:changes,mode:'real',max_amount:enabled?0:100,daily_max_count:enabled?0:30,daily_max_total:enabled?0:3000,today_count:0,today_total:0,retry_after_sec:0});
  await page.route('**/api/admin/trxchart-order',route=>{expect(route.request().method()).toBe('GET');return route.fulfill({json:status()});});
  await page.route('**/api/admin/trxchart-order/settings',route=>{
    const body=route.request().postDataJSON();
    expect(route.request().method()).toBe('PUT');
    expect(body).toEqual({revision:changes,enabled:true,unrestricted:true});
    expect(route.request().headers()['x-csrf-token']).toBeTruthy();
    enabled=true;changes++;return route.fulfill({json:status()});
  });
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  if(await page.locator('#menu-toggle').isVisible())await page.locator('#menu-toggle').click();
  await page.getByRole('link',{name:'↗ Trade',exact:true}).click();
  await expect(page.locator('#order-big')).toBeDisabled();
  await expect(page.locator('#trade-balance')).toContainText('—');
  await page.getByText('Order permissions & status',{exact:true}).click();
  await page.locator('#order-enable-all').click();
  await expect(page.locator('#order-status')).toContainText('No local amount, count, daily total or spacing limits');
  await page.locator('#order-amount').fill('1600');
  await expect(page.locator('#order-big')).toBeEnabled();
  await expect(page.locator('#order-small')).toBeEnabled();
  expect(changes).toBe(1);
});
