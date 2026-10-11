const {test,expect}=require('@playwright/test');

test('real orders require consent and confirmation; demo and uncertain outcomes remain distinct',async({page})=>{
  let posts=0;
  await page.route('**/api/admin/trxchart-account',route=>route.fulfill({json:{revision:1,active:true,status:'connected',worker_alive:true}}));
  await page.route('**/api/admin/trxchart-order',async route=>{
    if(route.request().method()==='POST'){
      posts++;
      const body=route.request().postDataJSON();
      expect(body).toMatchObject({direction:'BIG',amount:10,mode:'real',confirm:true});
      expect(body.request_id).toMatch(/^[0-9a-f-]{36}$/);
      expect(route.request().headers()['x-csrf-token']).toBeTruthy();
      await route.fulfill({json:{ok:false,outcome:'unknown',message:'Order outcome is unknown. Check REAL history before another order.'}});
    }else await route.fulfill({json:{enabled:true,mode:'real',max_amount:100,daily_max_count:30,daily_max_total:3000,today_count:posts,today_total:posts*10,retry_after_sec:0}});
  });
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  if(await page.locator('#menu-toggle').isVisible())await page.locator('#menu-toggle').click();
  await page.getByRole('link',{name:'◉ Trade Results',exact:true}).click();
  await expect(page.locator('#order-status')).toContainText('Real orders enabled');
  await expect(page.locator('#order-big')).toBeDisabled();
  await page.locator('#order-amount').fill('10');
  await page.locator('#order-real-consent').check();
  await expect(page.locator('#order-big')).toBeEnabled();
  page.once('dialog',dialog=>dialog.dismiss());
  await page.locator('#order-big').click();
  await expect(page.locator('#notice')).toContainText('Order cancelled');
  expect(posts).toBe(0);
  page.once('dialog',dialog=>{expect(dialog.message()).toContain('REAL');return dialog.accept();});
  await page.locator('#order-big').click();
  await expect(page.locator('#order-result')).toContainText('outcome is unknown');
  await expect(page.locator('#order-real-consent')).not.toBeChecked();
  await expect(page.locator('#order-big')).toBeDisabled();
  expect(posts).toBe(1);
  await page.locator('#journal-mode').selectOption('demo');
  await page.locator('#order-real-consent').check();
  await expect(page.locator('#order-status')).toContainText('Demo selected');
  await expect(page.locator('#order-big')).toBeDisabled();
  await expect(page.locator('#order-small')).toBeDisabled();
  expect(posts).toBe(1);
});

test('default server keeps real order buttons disabled',async({page})=>{
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  if(await page.locator('#menu-toggle').isVisible())await page.locator('#menu-toggle').click();
  await page.getByRole('link',{name:'◉ Trade Results',exact:true}).click();
  await expect(page.locator('#order-status')).toContainText('Real orders disabled');
  await page.locator('#order-real-consent').check();
  await expect(page.locator('#order-big')).toBeDisabled();
});
