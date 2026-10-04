const {test,expect}=require('@playwright/test');
const rows=p=>p.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3')||'[]'));
const dbg=p=>p.evaluate(()=>TRXDraw._dbg());
const study=p=>p.evaluate(()=>{const s=TRXChart.studyInfo();return {...s,rows:s.rows.map(r=>({issue:r.issue,type:r.type})),choices:undefined};});
async function ready(page){await page.addInitScript(()=>localStorage.setItem('trx_draw_v2_prefs',JSON.stringify({magnet:false})));await page.goto('/');await expect.poll(async()=>(await dbg(page)).apiReady).toBe(true);await page.locator('#dt-toggle-btn').click();}
async function shape(page,type='hline',touch=false){await page.locator(`[data-tool="${type}"]`).click();await page.locator("#tv-chart").scrollIntoViewIfNeeded();const b=await page.locator('#tv-chart').boundingBox();const a={x:b.x+b.width*.27,y:b.y+b.height*.78},z={x:b.x+b.width*.58,y:b.y+b.height*.58};if(touch){await page.touchscreen.tap(a.x,a.y);if(type==='fib')await page.touchscreen.tap(z.x,z.y);}else{await page.mouse.click(a.x,a.y);if(type==='fib')await page.mouse.click(z.x,z.y);}await expect.poll(async()=>(await dbg(page)).count).toBe(1);return {a,z};}
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
 await ready(page);await page.locator('#dt-options').click();await page.getByLabel('New Fibonacci mode').selectOption('up');await page.locator('#dt-options-close').click();await shape(page,'fib',info.project.name.includes('mobile'));
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
test('drawing edits remain undoable after timeframe remapping',async({page},info)=>{
 await ready(page);await shape(page,'fib',info.project.name.includes('mobile'));const original=await rows(page);
 await page.locator('.tf-btn[data-g="5"]').click();await page.locator('#dt-v2-width').selectOption('4');await page.locator('#dt-undo').click();expect((await rows(page))[0].width).toBe(original[0].width);expect((await rows(page))[0].points.map(p=>p.lb)).toEqual(original[0].points.map(p=>p.lb));
 await page.locator('#dt-undo').click();expect(await rows(page)).toHaveLength(0);await page.locator('#dt-redo').click();expect((await rows(page))[0].points.map(p=>p.lb)).toEqual(original[0].points.map(p=>p.lb));
});
test('saved automatic Fibonacci preset reorients a new drawing with reversed anchor order',async({page})=>{
 await ready(page);await page.locator('#dt-options').click();await page.getByLabel('New Fibonacci mode').selectOption('up');await page.locator('#dt-options-close').click();await shape(page,'fib');await page.locator('#dt-list').click();page.once('dialog',d=>d.accept('Up retracement'));await page.locator('#dt-preset-save').click();await page.locator('#dt-list-close').click();await page.locator('#dt-options').click();await page.locator('#dt-clear').click();await page.getByLabel('New Fibonacci mode').selectOption('manual');await page.locator('#dt-options-close').click();
 await page.locator('[data-tool="fib"]').click();await page.locator('#tv-chart').scrollIntoViewIfNeeded();const b=await page.locator('#tv-chart').boundingBox();await page.mouse.click(b.x+b.width*.25,b.y+b.height*.55);await page.mouse.click(b.x+b.width*.59,b.y+b.height*.8);await expect.poll(async()=>(await dbg(page)).count).toBe(1);const d=(await rows(page))[0];expect(d.fibMode).toBe('up');expect(d.fibReverse).toBe(d.points[0].p<d.points[1].p);
});

test('compact palette preserves chart space and replaces practice with exclusive drawers',async({page},info)=>{
 await page.goto('/');await expect.poll(async()=>(await dbg(page)).apiReady).toBe(true);
 const before=await page.locator('#tv-chart').boundingBox();
 await page.locator('#dt-toggle-btn').click();const after=await page.locator('#tv-chart').boundingBox();expect(after.height).toBe(before.height);expect(after.y).toBe(before.y);
 await expect(page.locator('#study-toggle,#study-tools,#replay-controls')).toHaveCount(0);
 await page.locator('#dt-options').click();await expect(page.locator('#drawing-options')).toBeVisible();
 await page.locator('#dt-list').click();await expect(page.locator('#drawing-options')).toBeHidden();await expect(page.locator('#drawing-manager')).toBeVisible();
 await page.keyboard.press('Escape');await expect(page.locator('#drawing-manager')).toBeHidden();expect((await dbg(page)).count).toBe(0);
 if(info.project.name.includes('mobile')){await page.setViewportSize({width:320,height:740});await page.locator('#dt-options').click();const b=await page.locator('#drawing-options').boundingBox();expect(b.x).toBeGreaterThanOrEqual(0);expect(b.x+b.width).toBeLessThanOrEqual(320);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);}
 await page.locator('#dt-toggle-btn').click();await expect(page.locator('#drawing-options')).toBeHidden();
});
