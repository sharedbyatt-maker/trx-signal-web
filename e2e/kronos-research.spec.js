const {test,expect}=require('@playwright/test');
const fs=require('fs');
const path=require('path');
// Synthetic fixtures test UI behavior only; never published as model output.
async function openKronos(page,missing=false){
 const start=Math.floor(Date.now()/60000)*60000-200*60000;
 const history=Array.from({length:200},(_,i)=>[String(100000+i),i%10,new Date(start+i*60000+390*60000).toISOString().slice(0,19)]);
 const snapshot={schema:'kronos-round-snapshot-v1',data_source:'big-small-walk',model:'Kronos-mini',source:'official-kronos-inference-cpu',research_only:true,timeframe_minutes:1,origin_issue:history[180][0],forecast_close:[900,901],forecast_delta:[1,2],generated_at_utc:new Date(start+180*60000+1000).toISOString()};
 await page.route('**/api/history?*',route=>route.fulfill({json:{history,last_time_utc:new Date(start+199*60000).toISOString()}}));
 await page.route('https://raw.githubusercontent.com/**',route=>{
  const url=route.request().url();
  if(missing)return route.fulfill({status:404,body:'Not found'});
  if(url.endsWith('index.json'))return route.fulfill({json:{schema:'kronos-index-v1',forecasts:[{file:'forecasts/test.json',timeframe:1,origin_issue:snapshot.origin_issue,generated_at_utc:snapshot.generated_at_utc}]}});
  return route.fulfill({json:url.endsWith('status.json')?{status:'ready'}:snapshot});
 });
 const html=fs.readFileSync(path.join(__dirname,'../templates/kronos.html'),'utf8').replace(/\{\{ url_for\('static', filename='([^']+)'\) \}\}/g,'/static/$1');
 await page.route('**/kronos',route=>route.fulfill({contentType:'text/html',body:html}));
 await page.goto('/kronos');
}
test('Kronos loads historical comparisons and working forecast controls',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await openKronos(page);
 await expect(page.locator('#forecastStatus')).toContainText('Historical');
 await expect(page.locator('#comparison')).toContainText('Evaluated bars: 2');
 await expect(page.locator('#kronosChart canvas').first()).toBeVisible();
 await page.locator('#forecastToggle').click();
 await expect(page.locator('#forecastToggle')).toHaveText('Forecast OFF');
 await page.locator('#forecastToggle').click();
 await expect(page.locator('#forecastToggle')).toHaveText('Forecast ON');
 await page.locator('[data-tf="5"]').click();
 await expect(page.locator('#forecastStatus')).toHaveText('Unavailable');
 await expect(page.locator('#snapshotInfo')).toContainText('No model output published for 5m');
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
 expect(overflow).toBe(false);
 expect(errors).toEqual([]);
});
test('Kronos missing publication shows an honest unavailable state',async({page})=>{
 await openKronos(page,true);
 await expect(page.locator('#count')).toHaveText('200');
 await expect(page.locator('#forecastStatus')).toHaveText('Unavailable');
 await expect(page.locator('#snapshotInfo')).toContainText('No published forecast manifest');
});
