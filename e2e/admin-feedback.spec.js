const {test,expect}=require('@playwright/test');

async function openAdmin(page,section='chart'){
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await page.goto('/admin#'+section);
  await expect(page.locator('#notice')).toContainText('Connected.');
  await page.locator('.toast-close').click();
  await page.mouse.move(0,0);
}

test('draft, pending, failed and successful saves give visible feedback without exposing form values',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await openAdmin(page);
  await page.locator('#timeframe').selectOption('5');
  await expect(page.locator('.toast-info')).toContainText('Unsaved changes');
  await expect(page.locator('#draft-summary')).toContainText('Chart');
  await page.route('**/api/admin/settings',route=>route.request().method()==='PUT'
    ?route.fulfill({status:409,contentType:'application/json',body:JSON.stringify({error:'Settings changed elsewhere. Reload and try again.'})})
    :route.continue());
  await page.getByRole('button',{name:'Save chart & alert settings',exact:true}).click();
  await expect(page.locator('.toast-error')).toContainText('Settings changed elsewhere');
  await expect(page.locator('#timeframe')).toHaveValue('5');
  await page.unroute('**/api/admin/settings');
  let release;
  const gate=new Promise(resolve=>release=resolve);
  await page.route('**/api/admin/settings',async route=>{
    if(route.request().method()!=='PUT')return route.continue();
    await gate;const body=route.request().postDataJSON();
    await route.fulfill({contentType:'application/json',body:JSON.stringify({revision:body.revision+1,settings:body.settings})});
  });
  try{
    await page.getByRole('button',{name:'Save chart & alert settings',exact:true}).click();
    await expect(page.locator('#admin-work-state')).toBeVisible();
    await expect(page.locator('#timeframe')).toBeDisabled();
    // Existing notification controls remain usable while an operation waits.
    await page.locator('.toast-error .toast-close').click();
    await expect(page.locator('.toast-error')).toHaveCount(0);
    release();
    await expect(page.locator('.toast-success')).toContainText('Settings saved.');
    await expect(page.locator('#admin-work-state')).toBeHidden();
    await expect(page.locator('#timeframe')).toBeEnabled();
    await expect(page.locator('#draft-summary')).toHaveText('');
    expect(errors).toEqual([]);
  }finally{release();}
});

test('a successful save followed by a refresh failure is reported as accepted rather than rejected',async({page})=>{
  await openAdmin(page);
  await page.locator('#range').selectOption('10');
  await page.route('**/api/admin/settings',route=>{
    if(route.request().method()!=='PUT')return route.continue();
    const body=route.request().postDataJSON();
    return route.fulfill({contentType:'application/json',body:JSON.stringify({revision:body.revision+1,settings:body.settings})});
  });
  await page.route('**/api/admin/events?**',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"Audit refresh unavailable."}'}));
  await page.getByRole('button',{name:'Save chart & alert settings',exact:true}).click();
  await expect(page.locator('.toast-warning')).toContainText('Change accepted');
  await expect(page.locator('.toast-warning')).toContainText('Audit refresh unavailable');
  await expect(page.locator('.toast-error')).toHaveCount(0);
  await expect(page.locator('#range')).toHaveValue('10');
  await expect(page.locator('#draft-summary')).toHaveText('');
});

test('notifications stay bounded and admin sections fit the viewport with an accessible mobile menu',async({page},testInfo)=>{
  await page.emulateMedia({reducedMotion:'reduce'});
  await openAdmin(page);
  for(let i=0;i<5;i++){
    await page.locator('#reload-settings').click();
    await expect(page.locator('#admin-work-state')).toBeHidden();
  }
  expect(await page.locator('.toast').count()).toBeLessThanOrEqual(3);
  await page.locator('.toast-close').first().click();
  expect(await page.locator('.toast').count()).toBeLessThanOrEqual(2);
  for(const name of ['system','chart','l1','twelve','notifications','reports','connection','security','maintenance','audit']){
    const menu=page.locator('#menu-toggle');
    if(await menu.isVisible())await menu.click();
    await page.locator(`nav [data-page="${name}"]`).click();
    await expect(page.locator('#'+name)).toBeVisible();
    await expect(page.locator(`nav [data-page="${name}"]`)).toHaveAttribute('aria-current','page');
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await expect(page.locator('#menu-backdrop')).toBeHidden();
  }
  if(await page.locator('#menu-toggle').isVisible()){
    await page.locator('#menu-toggle').click();
    await expect(page.locator('#menu-backdrop')).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(page.locator('#menu-backdrop')).toBeHidden();
    await expect(page.locator('#menu-toggle')).toBeFocused();
  }
  await page.goto('/admin#system');
  await expect(page.locator('#system')).toBeVisible();
  await page.screenshot({path:testInfo.outputPath('admin-refreshed-ui.png'),fullPage:true});
});

