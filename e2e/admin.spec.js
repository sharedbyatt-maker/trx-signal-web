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
    await page.goto('/admin#chart');
    await page.locator('#timeframe').selectOption('5');
    await page.locator('#range').selectOption('10');
    await page.locator('#indicator-hss').check();
    await page.getByRole('button',{name:'Save chart & alert settings'}).click();
    await expect(page.locator('#notice')).toContainText('Settings saved.');
    await page.getByRole('button',{name:'Reload settings'}).click();
    await expect(page.locator('#timeframe')).toHaveValue('5');
    await expect(page.locator('#range')).toHaveValue('10');
    await expect(page.locator('#indicator-hss')).toBeChecked();
    await page.goto('/admin#reports');
    await expect(page.locator('#l1-summary')).toContainText('Bets');
    await expect(page.locator('#step-summary')).toContainText('66.7');
    await page.goto('/admin#maintenance');
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

test('strategy money drafts, fixed rules and Telegram policy controls',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  const csrf=await page.locator('meta[name="csrf-token"]').getAttribute('content');
  const originals={};
  for(const name of ['l1','twelve']) originals[name]=(await (await page.request.get(`/api/admin/strategies/${name}`)).json()).settings;
  const policy=(await (await page.request.get('/api/admin/telegram')).json()).settings;
  try{
    await page.goto('/admin#l1');
    await expect(page.locator('#l1')).toBeVisible();
    await expect(page.locator('#l1-defaults')).toContainText('500 MMK');
    await expect(page.locator('#l1 .rule-list')).toContainText('R02');
    expect(await page.locator('#l1 .rule-list input').count()).toBe(0);
    await page.locator('#l1-base').fill('600');
    await expect(page.locator('#l1-preview')).toContainText('600 → 1,200');
    await page.getByRole('button',{name:'Save L1 CAPITAL settings'}).click();
    await expect(page.locator('#notice')).toContainText('Strategy money settings saved.');
    await page.locator('#l1-reset').click();
    await expect(page.locator('#l1-base')).toHaveValue('500');
    await expect(page.locator('#l1-draft')).toContainText('Unsaved');
    await page.locator('#l1-reload').click();
    await expect(page.locator('#l1-base')).toHaveValue('600');
    await page.goto('/admin#twelve');
    await expect(page.locator('#twelve-defaults')).toContainText('200 MMK');
    await page.locator('#twelve-base').fill('250');
    await page.getByRole('button',{name:'Save 12-STEP settings'}).click();
    await expect(page.locator('#notice')).toContainText('Strategy money settings saved.');
    await page.goto('/admin#notifications');
    await page.locator('#policy-engines-l1').uncheck();
    await page.locator('#policy-types-wait').uncheck();
    await page.locator('#quiet-enabled').check();
    await page.locator('#quiet-start').fill('23:00');
    await page.locator('#quiet-end').fill('06:00');
    await page.locator('#save-policy').click();
    await expect(page.locator('#notice')).toContainText('Telegram delivery policy saved.');
    await page.locator('#reload-policy').click();
    await expect(page.locator('#policy-engines-l1')).not.toBeChecked();
    await expect(page.locator('#quiet-start')).toHaveValue('23:00');
    await page.goto('/');
    await expect(page.locator('#l1-money-settings')).toContainText('Base 600');
    await expect(page.locator('#st-money-settings')).toContainText('Base 250');
    await page.goto('/admin#l1');
    await expect(page.locator('#l1-base')).toHaveValue('600');
    await expect.poll(()=>page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
    await page.screenshot({path:`test-results/admin-strategy-${test.info().project.name}.png`,fullPage:true});
  }finally{
    for(const name of ['l1','twelve']){const current=await (await page.request.get(`/api/admin/strategies/${name}`)).json();await page.request.put(`/api/admin/strategies/${name}`,{headers:{'X-CSRF-Token':csrf},data:{revision:current.revision,settings:originals[name]}});}
    const current=await (await page.request.get('/api/admin/telegram')).json();await page.request.put('/api/admin/telegram',{headers:{'X-CSRF-Token':csrf},data:{revision:current.revision,settings:policy}});
  }
  expect(errors).toEqual([]);
});

test('message studio preserves drafts and chart/master saves stay separate',async({page})=>{
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  const csrf=await page.locator('meta[name="csrf-token"]').getAttribute('content');
  const initial=(await (await page.request.get('/api/admin/settings')).json()).settings;
  const templates=(await (await page.request.get('/api/admin/telegram/messages')).json()).settings;
  try{
    await page.goto('/admin#chart');
    const draft=initial.timeframe===15?'5':'15';
    await page.locator('#timeframe').selectOption(draft);
    await page.goto('/admin#notifications');
    await page.locator('#alerts').setChecked(!initial.alerts);
    await page.getByRole('button',{name:'Save master switches',exact:true}).click();
    await expect(page.locator('#notice')).toContainText('Settings saved.');
    const saved=(await (await page.request.get('/api/admin/settings')).json()).settings;
    expect(saved.timeframe).toBe(initial.timeframe);
    await expect(page.locator('#draft-summary')).toContainText('Chart');
    await page.locator('#message-template').fill('မင်္ဂလာပါ {engine}\n{body}');
    await page.getByRole('button',{name:'Preview message',exact:true}).click();
    await expect(page.locator('#message-preview')).toContainText('မင်္ဂလာပါ L1 CAPITAL');
    await expect(page.locator('#message-preview')).toContainText('500 MMK');
    await page.locator('#message-category').selectOption('result');
    await expect(page.locator('#message-template')).toHaveValue('{original}');
    await page.locator('#message-category').selectOption('signal');
    await expect(page.locator('#message-template')).toHaveValue('မင်္ဂလာပါ {engine}\n{body}');
    await page.getByRole('button',{name:'Save message templates',exact:true}).click();
    await expect(page.locator('#message-state')).toContainText('Saved');
    await page.goto('/admin#chart');
    await expect(page.locator('#timeframe')).toHaveValue(draft);
    await page.getByRole('button',{name:'Save chart & alert settings',exact:true}).click();
    await expect(page.locator('#notice')).toContainText('Settings saved.');
    expect((await (await page.request.get('/api/admin/settings')).json()).settings.alerts).toBe(!initial.alerts);
    await page.goto('/admin#notifications');
    await page.locator('#message-template').fill('{secret}');
    await page.getByRole('button',{name:'Preview message',exact:true}).click();
    await expect(page.locator('#notice')).toContainText('Invalid placeholder');
    await page.getByRole('button',{name:'Reload saved templates',exact:true}).click();
    await expect(page.locator('#message-template')).toHaveValue('မင်္ဂလာပါ {engine}\n{body}');
    await page.screenshot({path:test.info().outputPath('admin-message-studio.png'),fullPage:true});
    expect(errors).toEqual([]);
  }finally{
    const current=(await (await page.request.get('/api/admin/settings')).json());
    await page.request.put('/api/admin/settings',{headers:{'X-CSRF-Token':csrf},data:{revision:current.revision,settings:initial}});
    const messages=(await (await page.request.get('/api/admin/telegram/messages')).json());
    await page.request.put('/api/admin/telegram/messages',{headers:{'X-CSRF-Token':csrf},data:{revision:messages.revision,settings:templates}});
  }
});
