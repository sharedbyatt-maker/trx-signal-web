const {test,expect}=require('@playwright/test');
const fs=require('fs');
const path=require('path');
// Synthetic fixtures test UI behavior only; never published as model output.
async function openKronos(page,missing=false,badBacktest=false,bothTimeframes=false){
 const start=Math.floor(Date.now()/60000)*60000-200*60000;
 const history=Array.from({length:200},(_,i)=>[String(100000+i),i%10,new Date(start+i*60000+390*60000).toISOString().slice(0,19)]);
 const snapshot={schema:'kronos-round-snapshot-v1',data_source:'big-small-walk',model:'Kronos-mini',source:'official-kronos-inference-cpu',research_only:true,timeframe_minutes:1,origin_issue:history[180][0],forecast_close:[900,901],forecast_delta:[1,2],generated_at_utc:new Date(start+180*60000+1000).toISOString()};
 await page.route('**/api/history?*',route=>route.fulfill({json:{history,last_time_utc:new Date(start+199*60000).toISOString()}}));
 await page.route('https://raw.githubusercontent.com/**',route=>{
  const url=new URL(route.request().url()).pathname;
  const day={day_local:new Date(Date.now()+420*60000).toISOString().slice(0,10),timeframe:1,model:'Kronos-mini',targets:2,forecasts:['forecasts/test.json'],error:3,persistence:4,random:5,majority:6,horizons:[{horizon:1,targets:1,error:1,persistence:2,random:3,majority:4}]};
  if(url.endsWith('reports.json'))return route.fulfill({json:{schema:'kronos-daily-reports-v1',calendar:'Asia/Bangkok',updated_at_utc:new Date().toISOString(),days:bothTimeframes?[day,{...day,timeframe:5,error:10,horizons:[{horizon:1,targets:1,error:5,persistence:6,random:7,majority:8}]}]:[day]}});
  if(url.endsWith('backtest-1m.json')||(bothTimeframes&&url.endsWith('backtest.json'))){
   const tf=url.endsWith('backtest-1m.json')?1:5;
   return route.fulfill({json:{schema:'kronos-walk-forward-v1',retrospective_only:!badBacktest,timeframe:tf,model:'Kronos-mini',lookback_bars:256,generated_at_utc:new Date().toISOString(),origins:[{input_end_utc:new Date(start).toISOString(),last_target_end_utc:new Date(start+12*60000).toISOString()}],horizons:[1,3,6,12].map(horizon=>({horizon,targets:1,error:tf,persistence:2,random:3,majority:4}))}});
  }
  if(missing)return route.fulfill({status:404,body:'Not found'});
  if(url.endsWith('index.json'))return route.fulfill({json:{schema:'kronos-index-v1',forecasts:[...(bothTimeframes?[{file:'forecasts/test5.json',timeframe:5,origin_issue:snapshot.origin_issue,generated_at_utc:snapshot.generated_at_utc}]:[]),{file:'forecasts/test.json',timeframe:1,origin_issue:snapshot.origin_issue,generated_at_utc:snapshot.generated_at_utc}]}});
  return route.fulfill({json:/status-(1|5)m\.json$/.test(url)?{status:'ready'}:url.endsWith('test5.json')?{...snapshot,timeframe_minutes:5}:snapshot});
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
 await expect(page.locator('#archiveMetrics')).toContainText('evaluated target bars 2');
 await expect(page.locator('#scoredTargets')).toHaveText('2');
 await expect(page.locator('#dailySummary')).toContainText('2 scored targets');
 await expect(page.locator('#horizonRows tr')).toHaveCount(4);
 await expect(page.locator('#horizonRows tr').first()).toContainText('1.000');
 await expect(page.locator('#baselineVerdict')).toContainText('Early sample');
 await expect(page.locator('#backtestSummary')).toContainText('1 historical origins');
 await expect(page.locator('#backtestSummary')).toContainText('retrospective only');
 await expect(page.locator('#backtestRows tr')).toHaveCount(4);
 await page.locator('#reportWindow').selectOption('30');
 await expect(page.locator('#dailyRows tr')).toHaveCount(1);
 await expect(page.locator('#kronosChart canvas').first()).toBeVisible();
 await page.locator('#kronosChart').scrollIntoViewIfNeeded();
 await page.locator('#kronosChart').click({position:{x:100,y:100}});
 await expect(page.locator('#inspector')).toContainText('Historical candle');
 await expect(page.locator('#inspector')).toBeInViewport();
 await page.locator('#replay').click();
 await expect(page.locator('#comparison')).toContainText('Replay: only rounds');
 await page.locator('#replay').click();
 await expect(page.locator('#comparison')).toContainText('expected random MAE');
 await page.locator('#forecastToggle').click();
 await expect(page.locator('#forecastToggle')).toHaveText('Forecast OFF');
 await page.locator('#forecastToggle').click();
 await expect(page.locator('#forecastToggle')).toHaveText('Forecast ON');
 await page.locator('[data-tf="5"]').click();
 await expect(page.locator('#forecastStatus')).toHaveText('Unavailable');
 await expect(page.locator('#backtestSummary')).toContainText('No retrospective backtest');
 await expect(page.locator('#backtestRows tr')).toHaveCount(0);
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

test('Kronos rejects backtest data without explicit retrospective provenance',async({page})=>{
 await openKronos(page,false,true);
 await expect(page.locator('#backtestSummary')).toContainText('No retrospective backtest');
 await expect(page.locator('#backtestRows tr')).toHaveCount(0);
 await expect(page.locator('#dailySummary')).toContainText('2 scored targets');
});

test('Kronos keeps 1m and 5m model results and reports separate',async({page})=>{
 await openKronos(page,false,false,true);
 await expect(page.locator('#snapshotInfo')).toContainText('1m');
 await expect(page.locator('#nextForecast')).toContainText('1m estimate');
 await expect(page.locator('#dailySummary')).toContainText('model MAE 1.500');
 await expect(page.locator('#backtestRows tr').first()).toContainText('1.000');
 await page.locator('[data-tf="5"]').click();
 await expect(page.locator('#snapshotInfo')).toContainText('5m');
 await expect(page.locator('#dailySummary')).toContainText('model MAE 5.000');
 await expect(page.locator('#backtestRows tr').first()).toContainText('5.000');
 await page.locator('[data-tf="1"]').click();
 await expect(page.locator('#snapshotInfo')).toContainText('1m');
 await expect(page.locator('#dailySummary')).toContainText('model MAE 1.500');
 await expect(page.locator('#backtestRows tr').first()).toContainText('1.000');
});
