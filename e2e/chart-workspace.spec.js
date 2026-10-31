const {test,expect}=require('@playwright/test');
async function ready(page){await page.goto('/');await expect.poll(()=>page.evaluate(()=>window.TRXChart?._qa.displaySnapshot().bars.length||0)).toBeGreaterThan(100);}
const view=page=>page.evaluate(()=>window.TRXChart._view());
const width=r=>r.to-r.from;

test('history navigation pauses follow; Live and Reset restore recent view while Fit shows full history',async({page})=>{
  await ready(page);await expect(page.locator('#chart-follow')).toBeChecked();
  await page.locator('#chart-more-toggle').click();await page.locator('#fit-btn').click();
  await expect(page.locator('#chart-follow')).not.toBeChecked();await expect.poll(async()=>width(await view(page))).toBeGreaterThan(323);const fitted=await view(page);
  await page.locator('#zoom-reset-btn').click();await expect(page.locator('#chart-follow')).toBeChecked();
  await expect.poll(async()=>width(await view(page))).toBeCloseTo(323,2);
  expect(width(await view(page))).toBeLessThan(width(fitted));
  await page.locator('#chart-more-toggle').click();await page.locator('#zoom-in-btn').click();
  const box=await page.locator('#tv-chart').boundingBox();
  await page.mouse.move(box.x+box.width*.3,box.y+box.height*.45);await page.mouse.down();await page.mouse.move(box.x+box.width*.65,box.y+box.height*.45,{steps:12});await page.mouse.up();
  await expect(page.locator('#chart-follow')).not.toBeChecked();await expect(page.locator('#chart-view-status')).toContainText('History');
  const before=await view(page);
  await page.evaluate(()=>{const info=window.TRXChart.studyInfo(),last=info.rows.at(-1);window.TRXChart.appendLatest({...last,issue:String(BigInt(last.issue)+1n),short_issue:'new',number:8,type:'BIG',block_time:new Date(Date.parse(String(last.block_time).replace(' ','T')+'Z')+60000).toISOString().slice(0,19).replace('T',' ')});});
  expect(width(await view(page))).toBeCloseTo(width(before),2);expect((await view(page)).from).toBeCloseTo(before.from,2);
  await page.getByRole('button',{name:'Back to Live',exact:true}).click();await expect(page.locator('#chart-follow')).toBeChecked();
  await expect.poll(async()=>width(await view(page))).toBeCloseTo(323,2);
  const live=await view(page);await page.evaluate(()=>{const info=window.TRXChart.studyInfo(),last=info.rows.at(-1);window.TRXChart.appendLatest({...last,issue:String(BigInt(last.issue)+1n),short_issue:'new2',number:3,type:'SMALL',block_time:new Date(Date.parse(String(last.block_time).replace(' ','T')+'Z')+60000).toISOString().slice(0,19).replace('T',' ')});});
  await expect.poll(async()=>(await view(page)).to).toBeGreaterThan(live.to);expect(width(await view(page))).toBeCloseTo(width(live),2);
  await page.locator('#zoom-in-btn').click();await expect.poll(async()=>width(await view(page))).toBeCloseTo(242.25,2);
  await page.evaluate(()=>{window.TRXChart.backToLive();const last=window.TRXChart.studyInfo().rows.at(-1);window.TRXChart.appendLatest({...last,issue:String(BigInt(last.issue)+1n),number:8,type:'BIG'});});
  await expect.poll(async()=>width(await view(page))).toBeCloseTo(323,2);
});

