const {test,expect}=require('@playwright/test');
const rows=page=>page.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3')||'[]'));
const debug=page=>page.evaluate(()=>window.TRXDraw._dbg());
async function ready(page){
  await page.addInitScript(()=>localStorage.setItem('trx_draw_v2_prefs',JSON.stringify({magnet:false})));
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
  await fib.locator('input[type=range]').fill('0.15');
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
