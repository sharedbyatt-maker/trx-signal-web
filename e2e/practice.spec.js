const {test,expect}=require('@playwright/test');
const rows=p=>p.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3')||'[]'));
const dbg=p=>p.evaluate(()=>TRXDraw._dbg());
const study=p=>p.evaluate(()=>{const s=TRXChart.studyInfo();return {...s,rows:s.rows.map(r=>({issue:r.issue,type:r.type})),choices:undefined};});
async function ready(page){await page.addInitScript(()=>localStorage.setItem('trx_draw_v2_prefs',JSON.stringify({magnet:false})));await page.goto('/');await expect.poll(async()=>(await dbg(page)).apiReady).toBe(true);await page.locator('#dt-toggle-btn').click();}
async function shape(page,type='hline',touch=false){await page.locator(`[data-tool="${type}"]`).click();await page.locator("#tv-chart").scrollIntoViewIfNeeded();const b=await page.locator('#tv-chart').boundingBox();const a={x:b.x+b.width*.27,y:b.y+b.height*.78},z={x:b.x+b.width*.58,y:b.y+b.height*.58};if(touch){await page.touchscreen.tap(a.x,a.y);if(type==='fib')await page.touchscreen.tap(z.x,z.y);}else{await page.mouse.click(a.x,a.y);if(type==='fib')await page.mouse.click(z.x,z.y);}await expect.poll(async()=>(await dbg(page)).count).toBe(1);return {a,z};}
async function practice(page){await page.locator('#study-toggle').click();await page.locator('#replay-start').click();await expect(page.locator('#replay-controls')).toBeVisible();await expect.poll(async()=>(await study(page)).mode).toBe('replay');}
async function freezeFixture(page){
 // These tests inject chart ticks directly; stop the static HTTP fixture replacing them.
 for(const path of ['state','latest','history**'])await page.route('**/api/'+path,route=>route.abort());
 await page.waitForTimeout(500); // Drain any fixture response already in flight.
}
test('full undo/redo restores style, deleted object, hidden state and clears redo on a new edit',async({page},info)=>{
 await ready(page);await shape(page,'hline',info.project.name.includes('mobile'));const original=await rows(page);
 await page.locator('#dt-v2-width').selectOption('4');await page.locator('#dt-undo').click();expect(await rows(page)).toEqual(original);
 await page.locator('#dt-redo').click();expect((await rows(page))[0].width).toBe(4);
 await page.locator('#dt-list').click();await page.getByRole('button',{name:'Delete hline 1',exact:true}).click();expect(await rows(page)).toHaveLength(0);
 await page.locator('#dt-undo').click();expect((await rows(page))[0].width).toBe(4);
 await page.getByRole('button',{name:'Hide hline 1',exact:true}).click();await page.locator('#dt-undo').click();expect((await rows(page))[0].hidden).toBe(false);
 await page.getByRole('button',{name:'Lock hline 1',exact:true}).click();await expect(page.locator('#dt-redo')).toBeDisabled();
 await page.keyboard.press('Control+z');expect((await rows(page))[0].locked).toBe(false);await page.keyboard.press('Control+Shift+z');expect((await rows(page))[0].locked).toBe(true);
});
test('Fibonacci up/down mode orients zero correctly regardless of anchor order and persists',async({page},info)=>{
 await ready(page);await page.getByLabel('New Fibonacci mode').selectOption('up');await shape(page,'fib',info.project.name.includes('mobile'));
 let d=(await rows(page))[0];expect(d.fibMode).toBe('up');expect(d.fibReverse).toBe(d.points[0].p<d.points[1].p);
 await page.locator('#dt-v2-fib').click();await page.getByLabel('Selected Fibonacci mode').selectOption('down');d=(await rows(page))[0];expect(d.fibReverse).toBe(d.points[0].p>d.points[1].p);
 await page.reload();await expect.poll(async()=>(await dbg(page)).count).toBe(1);expect((await rows(page))[0]).toEqual(d);
});
test('drawing manager selects hidden objects and a preset styles new objects after reload',async({page},info)=>{
 await ready(page);await shape(page,'hline',info.project.name.includes('mobile'));await page.locator('#dt-v2-width').selectOption('4');await page.locator('#dt-list').click();
 page.once('dialog',d=>d.accept('My support'));await page.locator('#dt-preset-save').click();
 await page.getByRole('button',{name:'Hide hline 1',exact:true}).click();await page.getByRole('button',{name:'Show hline 1',exact:true}).click();await page.getByRole('button',{name:'Select hline 1',exact:true}).click();
 await page.reload();await expect.poll(async()=>(await dbg(page)).count).toBe(1);await page.locator('#dt-toggle-btn').click();await page.locator('#dt-list').click();const v=await page.locator('#drawing-preset option').last().getAttribute('value');await page.locator('#drawing-preset').selectOption(v);await page.locator('#dt-list-close').click();
 await page.locator('[data-tool="hline"]').click();const b=await page.locator('#tv-chart').boundingBox();await page.mouse.click(b.x+b.width*.5,b.y+b.height*.5);expect((await rows(page))[1].width).toBe(4);
});
test('replay hides future bars and indicators, isolates drawings and returns to unchanged live drawings',async({page},info)=>{
 await ready(page);await shape(page,'hline',info.project.name.includes('mobile'));const before=await rows(page);const live=await study(page);const context=await page.evaluate(()=>TRXChart.getComparisons());
 await practice(page);await expect.poll(async()=>(await dbg(page)).count).toBe(0);const replay=await study(page);expect(replay.rows.length).toBeLessThan(live.rows.length);expect(replay.issue).not.toBe(live.issue);
 const displayed=await page.evaluate(()=>TRXChart._qa.displaySnapshot());expect(displayed.bars).toHaveLength(replay.rows.length);expect(displayed.rsi).toHaveLength(replay.rows.length);expect(displayed.bars.at(-1).c).toBe(100+replay.rows.reduce((sum,r)=>sum+(r.type==='BIG'?1:-1),0));
 expect(await page.evaluate(()=>TRXChart.getComparisons())).toEqual(context);
 expect(await rows(page)).toEqual(before);await shape(page,'hline',info.project.name.includes('mobile'));expect(await rows(page)).toEqual(before);
 await page.locator('#replay-next').click();expect((await study(page)).rows.length).toBe(replay.rows.length+1);
 await page.locator('.tf-btn[data-g="5"]').click();const grouped=await study(page);expect(grouped.issue).toBe((await study(page)).issue);await page.locator('#replay-next').click();const after=await study(page);expect(after.rows.length-grouped.rows.length).toBeGreaterThanOrEqual(1);expect(after.rows.length-grouped.rows.length).toBeLessThanOrEqual(5);
 await page.locator('#replay-live').click();expect((await study(page)).mode).toBe('live');expect((await study(page)).issue).toBe(live.issue);expect(await rows(page)).toEqual(before);expect((await dbg(page)).count).toBe(1);
});
test('replay remains frozen when new live data arrives; returning live catches up',async({page})=>{
 await ready(page);await freezeFixture(page);await practice(page);const old=await study(page);
 await page.evaluate(()=>{const s=TRXChart.studyInfo();const row={issue:String(BigInt('20260913000000360')+1n),number:8,type:'BIG',block_time:'2026-09-13 14:00:00'};TRXChart.appendLatest(row);});
 expect((await study(page)).issue).toBe(old.issue);await page.locator('#replay-live').click();await expect.poll(async()=>(await study(page)).issue).toBe('20260913000000361');
});
test('replay seek, play, pause and end-of-history controls are deterministic',async({page})=>{
 await ready(page);await practice(page);await page.locator('#replay-position').selectOption('1');expect((await study(page)).rows).toHaveLength(1);await page.locator('#replay-position').selectOption('20');const start=await study(page);expect(start.position).toBe(20);
 await page.locator('#replay-speed').selectOption('500');await page.locator('#replay-play').click();await expect.poll(async()=>(await study(page)).position).toBeGreaterThan(20);await page.locator('#replay-play').click();expect((await study(page)).playing).toBe(false);
 const end=String((await study(page)).total);await page.locator('#replay-position').selectOption(end);await expect(page.locator('#replay-next')).toBeDisabled();await page.locator('#replay-play').click();expect((await study(page)).playing).toBe(false);
});
test('journal locks a prospective replay observation and reveals result only after stepping',async({page})=>{
 await ready(page);await practice(page);await page.locator('#journal-toggle').click();await page.locator('#journal-note').fill('Fib 0.618 zone');await page.locator('#journal-save').click();
 await expect(page.locator('.journal-entry')).toHaveCount(1);await expect(page.locator('.journal-entry')).toContainText('PENDING');await expect(page.locator('#journal-save')).toBeDisabled();const pos=(await study(page)).position;
 await page.locator('#replay-next').click();await expect(page.locator('.journal-entry')).toContainText(/MATCH|MISS/);await expect(page.locator('#journal-summary')).toContainText('0 settled');
 await page.locator('#replay-position').selectOption(String(pos));await expect(page.locator('.journal-entry')).toContainText('PENDING');
 await page.reload();await expect.poll(async()=>(await dbg(page)).apiReady).toBe(true);await page.locator('#study-toggle').click();await page.locator('#journal-toggle').click();await expect(page.locator('.journal-entry')).toContainText('Switch to REPLAY');
});
test('live journal settles next result, archives/restores and exports locked entries',async({page})=>{
 await ready(page);await page.locator('#study-toggle').click();await page.locator('#journal-toggle').click();await page.locator('#journal-note').fill('Manual hypothesis');await page.locator('#journal-save').click();const base=await study(page);
 await page.evaluate(()=>TRXChart.appendLatest({issue:'20260913000000361',number:8,type:'BIG',block_time:'2026-09-13 14:00:00'}));
 await expect(page.locator('.journal-entry')).toContainText('MATCH');await expect(page.locator('#journal-summary')).toContainText('1 settled');
 const dp=page.waitForEvent('download');await page.locator('#journal-export').click();const data=JSON.parse(require('node:fs').readFileSync(await (await dp).path(),'utf8'));expect(data.observations[0]).toMatchObject({issue:base.issue,expected:'BIG',note:'Manual hypothesis',actual:'BIG'});
 await page.getByRole('button',{name:'Archive',exact:true}).click();await expect(page.locator('.journal-entry')).toHaveCount(0);await expect(page.locator('#journal-summary')).toContainText('1 settled');await page.locator('#journal-archived').check();await page.getByRole('button',{name:'Restore',exact:true}).click();await page.locator('#journal-archived').uncheck();await expect(page.locator('.journal-entry')).toHaveCount(1);
});
test('invalid journal import preserves records; imported records cannot inflate live accuracy',async({page})=>{
 await ready(page);await page.locator('#study-toggle').click();await page.locator('#journal-toggle').click();await page.locator('#journal-note').fill('Original');await page.locator('#journal-save').click();
 let chooser=page.waitForEvent('filechooser');await page.locator('#journal-import').click();await(await chooser).setFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{bad')});await expect(page.locator('#journal-status')).toContainText('Invalid journal');await expect(page.locator('.journal-entry')).toHaveCount(1);
 const e=await page.evaluate(()=>JSON.parse(localStorage.getItem('trx_observation_journal_v1'))[0]);e.id+='copy';e.issue='20260913000000359';e.actual='BIG';
 chooser=page.waitForEvent('filechooser');await page.locator('#journal-import').click();await(await chooser).setFiles({name:'valid.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify({observations:[e]}))});await expect(page.locator('.journal-entry')).toHaveCount(2);await expect(page.locator('#journal-summary')).toContainText('0 settled');await expect(page.locator('.journal-entry').first()).toContainText('IMPORTED');
});
test('practice controls and manager fit 320px without page overflow',async({page},info)=>{
 test.skip(!info.project.name.includes('mobile'),'phone layout');await page.setViewportSize({width:320,height:740});await ready(page);await shape(page,'fib',true);await page.locator('#dt-list').click();await expect(page.locator('#drawing-manager')).toBeVisible();await page.locator('#dt-list-close').click();await practice(page);await page.locator('#journal-toggle').click();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('drawing edits remain undoable after timeframe remapping',async({page},info)=>{
 await ready(page);await shape(page,'fib',info.project.name.includes('mobile'));const original=await rows(page);
 await page.locator('.tf-btn[data-g="5"]').click();await page.locator('#dt-v2-width').selectOption('4');await page.locator('#dt-undo').click();expect((await rows(page))[0].width).toBe(original[0].width);expect((await rows(page))[0].points.map(p=>p.lb)).toEqual(original[0].points.map(p=>p.lb));
 await page.locator('#dt-undo').click();expect(await rows(page)).toHaveLength(0);await page.locator('#dt-redo').click();expect((await rows(page))[0].points.map(p=>p.lb)).toEqual(original[0].points.map(p=>p.lb));
});
test('replay disables server writes and never uploads its temporary drawings',async({page})=>{
 await page.addInitScript(()=>localStorage.setItem('trx_draw_sync_token','test-token'));const writes=[];
 await page.route('**/api/drawings',route=>{if(route.request().method()==='PUT'){writes.push(route.request().postDataJSON());return route.fulfill({json:{revision:writes.length,ok:true}});}return route.fulfill({json:{revision:0,drawings:[]}});});
 await ready(page);await shape(page);await page.evaluate(()=>TRXDraw.pushServer());const original=await rows(page);await practice(page);const count=writes.length;await shape(page);
 await page.evaluate(()=>TRXDraw.pushServer());expect(writes).toHaveLength(count);await expect(page.getByRole('button',{name:'SYNC',exact:true})).toBeDisabled();await expect(page.getByRole('button',{name:'IMPORT',exact:true})).toBeDisabled();
 await page.locator('#replay-live').click();await page.evaluate(()=>TRXDraw.pushServer());expect(writes.at(-1).drawings).toEqual(original);
});
test('journal refuses to score a skipped next issue',async({page})=>{
 await ready(page);await page.locator('#study-toggle').click();await page.locator('#journal-toggle').click();await page.locator('#journal-note').fill('Before a gap');await page.locator('#journal-save').click();
 await page.evaluate(()=>TRXChart.appendLatest({issue:'20260913000000362',number:8,type:'BIG',block_time:'2026-09-13 14:01:00'}));await expect(page.locator('.journal-entry')).toContainText('Missing next round');await expect(page.locator('#journal-summary')).toContainText('0 settled');
});
test('saved automatic Fibonacci preset reorients a new drawing with reversed anchor order',async({page})=>{
 await ready(page);await page.getByLabel('New Fibonacci mode').selectOption('up');await shape(page,'fib');await page.locator('#dt-list').click();page.once('dialog',d=>d.accept('Up retracement'));await page.locator('#dt-preset-save').click();await page.locator('#dt-list-close').click();await page.locator('#dt-clear').click();await page.getByLabel('New Fibonacci mode').selectOption('manual');
 await page.locator('[data-tool="fib"]').click();await page.locator('#tv-chart').scrollIntoViewIfNeeded();const b=await page.locator('#tv-chart').boundingBox();await page.mouse.click(b.x+b.width*.25,b.y+b.height*.55);await page.mouse.click(b.x+b.width*.59,b.y+b.height*.8);await expect.poll(async()=>(await dbg(page)).count).toBe(1);const d=(await rows(page))[0];expect(d.fibMode).toBe('up');expect(d.fibReverse).toBe(d.points[0].p<d.points[1].p);
});
