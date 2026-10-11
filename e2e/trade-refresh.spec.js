const {test,expect}=require('@playwright/test');
const limits={enabled:true,unrestricted:true,max_amount:0,daily_max_count:0,daily_max_total:0,today_count:0,today_total:0,retry_after_sec:0};
const row=(id,state,side='BIG')=>({id,at:'2026-10-11T08:00:00Z',issue:'2026101110301070'+id,side,stake:100,state,number:state===1?8:state===0?2:null,pnl:state===1?96:state===0?-100:null});
async function signIn(page){await page.goto('/admin/login');await page.getByLabel('Admin password').fill('fixture-admin-password');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.locator('#notice')).toContainText('Connected.');await page.goto('/admin#trade');await expect(page.locator('#notice')).toContainText('Connected.');}
async function fixtures(page,options={}){
  const state={revision:1,rows:[row('1',1),row('2',0,'SMALL'),row('3',-1)],sync:'2026-10-11T08:00:00Z',balanceAt:'2026-10-11T08:00:00Z',orders:[],connected:true,refreshes:[],posts:0,...options};
  const account=()=>({revision:1,active:state.connected,status:state.connected?'connected':'disconnected',worker_alive:true,last_sync:state.sync,balance:'12500.50',balance_current:true,balance_at:state.balanceAt});
  await page.route('**/api/admin/trxchart-account',r=>r.fulfill({json:account()}));
  await page.route('**/api/admin/trxchart-order',r=>{if(r.request().method()==='POST')state.posts++;return r.fulfill({json:limits});});
  await page.route('**/api/admin/trade-journal?**',route=>{
    const q=new URL(route.request().url()).searchParams,settled=state.rows.filter(r=>r.state!==-1);
    return route.fulfill({json:{revision:state.revision,limits:{tp:0,sl:0,timezone:'Asia/Bangkok'},today:'2026-10-11',date:q.get('date')||'2026-10-11',mode:q.get('mode'),summary:{pnl:settled.reduce((n,r)=>n+r.pnl,0),staked:300,trades:3,wins:settled.filter(r=>r.state===1).length,losses:settled.filter(r=>r.state===0).length,pending:state.rows.length-settled.length,status:'limits_disabled'},rows:state.rows,coverage:'Provider fixture records; limited coverage.',synced_at:{real:state.sync,demo:state.sync}}});
  });
  await page.route('**/api/admin/trade-feed**',r=>r.fulfill({json:{stream:'fixture-refresh',cursor:0,events:[],recent:state.rows,orders:state.orders,sync:{...account(),provider_fetch_ms:220},journal_revision:state.revision,gap:false}}));
  return {state,account};
}

test('refresh icons queue reads only, show progress and preserve report filters and target drafts',async({page})=>{
  const {state,account}=await fixtures(page);let finish;const release=new Promise(resolve=>finish=resolve);
  await page.route('**/api/admin/trxchart-account/refresh',async route=>{state.refreshes.push(route.request().postDataJSON().mode);await release;state.sync=new Date().toISOString();state.balanceAt=state.sync;state.revision++;await route.fulfill({json:account()});});
  await signIn(page);await expect(page.getByRole('button',{name:'Refresh Trade',exact:true})).toBeVisible();
  await page.locator('#trade').getByRole('link',{name:'View results ↗'}).click();
  await page.locator('#journal-mode').selectOption('demo');await expect(page.locator('#notice')).toContainText('Selected history');
  await page.locator('#journal-date').fill('2026-10-10');await expect(page.locator('#journal-status')).toContainText('2026-10-10');
  await page.getByText('Report settings',{exact:true}).click();await page.locator('#journal-tp').fill('42.50');
  await page.locator('#journal-search').fill('BIG');await page.locator('#journal-result-filter').selectOption('1');
  await page.getByRole('button',{name:'Refresh Trade Results',exact:true}).click();
  await expect(page.locator('#journal-refresh')).toHaveAttribute('aria-busy','true');await expect(page.locator('#journal-refresh-state')).toContainText('Refreshing DEMO');
  finish();await expect(page.locator('#journal-refresh-state')).toContainText('DEMO history updated');
  await expect(page.locator('#journal-refresh')).toBeEnabled();await expect(page.locator('#journal-tp')).toHaveValue('42.50');
  await expect(page.locator('#journal-date')).toHaveValue('2026-10-10');await expect(page.locator('#journal-mode')).toHaveValue('demo');
  await expect(page.locator('#journal-search')).toHaveValue('BIG');await expect(page.locator('#journal-result-filter')).toHaveValue('1');
  await expect(page.locator('#journal-rows tr')).toHaveCount(1);expect(state.refreshes).toEqual(['demo']);expect(state.posts).toBe(0);
});

