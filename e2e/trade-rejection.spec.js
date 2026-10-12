const {test,expect}=require('@playwright/test');

test('rejected receipt shows saved HTTP diagnosis, stays non-loss and opens REAL history without a bet',async({page},testInfo)=>{
  let orderPosts=0,queries=[];
  const at='2026-10-11T08:00:00Z';
  await page.route('**/api/admin/trxchart-order',r=>{
    if(r.request().method()==='POST')orderPosts++;
    return r.fulfill({json:{enabled:true,unrestricted:true,max_amount:0,daily_max_count:0,daily_max_total:0,today_count:1,today_total:200,retry_after_sec:0}});
  });
  await page.route('**/api/admin/trade-feed**',r=>r.fulfill({json:{stream:'rejection-fixture',cursor:0,events:[],recent:[],orders:[{id:'rejected-fixture',at,side:'SMALL',stake:200,outcome:'rejected',state:-1,pnl:null,http_status:400,reason_code:'invalid_request',message:'TRXChart rejected the order (HTTP 400). The exact reason is unavailable. This request will not be resent.'}],sync:{active:true,status:'connected',last_sync:new Date().toISOString()},gap:false}}));
  await page.route('**/api/admin/trade-journal?**',r=>{
    const u=new URL(r.request().url());queries.push(u);
    return r.fulfill({json:{revision:1,date:u.searchParams.get('date')||'2026-10-12',today:'2026-10-12',mode:u.searchParams.get('mode')||'real',limits:{tp:0,sl:0,timezone:'Asia/Bangkok'},summary:{pnl:0,wins:0,losses:0,pending:0,trades:0,staked:0,status:'limits_disabled'},rows:[],synced_at:{},coverage:'Fixture history'}});
  });
  await page.goto('/admin/login');await page.getByLabel('Admin password').fill('fixture-admin-password');await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.goto('/admin#trade');
  await expect(page.locator('#trade-orders')).toContainText('HTTP 400');
  await expect(page.locator('#trade-orders .result-pill')).toHaveText('REJECTED');
  await expect(page.locator('#trade-wait-count')).toHaveText('0 WAIT');
  await page.locator('#trade').getByRole('link',{name:/View results ↗/i}).click();
  await page.locator('#journal-mode').selectOption('demo');
  await expect(page.locator('#journal-mode')).toHaveValue('demo');
  await page.locator('#journal-tp').fill('999');
  await page.locator('#journal').getByRole('link',{name:'Go to Trade ↗'}).click();
  await page.locator('#trade-orders').getByRole('link',{name:'Check REAL history ↗'}).click();
  await expect(page.locator('#journal')).toBeVisible();
  await expect(page.locator('#journal-mode')).toHaveValue('real');
  await expect(page.locator('#journal-date')).toHaveValue('2026-10-11');
  await expect(page.locator('#journal-search')).toHaveValue('SMALL');
  await expect(page.locator('#journal-tp')).toHaveValue('999');
  expect(queries.some(q=>q.searchParams.get('mode')==='real'&&q.searchParams.get('date')==='2026-10-11')).toBe(true);
  expect(orderPosts).toBe(0);
  await page.goto('/admin#trade');await expect(page.locator('#trade-orders')).toContainText('HTTP 400');
  await expect(page.locator('#trade-orders')).not.toContainText('LOSS');expect(orderPosts).toBe(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('rejected-order-diagnosis.png'),fullPage:true});
});
