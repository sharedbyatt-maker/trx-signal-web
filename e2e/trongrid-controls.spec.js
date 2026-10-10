const {test,expect}=require('@playwright/test');

test('TronGrid key controls verify, save, retain drafts on errors and hide credentials',async({page},testInfo)=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  let state={revision:0,settings:{mode:'disabled',key_set:false,endpoint:'https://api.trongrid.io/wallet/getblock'},active_source:'primary'};
  let savedKey='',fail=false;
  await page.route('**/api/admin/trongrid',async route=>{
    const method=route.request().method();
    if(method==='PUT'){
      const body=route.request().postDataJSON();
      if(fail)return route.fulfill({status:400,json:{error:'TronGrid results do not match recent live rounds.'}});
      savedKey=body.key||savedKey;
      state={...state,revision:state.revision+1,settings:{...state.settings,mode:body.mode,key_set:!!savedKey}};
    }
    if(method==='DELETE'){savedKey='';state={...state,revision:state.revision+1,settings:{...state.settings,mode:'disabled',key_set:false}};}
    return route.fulfill({status:200,json:state});
  });
  await page.route('**/api/admin/trongrid/check',route=>route.fulfill({status:200,json:{ok:true,rows:4,matched_rounds:4,latest_issue:'20261010103010756'}}));
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await page.goto('/admin#connection');
  await expect(page.locator('#notice')).toContainText('Connected.');
  await expect(page.locator('#trongrid-url')).toHaveValue('https://api.trongrid.io/wallet/getblock');
  await expect(page.locator('#trongrid-url')).toHaveAttribute('readonly','');
  await page.locator('#trongrid-mode').selectOption('backup');
  await page.locator('#trongrid-key').fill('fixture-private-trongrid-key');
  await expect(page.locator('#draft-summary')).toContainText('TronGrid');
  await page.locator('#check-trongrid').click();
  await expect(page.locator('#trongrid-state')).toContainText('4 matching rounds');
  expect(state.revision).toBe(0);
  await page.locator('#save-trongrid').click();
  await expect(page.locator('#notice')).toContainText('TronGrid settings saved');
  await expect(page.locator('#trongrid-key')).toHaveValue('');
  await expect(page.locator('#trongrid-state')).toContainText('Key stored (hidden)');
  expect(savedKey).toBe('fixture-private-trongrid-key');
  await page.reload();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await expect(page.locator('#trongrid-mode')).toHaveValue('backup');
  await expect(page.locator('#trongrid-key')).toHaveValue('');
  fail=true;
  await page.locator('#trongrid-mode').selectOption('live');
  await page.locator('#save-trongrid').click();
  await expect(page.locator('.toast-error')).toContainText('do not match');
  await expect(page.locator('#trongrid-mode')).toHaveValue('live');
  expect(state.settings.mode).toBe('backup');
  await page.locator('#reload-trongrid').click();
  await expect(page.locator('#trongrid-mode')).toHaveValue('backup');
  await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.locator('#trongrid-controls').screenshot({path:testInfo.outputPath('trongrid-controls.png')});
  await page.locator('#clear-trongrid').click();
  await expect(page.locator('#trongrid-state')).toContainText('No API key');
  expect(savedKey).toBe('');
  expect(errors).toEqual([]);
});
