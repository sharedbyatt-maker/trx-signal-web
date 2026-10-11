const {test,expect}=require('@playwright/test');
const fs=require('node:fs');
const bridge=fs.readFileSync('static/js/trxchart-history-bridge.js','utf8');

test('browser sync saves exact IDs, settles pending orders and keeps credentials on provider',async({page,baseURL})=>{
  let settled=false;
  const orderId=String(Date.now())+'1234';
  let baseline;
  const providerRequests=[],saved=[];
  page.on('dialog',dialog=>dialog.dismiss());
  await page.route('https://trxchart.com/**',async route=>{
    const url=new URL(route.request().url());
    if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<button id="history">History</button><script>document.getElementById("history").onclick=()=>fetch("/api/bet/history?size=100",{headers:{"X-API-Token":"fixture-provider-secret"}});</script>'});
    providerRequests.push({path:url.pathname,method:route.request().method(),token:route.request().headers()['x-api-token']});
    if(url.pathname==='/api/demo/history')return route.fulfill({json:{success:true,list:[]}});
    expect(url.pathname).toBe('/api/bet/history');
    return route.fulfill({contentType:'application/json',body:'{"success":true,"list":[{"addTime":"'+new Date().toISOString()+'","issueNumber":20261011103010001,"id":'+orderId+',"selectType":"big","amount":100,"profitAmount":198,"state":'+(settled?1:-1)+',"number":'+(settled?8:'null')+',"token":"fixture-unused-secret"}]}'});
  });
  await page.goto('/admin/login');await page.getByLabel('Admin password').fill('fixture-admin-password');await page.getByRole('button',{name:'Sign in',exact:true}).click();
  baseline=await (await page.request.get(baseURL+'/api/admin/trade-journal?mode=real')).json();
  await page.goto('https://trxchart.com/');
  await page.clock.install();
  await page.addScriptTag({content:bridge});
  const waiting=page.waitForEvent('popup');
  await page.evaluate(origin=>trxHistoryBridge(origin),baseURL);
  const receiver=await waiting;
  receiver.on('request',request=>{if(request.url().endsWith('/trade-journal/sync'))saved.push(request.postData());});
  await receiver.getByRole('button',{name:'Accept browser sync',exact:true}).click();
  await page.getByRole('button',{name:'History',exact:true}).click();
  await expect(receiver.locator('#sync-real')).toContainText((baseline.summary.trades+1)+' today');
  const first=await receiver.request.get(baseURL+'/api/admin/trade-journal?mode=real');
  expect((await first.json()).summary.pending).toBe(baseline.summary.pending+1);
  // A later history snapshot retains the creation timestamp for the same order.
  const stamp=JSON.parse(saved.find(Boolean)).history.list[0].addTime;
  settled=true;
  await page.unroute('https://trxchart.com/**');
  await page.route('https://trxchart.com/api/**',async route=>{
    const url=new URL(route.request().url());providerRequests.push({path:url.pathname,method:route.request().method(),token:route.request().headers()['x-api-token']});
    return route.fulfill({contentType:'application/json',body:url.pathname==='/api/demo/history'?'{"success":true,"list":[]}':'{"success":true,"list":[{"addTime":"'+stamp+'","issueNumber":20261011103010001,"id":'+orderId+',"selectType":"big","amount":100,"profitAmount":198,"state":1,"number":8}]}'});
  });
  await page.clock.fastForward(60000);
  await expect(receiver.locator('#sync-real')).toContainText((baseline.summary.pnl+98).toLocaleString()+' MMK');
  await expect(receiver.locator('#sync-demo')).toContainText('0 today');
  const result=await (await receiver.request.get(baseURL+'/api/admin/trade-journal/export?mode=real')).json();
  const record=result.list.find(r=>r.orderId===orderId);expect(record.issueNumber).toBe('20261011103010001');expect(record.state).toBe(1);expect(result.list.filter(r=>r.orderId===orderId).length).toBe(1);
  expect(saved.join('')).not.toContain('fixture-provider-secret');expect(saved.join('')).not.toContain('fixture-unused-secret');
  expect(providerRequests.every(r=>r.method==='GET'&&r.token==='fixture-provider-secret')).toBe(true);
  await receiver.getByRole('button',{name:'Stop sync',exact:true}).click();
  await expect.poll(()=>page.evaluate(()=>!!window.__trxHistoryBridge)).toBe(false);
});

test('sync receiver refuses unsolicited or wrong-origin data before saving',async({page})=>{
  await page.goto('/admin/login');await page.getByLabel('Admin password').fill('fixture-admin-password');await page.getByRole('button',{name:'Sign in',exact:true}).click();
  await page.goto('/admin/trxchart-sync?bridge='+'a'.repeat(48));
  let writes=0;page.on('request',r=>{if(r.url().endsWith('/trade-journal/sync'))++writes;});
  await page.getByRole('button',{name:'Accept browser sync',exact:true}).click();
  await expect(page.locator('#sync-status')).toContainText('connection bookmark');
  await page.evaluate(()=>window.dispatchEvent(new MessageEvent('message',{origin:'https://evil.invalid',data:{type:'trx-history',nonce:'a'.repeat(48),mode:'real',history:{success:true,list:[]}}})));
  expect(writes).toBe(0);
});