test('manual refresh shows progress, preserves historical zoom and drawings, and reports history failure',async({page})=>{
  await ready(page);await page.locator('#chart-follow').uncheck();await page.locator('#zoom-in-btn').click();
  await page.locator('#dt-toggle-btn').click();await page.locator('[data-tool=hline]').click();
  const b=await page.locator('#tv-chart').boundingBox();await page.mouse.click(b.x+b.width*.6,b.y+b.height*.5);
  await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().count)).toBe(1);
  const drawings=await page.evaluate(()=>localStorage.getItem('trx_drawings_v3'));const before=await view(page);let release,held=false,fail=false;
  const gate=new Promise(r=>release=r);
  await page.route('**/api/history*',async r=>{if(fail)return r.fulfill({status:503,json:{error:'Fixture outage'}});held=true;await gate;return r.continue();});
  await page.getByRole('button',{name:'Refresh chart',exact:true}).click();await expect(page.locator('#chart-refresh')).toHaveAttribute('aria-busy','true');await expect.poll(()=>held).toBe(true);release();
  await expect(page.locator('#chart-refresh-status')).toContainText('Chart refreshed');await expect(page.locator('#chart-refresh')).toBeEnabled();
  expect((await view(page)).from).toBeCloseTo(before.from,1);expect(width(await view(page))).toBeCloseTo(width(before),1);
  expect(await page.evaluate(()=>localStorage.getItem('trx_drawings_v3'))).toBe(drawings);await expect(page.locator('#chart-follow')).not.toBeChecked();
  fail=true;await page.locator('#chart-refresh').click();await expect(page.locator('#chart-refresh-status')).toContainText('Refresh failed');await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
  expect(await page.evaluate(()=>window.TRXDraw._dbg().count)).toBe(1);
});

test('Magnet is available before drawing; inspection pins real candle data without creating drawings',async({page},info)=>{
  await ready(page);await expect(page.locator('#chart-magnet')).toBeVisible();
  await page.locator('#chart-magnet').click();await expect(page.locator('#chart-magnet')).toHaveAttribute('aria-pressed','false');
  await page.reload();await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().apiReady)).toBe(true);await expect.poll(()=>page.evaluate(()=>window.TRXChart?._qa.displaySnapshot().bars.length||0)).toBeGreaterThan(100);await expect(page.locator('#chart-magnet')).toHaveText('Magnet OFF');
  await page.locator('#chart-inspect').click();await page.locator('#tv-chart').scrollIntoViewIfNeeded();const b=await page.locator('#tv-chart').boundingBox();
  if(info.project.name.includes('mobile')){for(const ratio of [.52,.35,.7]){await page.touchscreen.tap(b.x+b.width*ratio,b.y+b.height*.45);if(await page.locator('#inspector-values').textContent())break;}}else await page.mouse.click(b.x+b.width*.52,b.y+b.height*.45);
  await expect(page.locator('#inspector-values')).toContainText('Latest issue');await expect(page.locator('#inspector-values')).toContainText('RSI 14');await expect(page.locator('#inspector-values')).toContainText('digit');
  expect(await page.evaluate(()=>window.TRXDraw._dbg().count)).toBe(0);
  await page.getByRole('button',{name:'Close candle inspector',exact:true}).click();await expect(page.locator('#candle-inspector')).toBeHidden();
  await page.locator('#chart-inspect').click();await page.locator('#dt-toggle-btn').click();await page.locator('[data-tool=trend]').click();await expect(page.locator('#chart-inspect')).toHaveAttribute('aria-pressed','false');
});

test('mobile controls have large touch targets and public chart remains within the viewport',async({page},info)=>{
  await ready(page);if(info.project.name.includes('mobile'))for(const id of ['chart-live','chart-magnet','chart-refresh','chart-inspect','zoom-in-btn','dt-toggle-btn']){const b=await page.locator('#'+id).boundingBox();expect(b.width).toBeGreaterThanOrEqual(44);expect(b.height).toBeGreaterThanOrEqual(44);}
  await page.locator('#chart-more-toggle').click();await expect(page.locator('#history-range-select')).toBeVisible();
  await page.locator('#chart-more-toggle').click();await page.locator('#dt-toggle-btn').click();await page.locator('#dt-options').click();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1)).toBe(true);
  await page.screenshot({path:info.outputPath('chart-workspace.png'),fullPage:true});
});
