const {test,expect}=require('@playwright/test');

async function signIn(page){
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await page.goto('/admin#trade');
  await expect(page.locator('#notice')).toContainText('Connected.');
}
const trade=(id,state)=>({id,at:'2026-10-11T08:00:00Z',issue:'20261011103010115',side:'BIG',stake:100,state,number:state===1?8:state===0?2:null,pnl:state===1?96:state===0?-100:null});

test('Trade is a separate REAL workspace; Results tools are collapsed and amount presets never submit',async({page},testInfo)=>{
  let posts=0;
  await page.route('**/api/admin/trxchart-account',route=>route.fulfill({json:{revision:1,active:true,status:'connected',worker_alive:true,balance:'12500.50',balance_current:true}}));
  await page.route('**/api/admin/trxchart-order',route=>{if(route.request().method()==='POST')posts++;return route.fulfill({json:{enabled:true,unrestricted:true,max_amount:0,daily_max_count:0,daily_max_total:0,today_count:0,today_total:0,retry_after_sec:0}});});
  await page.route('**/api/admin/trade-feed**',route=>route.fulfill({json:{stream:'fixture-ui',cursor:0,events:[],recent:[trade('pending',-1),trade('win',1),trade('loss',0)],gap:false}}));
  await signIn(page);
  await expect(page.locator('#trade')).toBeVisible();
  await expect(page.locator('#journal')).toBeHidden();
  await expect(page.locator('#trade-balance')).toContainText('12,500.50');
  await page.locator('[data-amount="1000"]').click();
  await expect(page.locator('#order-amount')).toHaveValue('1000');
  await expect(page.locator('#order-big')).toBeEnabled();
  await expect(page.locator('#trade-activity')).toContainText('WAIT');
  await expect(page.locator('#trade-latest')).toContainText('WIN');
  expect(posts).toBe(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('trade-workspace.png'),fullPage:true});
  await page.locator('#trade').getByRole('link',{name:'View results ↗'}).click();
  await expect(page.locator('#journal')).toBeVisible();
  await expect(page.locator('#order-amount')).toBeHidden();
  await expect(page.locator('#journal-tp')).toBeHidden();
  await expect(page.locator('#journal-json')).toBeHidden();
  await expect(page.locator('#journal-account-phone')).toBeHidden();
  await page.locator('#journal-mode').selectOption('demo');
  await expect(page.locator('#journal-status')).toContainText('DEMO');
  await page.locator('#journal').getByRole('link',{name:'Go to Trade ↗'}).click();
  await expect(page.locator('#order-big')).toBeEnabled();
  expect(posts).toBe(0);
});

test('confirmed WIN and LOSS alerts follow account feed on other pages, never flood or replay on reload',async({page})=>{
  let sequence=10,stage=0,prompted=0;
  await page.addInitScript(()=>{
    class FixtureNotification {static permission='default';static async requestPermission(){window.notificationPrompts=(window.notificationPrompts||0)+1;return 'denied';}}
    Object.defineProperty(window,'Notification',{value:FixtureNotification,configurable:true});
  });
  await page.route('**/api/admin/trade-feed**',route=>{
    const q=new URL(route.request().url()).searchParams;
    const after=Number(q.get('after'));
    const events=stage?[{sequence:11,observed_at:'now',trade:trade('pending',1)}]:[];
    if(stage===2)events.push({sequence:12,observed_at:'now',trade:trade('second',0)});
    // Deliberately return duplicates: UI still must display each sequence once.
    return route.fulfill({json:{stream:'fixture-alerts',cursor:sequence,events:q.has('after')?events:[],recent:[trade('pending',stage?1:-1),trade('older',1)],gap:false}});
  });
  await signIn(page);
  await expect(page.locator('#trade-activity')).toContainText('WAIT');
  expect(await page.locator('.toast-win').count()).toBe(0);
  expect(await page.evaluate(()=>window.notificationPrompts||0)).toBe(0);
  sequence=11;stage=1;
  await expect(page.locator('.toast-win')).toHaveCount(1);
  await expect(page.locator('.toast-win')).toContainText('96.00 MMK');
  await expect(page.locator('.toast-win')).toContainText('20261011103010115');
  await expect(page.locator('#trade-activity')).not.toContainText('WAIT');
  await page.locator('#trade').getByRole('link',{name:'View results ↗'}).click();
  await page.locator('#journal-mode').selectOption('demo');
  sequence=12;stage=2;
  await expect(page.locator('.toast-loss')).toHaveCount(1);
  await expect(page.locator('.toast-loss')).toContainText('-100.00 MMK');
  await expect.poll(async()=>Number(await page.evaluate(()=>localStorage.getItem('trx-settlement:fixture-alerts')))).toBe(12);
  await page.reload();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await expect(page.locator('#trade-feed-status')).toContainText('Provider-confirmed');
  expect(await page.locator('.toast-win,.toast-loss').count()).toBe(0);
  await page.locator('#journal').getByRole('link',{name:'Go to Trade ↗'}).click();
  await page.locator('#trade-notifications').click();
  expect(await page.evaluate(()=>window.notificationPrompts)).toBe(1);
});

test('journal result filter preserves exact issue IDs and colours confirmed profit/loss',async({page})=>{
  const today='2026-10-11';
  await page.route('**/api/admin/trade-journal?**',route=>route.fulfill({json:{revision:1,limits:{tp:0,sl:0,timezone:'Asia/Yangon'},today,date:today,mode:'real',summary:{pnl:-4,staked:300,trades:3,wins:1,losses:1,pending:1,status:'limits_disabled'},rows:[trade('win',1),trade('loss',0),trade('pending',-1)],coverage:'Confirmed fixture records',synced_at:{}}}));
  await signIn(page);
  await page.locator('#trade').getByRole('link',{name:'View results ↗'}).click();
  await expect(page.locator('#journal-rows tr')).toHaveCount(3);
  await page.locator('#journal-result-filter').selectOption('0');
  await expect(page.locator('#journal-rows tr')).toHaveCount(1);
  await expect(page.locator('#journal-rows .result-pill')).toHaveText('LOSS');
  await expect(page.locator('#journal-rows .negative')).toContainText('-100.00');
  await expect(page.locator('#journal-rows')).toContainText('20261011103010115');
  await page.locator('#journal-result-filter').selectOption('-1');
  await expect(page.locator('#journal-rows .result-pill')).toHaveText('PENDING');
});
