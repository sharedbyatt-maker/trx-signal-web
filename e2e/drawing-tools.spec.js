const {test,expect}=require('@playwright/test');
const rows=page=>page.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3')||'[]'));
const debug=page=>page.evaluate(()=>window.TRXDraw._dbg());
async function ready(page){
  await page.addInitScript(()=>{if(!localStorage.getItem('trx_draw_v2_prefs'))localStorage.setItem('trx_draw_v2_prefs',JSON.stringify({magnet:false}));});
  await page.goto('/');
  await expect.poll(async()=> (await debug(page))?.apiReady).toBe(true);
  await page.locator('#dt-toggle-btn').click();
}
async function create(page,type,touch=false){
  await page.locator(`[data-tool="${type}"]`).click();
  const b=await page.locator('#tv-chart').boundingBox();
  const a={x:b.x+b.width*.25,y:b.y+b.height*.57};
  const z={x:b.x+b.width*.59,y:b.y+b.height*.78};
  if(touch){await page.touchscreen.tap(a.x,a.y);if(!['hline','vline'].includes(type))await page.touchscreen.tap(z.x,z.y);}
  else {await page.mouse.click(a.x,a.y);if(!['hline','vline'].includes(type))await page.mouse.click(z.x,z.y);}
  await expect.poll(async()=> (await rows(page)).length).toBe(1);
  return {a,z};
}
for(const type of ['trend','ray','hline','vline','rect','fib']){
  test(`${type}: real pointer placement, anchored timeframe changes and reload`,async({page},info)=>{
    const errors=[];page.on('pageerror',e=>errors.push(e.message));
    await ready(page);await create(page,type,info.project.name.includes('mobile'));
    const original=await rows(page);
    expect(original[0].points.every(p=>Number.isFinite(p.p)&&p.lb)).toBeTruthy();
    for(const tf of ['5','15','1']){
      await page.locator(`.tf-btn[data-g="${tf}"]`).click();
      await expect.poll(async()=> (await debug(page)).count).toBe(1);
    }
    await page.reload();await expect.poll(async()=> (await debug(page))?.apiReady).toBe(true);
    await expect.poll(async()=> (await debug(page)).count).toBe(1);
    expect((await rows(page))[0]).toEqual(original[0]);expect(errors).toEqual([]);
  });
}
test('object controls preserve selection and apply width, style, extensions, lock, hide and duplicate',async({page},info)=>{
  await ready(page);await create(page,'trend',info.project.name.includes('mobile'));
  const id=(await debug(page)).selectedId;
  await page.locator('#dt-v2-width').selectOption('4');
  await page.locator('#dt-v2-style').selectOption('dashed');
  await page.locator('#dt-v2-right').click();
  await expect.poll(async()=> (await debug(page)).selectedId).toBe(id);
  await expect.poll(async()=> (await rows(page))[0].extendRight).toBe(true);
  await page.locator('#dt-v2-left').click();
  await page.locator('#dt-v2-lock').click();
  await expect.poll(async()=> (await rows(page))[0].locked).toBe(true);
  await page.locator('#dt-v2-lock').click();
  await page.locator('[data-color="#f23645"]').click();
  expect((await rows(page))[0]).toMatchObject({width:4,style:'dashed',color:'#f23645',extendLeft:true,extendRight:true,locked:false});
  await page.locator('#dt-v2-dup').click();await expect.poll(async()=> (await rows(page)).length).toBe(2);
  await page.locator('#dt-v2-hide').click();await expect.poll(async()=> (await debug(page)).hidden).toBe(1);
  await page.locator('#dt-v2-show').click();await expect.poll(async()=> (await debug(page)).hidden).toBe(0);
  await page.locator('#dt-undo').click();await expect.poll(async()=> (await rows(page)).length).toBe(1);
});
test('two-point tools support drag placement and endpoint edits without shifting the other anchor',async({page})=>{
  await ready(page);
  for(const type of ['trend','ray','rect','fib']){
    await page.locator(`[data-tool="${type}"]`).click();
    const b=await page.locator('#tv-chart').boundingBox();
    const a={x:b.x+b.width*.25,y:b.y+b.height*.57},z={x:b.x+b.width*.59,y:b.y+b.height*.78};
    await page.mouse.move(a.x,a.y);await page.mouse.down();await page.mouse.move(z.x,z.y,{steps:12});await page.mouse.up();
    await expect.poll(async()=> (await rows(page)).length).toBe(1);
    const original=(await rows(page))[0];
    await page.mouse.move(z.x,z.y);await page.mouse.down();await page.mouse.move(z.x+15,z.y-25,{steps:8});await page.mouse.up();
    await expect.poll(async()=> (await rows(page))[0].points[1].p).not.toBe(original.points[1].p);
    expect((await rows(page))[0].points[0]).toEqual(original.points[0]);
    await page.locator('#dt-del').click();await expect.poll(async()=> (await rows(page)).length).toBe(0);
  }
});
test('Fibonacci settings remain clickable and persist every option',async({page},info)=>{
  await ready(page);await create(page,'fib',info.project.name.includes('mobile'));
  await page.locator('#dt-v2-fib').click();
  const fib=page.locator('#fib-v2-panel');await expect(fib).toBeVisible();
  await fib.getByRole('checkbox',{name:'1.618',exact:true}).check();
  await fib.getByRole('button',{name:'REVERSE',exact:true}).click();
  await fib.getByRole('button',{name:'LABEL LEFT',exact:true}).click();
  await fib.getByRole('button',{name:'EXT RIGHT',exact:true}).click();
  await fib.getByPlaceholder('custom e.g. 2.618').fill('2.618');
  await fib.getByRole('button',{name:'+ ADD',exact:true}).click();
  await fib.locator('input[type=range]').press('Home');
  for(let i=0;i<15;i++)await fib.locator('input[type=range]').press('ArrowRight');
  const before=(await rows(page))[0];
  expect(before).toMatchObject({fibReverse:true,fibLabelSide:'right',fibExtendRight:true,fibFill:.15});
  expect(before.fibLevels).toContainEqual({value:1.618,enabled:true});
  expect(before.fibLevels).toContainEqual({value:2.618,enabled:true});
  await fib.getByRole('button',{name:'DONE',exact:true}).click();await expect(fib).toBeHidden();
  await page.reload();await expect.poll(async()=> (await debug(page)).count).toBe(1);
  expect((await rows(page))[0]).toEqual(before);
});
test('drawing panel fits a narrow phone without covering its own controls',async({page},info)=>{
  test.skip(!info.project.name.includes('mobile'),'Phone geometry');
  await page.setViewportSize({width:320,height:740});await ready(page);await create(page,'fib',true);
  const geometry=await page.locator('#draw-v2-panel').evaluate(e=>{const r=e.getBoundingClientRect();return {left:r.left,right:r.right,bottom:r.bottom}});
  expect(geometry.left).toBeGreaterThanOrEqual(0);expect(geometry.right).toBeLessThanOrEqual(320);
  await page.locator('#dt-v2-fib').click();
  const intersects=await page.evaluate(()=>{const a=document.querySelector('#draw-v2-panel').getBoundingClientRect(),b=document.querySelector('#fib-v2-panel').getBoundingClientRect();return a.bottom>b.top&&a.right>b.left&&b.right>a.left;});
  expect(intersects).toBeFalsy();
});
test('pointer cancellation rolls back an unfinished edit and unlocks chart gestures',async({page})=>{
  await ready(page);const {a}=await create(page,'hline');const before=await rows(page);
  await page.locator('#tv-chart').dispatchEvent('pointerdown',{pointerId:77,button:0,clientX:a.x+30,clientY:a.y});
  await page.locator('#tv-chart').dispatchEvent('pointermove',{pointerId:77,clientX:a.x+30,clientY:a.y+45});
  await page.evaluate(()=>new Promise(requestAnimationFrame));
  await page.locator('#tv-chart').dispatchEvent('pointercancel',{pointerId:77});
  await expect.poll(async()=> (await debug(page)).dragging).toBe(false);
  // Trigger a save through a visible style change; cancelled geometry must stay original.
  await page.locator('#dt-v2-width').selectOption('3');
  expect((await rows(page))[0].points).toEqual(before[0].points);
  await expect(page.locator('#tv-chart')).not.toHaveClass(/drawing-active/);
});
test('object drag saves the final release point even when no move frame runs',async({page})=>{
  await ready(page);const {a}=await create(page,'hline');const before=await rows(page);
  await page.evaluate(({x,y})=>{
    const el=document.querySelector('#tv-chart');
    el.dispatchEvent(new PointerEvent('pointerdown',{bubbles:true,pointerId:78,button:0,clientX:x,clientY:y}));
    el.dispatchEvent(new PointerEvent('pointermove',{bubbles:true,pointerId:78,clientX:x,clientY:y+40}));
    el.dispatchEvent(new PointerEvent('pointerup',{bubbles:true,pointerId:78,clientX:x,clientY:y+40}));
  },{x:a.x+30,y:a.y});
  await expect.poll(async()=> (await rows(page))[0].points[0].p).not.toBe(before[0].points[0].p);
  const after=await rows(page);await page.reload();await expect.poll(async()=> (await debug(page)).count).toBe(1);expect(await rows(page)).toEqual(after);
});
test('export, import, invalid-file recovery, clear and keyboard undo preserve actual drawings',async({page},info)=>{
  await ready(page);await create(page,'rect',info.project.name.includes('mobile'));
  const before=await rows(page);
  const downloadPromise=page.waitForEvent('download');
  await page.getByRole('button',{name:'EXPORT',exact:true}).click();
  const download=await downloadPromise;
  const payload=JSON.parse(require('node:fs').readFileSync(await download.path(),'utf8'));
  expect(payload.drawings).toEqual(before);
  await page.locator('#dt-clear').click();await expect.poll(async()=> (await rows(page)).length).toBe(0);
  let chooserPromise=page.waitForEvent('filechooser');await page.getByRole('button',{name:'IMPORT',exact:true}).click();
  await (await chooserPromise).setFiles({name:'drawings.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(payload))});
  await expect.poll(async()=> (await debug(page)).count).toBe(1);
  expect(await rows(page)).toEqual(before);
  const invalidDialog=page.waitForEvent('dialog');
  chooserPromise=page.waitForEvent('filechooser');await page.getByRole('button',{name:'IMPORT',exact:true}).click();
  await (await chooserPromise).setFiles({name:'bad.json',mimeType:'application/json',buffer:Buffer.from('{broken')});
  await (await invalidDialog).dismiss();
  await expect.poll(async()=> (await rows(page)).length).toBe(1);
  await page.locator('.tf-btn[data-g="1"]').focus();await page.keyboard.press('Control+z');
  await expect.poll(async()=> (await rows(page)).length).toBe(0);
});
test('magnet preference and selected-object deletion survive reload',async({page},info)=>{
  await ready(page);await create(page,'hline',info.project.name.includes('mobile'));
  await page.locator('#dt-v2-mag').click();await expect.poll(async()=> (await debug(page)).magnet).toBe(true);
  await page.reload();await expect.poll(async()=> (await debug(page))?.apiReady).toBe(true);
  await expect.poll(async()=> (await debug(page)).magnet).toBe(true);
  await page.locator('#dt-toggle-btn').click();await page.locator('[data-tool="vline"]').click();
  const b=await page.locator('#tv-chart').boundingBox();
  if(info.project.name.includes('mobile'))await page.touchscreen.tap(b.x+b.width*.45,b.y+b.height*.6);
  else await page.mouse.click(b.x+b.width*.45,b.y+b.height*.6);
  await expect.poll(async()=> (await rows(page)).length).toBe(2);
  await page.locator('#dt-del').click();await expect.poll(async()=> (await rows(page)).length).toBe(1);
});
test('server conflict merge, server backup, local safety backup and auth loss keep drawings safe',async({page},info)=>{
  await page.addInitScript(()=>localStorage.setItem('trx_draw_sync_token','local-test-only'));
  let remote=[],revision=0,conflict=false,denied=false,backup=[];
  await page.route('**/api/drawings',async route=>{
    if(denied)return route.fulfill({status:401,json:{error:'unauthorized'}});
    if(route.request().method()==='GET')return route.fulfill({json:{ok:true,revision,drawings:remote}});
    if(conflict)return route.fulfill({status:409,json:{error:'conflict',revision}});
    remote=route.request().postDataJSON().drawings;revision++;
    return route.fulfill({json:{ok:true,revision}});
  });
  await page.route('**/api/drawings/backups',route=>route.fulfill({json:{backups:[{revision:1,count:1,updated_at:'test'}]}}));
  await page.route('**/api/drawings/restore',route=>{remote=backup;revision++;return route.fulfill({json:{ok:true,revision,drawings:remote}});});
  await ready(page);await expect.poll(async()=> (await debug(page)).serverRevision).toBe(0);
  await create(page,'hline',info.project.name.includes('mobile'));
  await page.evaluate(()=>window.TRXDraw.pushServer());backup=JSON.parse(JSON.stringify(remote));
  await page.locator('#dt-v2-width').selectOption('3');
  remote[0].width=4;revision++;conflict=true;
  await page.evaluate(()=>window.TRXDraw.pushServer());
  await expect.poll(async()=> (await debug(page)).serverConflict).toBe(true);
  expect((await rows(page))[0].width).toBe(3);
  conflict=false;page.once('dialog',dialog=>dialog.accept());
  await page.getByRole('button',{name:'SYNC',exact:true}).click();
  await expect.poll(async()=> (await rows(page)).length).toBe(2);
  expect((await rows(page)).map(d=>d.width).sort()).toEqual([3,4]);
  await page.evaluate(()=>window.TRXDraw.pushServer());
  page.once('dialog',dialog=>dialog.accept());await page.getByRole('button',{name:'LOCAL BKP',exact:true}).click();
  await expect.poll(async()=> (await rows(page)).length).toBe(1);
  expect((await rows(page))[0].width).toBe(3);
  page.once('dialog',dialog=>dialog.accept('1'));await page.getByRole('button',{name:'BACKUPS',exact:true}).click();
  await expect.poll(async()=> (await rows(page))[0].width).toBe(2);
  const before=await rows(page);denied=true;
  await page.getByRole('button',{name:'SYNC',exact:true}).click();
  await expect.poll(async()=>page.evaluate(()=>localStorage.getItem('trx_draw_sync_token'))).toBe(null);
  expect(await rows(page)).toEqual(before);
});
