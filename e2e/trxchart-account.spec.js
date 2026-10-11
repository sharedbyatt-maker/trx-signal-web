const {test,expect}=require('@playwright/test');

test('server connection requires consent, clears credentials and allows stopping without deleting history',async({page})=>{
  let connected=false,posts=0,stops=0;
  await page.route('**/api/admin/trxchart-account',async route=>{
    const method=route.request().method();
    if(method==='POST'){
      const body=route.request().postDataJSON();
      expect(body).toMatchObject({consent:true,phone:'fixture@example.invalid',password:'fixture-password',twofa:''});
      expect(route.request().headers()['x-csrf-token']).toBeTruthy();
      connected=true;posts++;
    }
    if(method==='DELETE'){connected=false;stops++;}
    await route.fulfill({json:{revision:connected?1:0,active:connected,status:connected?'connected':'disconnected',last_sync:connected?new Date().toISOString():null,worker_alive:true,interval_seconds:60}});
  });
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  if(await page.locator('#menu-toggle').isVisible())await page.locator('#menu-toggle').click();
  await page.getByRole('link',{name:'◉ Trade Results',exact:true}).click();
  await expect(page.locator('#journal-account-state')).toContainText('Not connected');
  await page.getByLabel('TRXChart Phone / Email',{exact:true}).fill('fixture@example.invalid');
  await page.getByLabel('TRXChart Password',{exact:true}).fill('fixture-password');
  await page.getByRole('button',{name:'Connect TRXChart · တစ်ကြိမ်ချိတ်ဆက်ရန်',exact:true}).click();
  expect(posts).toBe(0);
  await expect(page.locator('#journal-connect-form')).toBeVisible();
  await page.locator('#journal-account-consent').check();
  await page.getByRole('button',{name:'Connect TRXChart · တစ်ကြိမ်ချိတ်ဆက်ရန်',exact:true}).click();
  await expect(page.locator('#journal-account-state')).toContainText('Connected');
  await expect(page.locator('#journal-connect-form')).toBeHidden();
  await expect(page.locator('#journal-account-password')).toHaveValue('');
  await expect(page.locator('#journal-account-twofa')).toHaveValue('');
  await expect(page.getByRole('button',{name:'Sync now',exact:true})).toBeEnabled();
  await expect(page.getByRole('button',{name:'Disconnect',exact:true})).toBeEnabled();
  await expect(page.locator('#toast-region')).not.toContainText('fixture-password');
  await page.getByRole('button',{name:'Disconnect',exact:true}).click();
  await expect(page.locator('#journal-account-state')).toContainText('Not connected');
  await expect(page.locator('#journal-connect-form')).toBeVisible();
  await expect(page.getByRole('button',{name:'Sync now',exact:true})).toBeDisabled();
  expect(posts).toBe(1);expect(stops).toBe(1);
});
