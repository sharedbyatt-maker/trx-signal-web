const {test,expect}=require('@playwright/test');

test('private journal imports past results and separates targets from strategy controls',async({page},testInfo)=>{
  let data={revision:0,limits:{tp:0,sl:0,timezone:'Asia/Bangkok'},today:'2026-10-10',date:'2026-10-10',mode:'real',summary:{pnl:0,staked:0,trades:0,wins:0,losses:0,pending:0,status:'limits_disabled'},rows:[],stored_records:0,imported_at:null,coverage:'Imported records only; pending records excluded.'};
  await page.route('**/api/admin/trade-journal**',async route=>{
    const req=route.request(),url=new URL(req.url());
    if(url.pathname.endsWith('/import')){
      const body=req.postDataJSON();expect(body.history.list[0].issueNumber).toBe('20261010103010800');expect(body.mode).toBe('real');expect(body.source_timezone).toBe('Asia/Yangon');
      data={...data,revision:data.revision+1,stored_records:1,imported_at:'2026-10-10T05:00:00Z',summary:{pnl:98,staked:100,trades:1,wins:1,losses:0,pending:0,status:'tp_reached'},rows:[{at:'2026-10-10T05:00:00Z',issue:'20261010103010800',side:'BIG',stake:100,state:1,pnl:98,number:8}]};
      return route.fulfill({json:{...data,import_result:{added:1,updated:0,unchanged:0}}});
    }
    if(req.method()==='PUT'){const body=req.postDataJSON();expect(body.revision).toBe(0);data={...data,revision:1,limits:body.limits,summary:{...data.summary,status:'within_limits'}};}
    const mode=url.searchParams.get('mode')||'real';
    await route.fulfill({json:mode==='demo'?{...data,mode,summary:{pnl:0,staked:0,trades:0,wins:0,losses:0,pending:0,status:'within_limits'},rows:[]}:{...data,mode}});
  });
  await page.goto('/admin/login');
  await page.getByLabel('Admin password').fill('fixture-admin-password');
  await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await expect(page.locator('#notice')).toContainText('Connected.');
  await page.goto('/admin#journal');
  await expect(page.locator('#notice')).toContainText('Connected.');
  await expect(page.locator('#journal')).toBeVisible();
  await page.getByText('Report settings',{exact:true}).click();
  await page.locator('#journal-tp').fill('50');
  await page.locator('#journal-sl').fill('100');
  await expect(page.locator('#draft-summary')).toContainText('Trade targets');
  await page.locator('#journal-save').click();
  await expect(page.locator('#notice')).toContainText('Daily targets saved');
  await page.getByText('Import / export tools',{exact:true}).click();
  await page.locator('#journal-json').fill('invalid JSON');
  await page.locator('#journal-import').click();
  await expect(page.locator('#notice')).toContainText('History is not valid JSON');
  await expect(page.locator('#journal-json')).toHaveValue('invalid JSON');
  await page.locator('#journal-json').fill(JSON.stringify({success:true,list:[{addTime:'2026-10-10 11:30:00',issueNumber:'20261010103010800',selectType:'big',amount:100,profitAmount:198,state:1,number:8}]}));
  await page.locator('#journal-import').click();
  await expect(page.locator('#journal-status')).toContainText('TP reached');
  await expect(page.locator('#journal-stats')).toContainText('98.00');
  await expect(page.locator('#journal-rows')).toContainText('20261010103010800');
  await expect(page.locator('#journal-json')).toHaveValue('');
  await expect(page.locator('#journal-coverage')).toContainText('Imported records only');
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth+1)).toBe(true);
  await page.screenshot({path:testInfo.outputPath('journal.png'),fullPage:true});
  await page.locator('#journal-mode').selectOption('demo');
  await expect(page.locator('#journal-rows')).toContainText('No records yet');
  await expect(page.locator('#journal-status')).toContainText('DEMO');
});