test('background polls do not flood notifications and completed maintenance reports once',async({page})=>{
  await page.clock.install();
  await openAdmin(page,'system');
  const original=await (await page.request.get('/api/admin/status')).json();
  await page.route('**/api/admin/status',route=>route.fulfill({status:503,contentType:'application/json',body:'{"error":"Status temporarily unavailable."}'}));
  await page.clock.fastForward(10000);
  await expect(page.locator('#notice')).toContainText('Status temporarily unavailable');
  await expect(page.locator('.toast')).toHaveCount(0);
  await page.clock.fastForward(10000);
  await expect(page.locator('.toast')).toHaveCount(0);
  await page.unroute('**/api/admin/status');
  await page.route('**/api/admin/status',route=>route.fulfill({contentType:'application/json',body:JSON.stringify({...original,maintenance:{action:'cache_refresh',status:'complete',updated:'2026-10-07T12:00:00Z',error:null}})}));
  await page.clock.fastForward(10000);
  await expect(page.locator('.toast-success')).toContainText('cache refresh completed');
  await page.clock.fastForward(10000);
  await expect(page.locator('.toast')).toHaveCount(0);
});


test('accepted policy saves keep the latest revision even when the audit refresh fails',async({page})=>{
  await openAdmin(page,'notifications');
  let revision=40,saved=null,writes=0;
  const initial=await (await page.request.get('/api/admin/telegram')).json();
  await page.route('**/api/admin/telegram',route=>{
    if(route.request().method()==='GET')return route.fulfill({status:503,json:{error:'Policy refresh unavailable.'}});
    const body=route.request().postDataJSON();
    const expected=writes===0?initial.revision:revision;
    if(body.revision!==expected)return route.fulfill({status:409,json:{error:'Stale policy revision.'}});
    writes++;revision++;saved=body.settings;
    return route.fulfill({json:{...initial,revision,settings:saved}});
  });
  await page.route('**/api/admin/events?**',route=>route.fulfill({status:503,json:{error:'Audit refresh unavailable.'}}));
  const control=page.locator('#quiet-enabled');
  await control.setChecked(!(await control.isChecked()));
  await page.locator('#save-policy').click();
  await expect(page.locator('.toast-warning')).toContainText('Change accepted');
  await expect(page.locator('#draft-summary')).toHaveText('');
  await control.setChecked(!(await control.isChecked()));
  await page.locator('#save-policy').click();
  await expect.poll(()=>writes).toBe(2);
  await expect(page.locator('#admin-work-state')).toBeHidden();
  await expect(page.locator('.toast-error')).toHaveCount(0);
  expect(saved.quiet.enabled).toBe(await control.isChecked());
});

test('Refresh data retries failed startup sections without replacing another section draft',async({page})=>{
  await openAdmin(page,'chart');
  let fail=true;
  await page.route('**/api/admin/feed',route=>fail?route.fulfill({status:503,json:{error:'Startup API settings unavailable.'}}):route.continue());
  await page.reload();
  await expect(page.locator('#notice')).toContainText('Startup API settings unavailable.');
  await expect(page.locator('#default-feed')).toBeDisabled();
  const draft=await page.locator('#timeframe').inputValue()==='5'?'15':'5';
  await page.locator('#timeframe').selectOption(draft);
  await expect(page.locator('#draft-summary')).toContainText('Chart');
  fail=false;
  await page.locator('#refresh-all').click();
  await expect(page.locator('#notice')).toContainText('Status and reports refreshed.');
  await expect(page.locator('#default-feed')).toBeEnabled();
  await expect(page.locator('#timeframe')).toHaveValue(draft);
  await expect(page.locator('#draft-summary')).toContainText('Chart');
});
