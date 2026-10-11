const {test,expect}=require('@playwright/test');
const account=(extra={})=>({revision:1,active:true,status:'connected',worker_alive:true,last_sync:new Date().toISOString(),...extra});
const limits={enabled:true,unrestricted:true,max_amount:0,daily_max_count:0,daily_max_total:0,today_count:0,today_total:0,retry_after_sec:0};
async function signIn(page){
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await page.goto('/admin#trade');
  await expect(page.locator('#notice')).toContainText('Connected.');
}

test('WAIT appears before POST completes, stays one card, and settles while the action is busy',async({page},testInfo)=>{
  let orders=[],posts=0,checksDuringPost=0,held,finishPost;
  const release=new Promise(resolve=>finishPost=resolve);
  await page.route('**/api/admin/trxchart-account',r=>r.fulfill({json:account()}));
  await page.route('**/api/admin/trxchart-order',async route=>{
    if(route.request().method()==='GET')return route.fulfill({json:limits});
    posts++;const body=route.request().postDataJSON();
    orders=[{id:body.request_id,at:new Date().toISOString(),side:body.direction,stake:body.amount,outcome:'pending',state:-1,pnl:null}];
    held=true;await release;held=false;
    await route.fulfill({json:{ok:true,outcome:'accepted',message:'Order submitted. Check REAL history for settlement.'}});
  });
  await page.route('**/api/admin/trade-feed**',route=>{
    if(held)checksDuringPost++;
    return route.fulfill({json:{stream:'fixture-fast',cursor:0,events:[],recent:[],orders,sync:{...account(),provider_fetch_ms:240},gap:false}});
  });
  await signIn(page);await expect(page.locator('#order-big')).toBeEnabled();
  await page.locator('#order-amount').fill('100');
  page.once('dialog',dialog=>dialog.accept());await page.locator('#order-big').click();
  await expect(page.locator('#trade-orders li[data-request-id]')).toHaveCount(1);
  await expect(page.locator('#trade-orders')).toContainText('WAIT');
  await expect(page.locator('#order-result')).toContainText('WAIT');
  await expect.poll(()=>checksDuringPost).toBeGreaterThan(0);
  orders=[{...orders[0],outcome:'accepted',state:1,pnl:96,issue:'20261011103010700',result_source:'order_id'}];
  await expect(page.locator('#trade-orders .result-pill')).toHaveText('WIN');
  await expect(page.locator('#trade-orders')).toContainText('+96.00 MMK');
  await expect(page.locator('#order-big')).toBeDisabled();
  finishPost();
  await expect(page.locator('#order-big')).toBeEnabled();
  await expect(page.locator('#trade-orders .result-pill')).toHaveText('WIN');
  await expect(page.locator('#trade-orders li[data-request-id]')).toHaveCount(1);
  expect(posts).toBe(1);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('trade-order-settled.png'),fullPage:true});
});

test('offline and sync errors expose email/password; reconnect never disconnects a healthy session',async({page})=>{
  let state=account({active:false,status:'disconnected'}),deletes=0;
  await page.route('**/api/admin/trxchart-account',route=>{
    if(route.request().method()==='DELETE')deletes++;
    return route.fulfill({json:state});
  });
  await page.route('**/api/admin/trxchart-order',r=>r.fulfill({json:limits}));
  await signIn(page);
  await expect(page.getByLabel('TRXChart Phone / Email',{exact:true})).toBeVisible();
  await expect(page.getByLabel('TRXChart Password',{exact:true})).toBeVisible();
  await expect(page.locator('#trade-connection-badge')).toHaveText('CONNECT ACCOUNT');
  state=account();await page.locator('#trade-check-connection').click();
  await expect(page.locator('#journal-connect-form')).toBeHidden();
  await page.locator('#trade-reconnect').click();
  await expect(page.locator('#journal-connect-form')).toBeVisible();
  await page.locator('#trade-reconnect').click();
  await expect(page.locator('#journal-connect-form')).toBeHidden();
  state=account({status:'invalid_data',error:'History format error'});
  await page.locator('#trade-check-connection').click();
  await expect(page.locator('#trade-connection-badge')).toHaveText('SYNC DELAYED');
  await expect(page.locator('#journal-connect-form')).toBeVisible();
  expect(deletes).toBe(0);
});

test('freshness uses upstream sync time, and only Trade view requests fast watching',async({page})=>{
  let lastSync=new Date(Date.now()-120000).toISOString(),lastWatch;
  await page.route('**/api/admin/trxchart-account',r=>r.fulfill({json:account()}));
  await page.route('**/api/admin/trade-feed**',route=>{
    lastWatch=new URL(route.request().url()).searchParams.get('watch');
    return route.fulfill({json:{stream:'fixture-age',cursor:0,events:[],recent:[],orders:[],sync:{...account(),last_sync:lastSync,provider_fetch_ms:180},gap:false}});
  });
  await signIn(page);
  await expect(page.locator('#trade-live-state')).toHaveText('DELAYED');
  await expect(page.locator('#trade-feed-status')).toContainText('updates delayed');
  await expect.poll(()=>lastWatch).toBe('1');
  lastSync=new Date().toISOString();
  await expect(page.locator('#trade-live-state')).toHaveText('LIVE');
  await expect(page.locator('#trade-feed-status')).toContainText('fetch 180 ms');
  await page.locator('#trade').getByRole('link',{name:'View results ↗'}).click();
  await expect.poll(()=>lastWatch).toBe(null);
});

test('unknown and rejected outcomes remain distinct from a settled loss',async({page})=>{
  const now=new Date().toISOString();
  await page.route('**/api/admin/trade-feed**',r=>r.fulfill({json:{stream:'fixture-outcomes',cursor:0,events:[],recent:[],orders:[{id:'unknown',at:now,side:'BIG',stake:100,outcome:'unknown',state:-1,pnl:null},{id:'rejected',at:now,side:'SMALL',stake:100,outcome:'rejected',state:-1,pnl:null}],sync:account(),gap:false}}));
  await signIn(page);
  await expect(page.locator('#trade-orders')).toContainText('UNCERTAIN');
  await expect(page.locator('#trade-orders')).toContainText('REJECTED');
  await expect(page.locator('#trade-orders')).not.toContainText('LOSS');
  await expect(page.locator('#trade-wait-count')).toHaveText('0 WAIT');
});