test('visible Results follows committed revisions and keeps drafts; win rate excludes WAIT',async({page},testInfo)=>{
  const {state}=await fixtures(page);await signIn(page);await page.locator('#trade').getByRole('link',{name:'View results ↗'}).click();
  await expect(page.locator('#journal-stats')).toContainText('50.0%');await page.getByText('Report settings',{exact:true}).click();await page.locator('#journal-tp').fill('123');await page.getByText('Report settings',{exact:true}).click();
  await page.locator('#journal-search').fill('BIG');await expect(page.locator('#journal-visible-count')).toHaveText('2 of 3 displayed records');
  state.rows=[row('1',1),row('2',0,'SMALL'),row('3',1)];state.sync=new Date().toISOString();state.revision++;
  await expect(page.locator('#journal-stats')).toContainText('66.7%');await expect(page.locator('#journal-rows .result-pill')).toHaveText(['WIN','WIN']);
  await expect(page.locator('#journal-tp')).toHaveValue('123');await expect(page.locator('#journal-search')).toHaveValue('BIG');
  await page.locator('#journal-search').fill('no matching issue');await expect(page.locator('#journal-rows')).toContainText('No matching records');
  await page.locator('#journal-clear-search').click();await expect(page.locator('#journal-rows tr')).toHaveCount(3);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  if(testInfo.project.name.includes('mobile')){
    await page.locator('#journal-rows tr').first().scrollIntoViewIfNeeded();
    const visible=await page.locator('#journal-rows tr').first().evaluate(tr=>[tr.children[4],tr.children[5]].every(el=>{const r=el.getBoundingClientRect();return r.left>=0&&r.right<=innerWidth;}));
    expect(visible).toBe(true);
  }
  await page.screenshot({path:testInfo.outputPath('results-focused.png'),fullPage:true});
});

test('old unlinked receipt is CHECK HISTORY, not active WAIT; provider account orders show verified WAIT',async({page})=>{
  await fixtures(page,{orders:[{id:'old-receipt',at:new Date(Date.now()-600000).toISOString(),side:'BIG',stake:100,outcome:'accepted',state:-1,pnl:null}]});
  await signIn(page);await expect(page.locator('#trade-wait-count')).toHaveText('0 WAIT · 1 CHECK HISTORY');
  await expect(page.locator('#trade-orders .result-pill')).toHaveText('CHECK HISTORY');await expect(page.locator('#trade-activity')).toContainText('WAIT');
  await page.locator('#trade-orders').getByRole('link',{name:'Find in Results ↗'}).click();await expect(page.locator('#journal')).toBeVisible();await expect(page.locator('#journal-search')).toHaveValue('BIG');
});

test('disconnected refresh reloads saved history without provider calls and does not repeat an order',async({page})=>{
  const {state}=await fixtures(page,{connected:false});let providerCalls=0;
  await page.route('**/api/admin/trxchart-account/refresh',route=>{providerCalls++;return route.fulfill({json:{}});});
  await signIn(page);await page.getByRole('button',{name:'Refresh Trade',exact:true}).click();
  await expect(page.locator('#trade-refresh-state')).toContainText('Saved history refreshed');
  await expect(page.locator('#trade-refresh')).toBeEnabled();await expect(page.locator('#journal-connect-form')).toBeVisible();expect(providerCalls).toBe(0);expect(state.posts).toBe(0);
});
