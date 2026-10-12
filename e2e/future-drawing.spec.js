const {test,expect}=require('@playwright/test');
const selected=page=>page.evaluate(()=>window.TRXDraw._dbg().selected);
async function ready(page){
  await page.goto('/');await expect.poll(()=>page.evaluate(()=>window.TRXChart?._qa.displaySnapshot().bars.length||0)).toBeGreaterThan(100);
  await page.locator('#chart-more-toggle').click();await page.locator('#chart-future-space').selectOption('100');await page.locator('#chart-more-toggle').click();
  await expect.poll(()=>page.evaluate(()=>window.TRXChart._view().to-window.TRXChart._qa.displaySnapshot().bars.length)).toBeCloseTo(100,1);
  await page.locator('#dt-toggle-btn').click();
  if(await page.locator('#chart-magnet').getAttribute('aria-pressed')==='true')await page.locator('#chart-magnet').click();
}
async function place(page,type,touch){
  await page.locator(`[data-tool="${type}"]`).click();
  const b=await page.locator('#tv-chart').boundingBox();
  // Exclude the price axis; the last third of the plot is real blank future space.
  const points=[{x:b.x+(b.width-60)*.45,y:b.y+b.height*.45},{x:b.x+(b.width-60)*.90,y:b.y+b.height*.70}];
  const tap=async p=>touch?page.touchscreen.tap(p.x,p.y):page.mouse.click(p.x,p.y);
  if(!['hline','vline'].includes(type))await tap(points[0]);await tap(points[1]);
  await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().count)).toBe(1);
  const object=await selected(page),n=await page.evaluate(()=>window.TRXChart._qa.displaySnapshot().bars.length);
  expect(object.points.at(-1).t).toBeGreaterThan(n+12);expect(object.points.at(-1).futureTime).toBeGreaterThan(0);
  return object;
}
for(const type of ['trend','ray','rect','fib','hline','vline'])test(`${type} supports endpoints well beyond the latest candle`,async({page},info)=>{
  await ready(page);const original=await place(page,type,info.project.name.includes('mobile'));
  const stored=await page.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3'))[0]);
  expect(stored.points.at(-1).futureTime).toBe(original.points.at(-1).futureTime);
  await page.reload();await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().count)).toBe(1);
  await page.locator('#chart-more-toggle').click();await expect(page.locator('#chart-future-space')).toHaveValue('100');
  expect(await page.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3'))[0])).toEqual(stored);
});
test('future trend endpoint stays fixed through new rounds and timeframe changes',async({page},info)=>{
  await ready(page);const original=await place(page,'trend',info.project.name.includes('mobile')),point=original.points[1];
  await page.evaluate(()=>{const last=window.TRXChart.studyInfo().rows.at(-1),date=new Date(last.block_time.replace(' ','T')+'Z');date.setUTCMinutes(date.getUTCMinutes()+1);window.TRXChart.appendLatest({...last,issue:String(BigInt(last.issue)+1n),number:8,type:'BIG',block_time:date.toISOString().slice(0,19).replace('T',' ')});});
  expect((await selected(page)).points[1].t).toBe(point.t);expect((await selected(page)).points[1].p).toBe(point.p);
  await page.locator('.tf-btn[data-g="5"]').click();
  const grouped=(await selected(page)).points[1],n=await page.evaluate(()=>window.TRXChart._qa.displaySnapshot().bars.length);
  expect(grouped.futureTime).toBe(point.futureTime);expect(grouped.t-n).toBeGreaterThan(0);expect(grouped.t-n).toBeLessThan(20);
  await page.locator('.tf-btn[data-g="1"]').click();expect((await selected(page)).points[1].t).toBe(point.t);
  await page.locator('#dt-undo').click();await expect.poll(()=>page.evaluate(()=>window.TRXDraw._dbg().count)).toBe(0);
  await page.locator('#dt-redo').click();expect((await page.evaluate(()=>JSON.parse(localStorage.getItem('trx_drawings_v3'))[0])).points[1].futureTime).toBe(point.futureTime);
});
test('an existing trend endpoint can be dragged into future space without moving its first anchor',async({page})=>{
  await ready(page);await page.locator('[data-tool="trend"]').click();
  const b=await page.locator('#tv-chart').boundingBox(),plot=b.width-60;
  const a={x:b.x+plot*.35,y:b.y+b.height*.45},z={x:b.x+plot*.59,y:b.y+b.height*.70};
  await page.mouse.click(a.x,a.y);await page.mouse.click(z.x,z.y);const original=await selected(page);
  await page.mouse.move(z.x,z.y);await page.mouse.down();await page.mouse.move(b.x+plot*.92,z.y-25,{steps:12});await page.mouse.up();
  const edited=await selected(page),n=await page.evaluate(()=>window.TRXChart._qa.displaySnapshot().bars.length);
  expect(edited.points[0]).toEqual(original.points[0]);expect(edited.points[1].t).toBeGreaterThan(n+12);expect(edited.points[1].futureTime).toBeGreaterThan(0);
  await expect(page.locator('#chart-follow')).toBeChecked();
});
