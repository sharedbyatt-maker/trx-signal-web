const {test,expect}=require('@playwright/test');
const fs=require('fs');
const path=require('path');
// Synthetic fixtures test UI behavior only; never published as model output.
async function openKronos(page,missing=false,badBacktest=false,bothTimeframes=false,variant="history"){
 const start=Math.floor(Date.now()/60000)*60000-200*60000;
 const history=Array.from({length:200},(_,i)=>[String(100000+i),i%10,new Date(start+i*60000+390*60000).toISOString().slice(0,19)]);
 const origin=variant==="pending"?199:180;
 const snapshot={schema:'kronos-round-snapshot-v1',data_source:'big-small-walk',model:'Kronos-mini',source:'official-kronos-inference-cpu',research_only:true,timeframe_minutes:1,origin_issue:history[origin][0],forecast_close:[900,901],forecast_delta:variant==="exact"?[-1,-2]:[1,2],generated_at_utc:new Date(start+(variant==="excluded"?190:origin)*60000+1000).toISOString()};
 if(['candles','partial-candles','invalid-candles'].includes(variant)){
  snapshot.origin_close=100;snapshot.forecast_close=[101,102];
  snapshot.forecast_ohlc=[{open:100,high:variant==='candles'?103:99,low:99,close:101},{open:101,high:variant==='invalid-candles'?100:104,low:100,close:102}];
 }
 const older={...snapshot,origin_issue:history[170][0],generated_at_utc:new Date(start+170*60000+1000).toISOString()};
 if(variant==='gap')history.splice(181,1);
 await page.route('**/api/history?*',route=>route.fulfill({json:{history,last_time_utc:new Date(start+199*60000).toISOString()}}));
 await page.route('https://raw.githubusercontent.com/**',route=>{
  const url=new URL(route.request().url()).pathname;
  const day={day_local:new Date(Date.now()+420*60000).toISOString().slice(0,10),timeframe:1,model:'Kronos-mini',targets:2,forecasts:['forecasts/test.json'],error:3,persistence:4,random:5,majority:6,horizons:[{horizon:1,targets:1,error:1,persistence:2,random:3,majority:4}]};
  if(url.endsWith('reports.json'))return route.fulfill({json:{schema:'kronos-daily-reports-v1',calendar:'Asia/Bangkok',updated_at_utc:new Date().toISOString(),days:variant==="pending"||variant==="excluded"?[]:bothTimeframes?[day,{...day,timeframe:5,error:10,horizons:[{horizon:1,targets:1,error:5,persistence:6,random:7,majority:8}]}]:[day]}});
  if(url.endsWith('backtest-1m.json')||(bothTimeframes&&url.endsWith('backtest.json'))){
   const tf=url.endsWith('backtest-1m.json')?1:5;
   return route.fulfill({json:{schema:'kronos-walk-forward-v1',retrospective_only:!badBacktest,timeframe:tf,model:'Kronos-mini',lookback_bars:256,generated_at_utc:new Date().toISOString(),origins:[{input_end_utc:new Date(start).toISOString(),last_target_end_utc:new Date(start+12*60000).toISOString()}],horizons:[1,3,6,12].map(horizon=>({horizon,targets:1,error:tf,persistence:2,random:3,majority:4}))}});
  }
  if(missing)return route.fulfill({status:404,body:'Not found'});
  if(url.endsWith('index.json'))return route.fulfill({json:{schema:'kronos-index-v1',forecasts:[...(bothTimeframes?[{file:'forecasts/test5.json',timeframe:5,origin_issue:snapshot.origin_issue,generated_at_utc:snapshot.generated_at_utc}]:[]),{file:'forecasts/test.json',timeframe:1,origin_issue:snapshot.origin_issue,generated_at_utc:snapshot.generated_at_utc},...(variant==='archive'?[{file:'forecasts/older.json',timeframe:1,origin_issue:older.origin_issue,generated_at_utc:older.generated_at_utc}]:[])]}});
  if(url.endsWith('older.json'))return route.fulfill({json:older});
  return route.fulfill({json:/status-(1|5)m\.json$/.test(url)?{status:'ready'}:url.endsWith('test5.json')?{...snapshot,timeframe_minutes:5}:snapshot});
 });
 const html=fs.readFileSync(path.join(__dirname,'../templates/kronos.html'),'utf8').replace(/\{\{ url_for\('static', filename='([^']+)'\) \}\}/g,'/static/$1');
 await page.route('**/kronos',route=>route.fulfill({contentType:'text/html',body:html}));
 await page.goto('/kronos');
 return {snapshot,history};
}
test('Kronos loads historical comparisons and working forecast controls',async({page})=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await openKronos(page);
 await expect(page.locator('#forecastStatus')).toContainText('Historical');
 await expect(page.locator('#comparison')).toContainText('Evaluated bars: 2');
 await expect(page.locator('#archiveMetrics')).toContainText('evaluated target bars 2');
 await expect(page.locator('#scoredTargets')).toHaveText('2');
 await expect(page.locator('#easyTitle')).toContainText('1m');
 await expect(page.locator('#easyActual')).toContainText('↓ ကျ 2');
 await expect(page.locator('#easyVerdict')).toContainText('ဦးတည်ချက် မကိုက်');
 await page.locator('.easy-list summary').click();
 await expect(page.locator('#easyRows li')).toHaveCount(2);
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
 await expect(page.locator('#easyActual')).toContainText('ဖုံးထား');
 await expect(page.locator('#easyRows')).not.toContainText('↓ ကျ 2');
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
 await expect(page.locator('#easyState')).toContainText('forecast မရသေး');
 await expect(page.locator('#easyRows li')).toHaveCount(0);
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

for(const variant of ['pending','excluded','exact'])test('Kronos explains '+variant+' results without invented wins',async({page})=>{
 await openKronos(page,false,false,false,variant);
 await expect(page.locator('#easyTitle')).toContainText('1m');
 if(variant==='pending'){
  await expect(page.locator('#easyActual')).toContainText('စောင့်နေဆဲ');
  await expect(page.locator('#easyVerdict')).toContainText('မစစ်ရသေး');
  await expect(page.locator('#easyCount')).toContainText('စစ်ပြီး 0 ခု');
 }else if(variant==='excluded'){
  await expect(page.locator('#easyActual')).toContainText('ရလဒ်ထဲ မထည့်');
  await expect(page.locator('#easyCount')).toContainText('မပါဝင် 2 ခု');
 }else{
  await expect(page.locator('#easyVerdict')).toContainText('အတိအကျကိုက်');
  await expect(page.locator('#easyVerdict')).toContainText('0 steps');
 }
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
});

test('Kronos preserves an archived forecast and replay through history refresh',async({page})=>{
 await openKronos(page,false,false,false,'archive');
 await expect(page.locator('#snapshotInfo')).toContainText('origin 100180');
 await page.locator('#forecastHistory').selectOption('forecasts/older.json');
 await expect(page.locator('#snapshotInfo')).toContainText('origin 100170');
 await page.locator('#reload').click();
 await expect(page.locator('#snapshotInfo')).toContainText('origin 100170');
 await expect(page.locator('#forecastHistory')).toHaveValue('forecasts/older.json');
 await page.locator('#replay').click();
 await page.locator('#reload').click();
 await expect(page.locator('#easyActual')).toContainText('ဖုံးထား');
 await expect(page.locator('#scoredTargets')).toHaveText('—');
 await page.locator('#latestForecast').click();
 await expect(page.locator('#snapshotInfo')).toContainText('origin 100180');
 await expect(page.locator('#easyActual')).not.toContainText('ဖုံးထား');
 await expect(page.locator('#nextForecast')).toContainText('နောက်ကျနေသည်');
});

test('Kronos ignores a delayed snapshot from the previous timeframe',async({page})=>{
 const {snapshot}=await openKronos(page,false,false,true);
 await expect(page.locator('#snapshotInfo')).toContainText('1m');
 let release,entered=false,finished;
 const gate=new Promise(resolve=>{release=resolve;});
 const done=new Promise(resolve=>{finished=resolve;});
 await page.route('**/forecasts/test5.json',async route=>{
  entered=true;await gate;
  await route.fulfill({json:{...snapshot,timeframe_minutes:5}});finished();
 });
 await page.locator('[data-tf="5"]').click();
 await expect.poll(()=>entered).toBe(true);
 await page.locator('[data-tf="1"]').click();
 await expect(page.locator('#snapshotInfo')).toContainText('1m');
 release();await done;
 await expect(page.locator('#easyTitle')).toContainText('1m');
 await expect(page.locator('#snapshotInfo')).toContainText('1m');
 await expect(page.locator('#forecastStatus')).not.toHaveText('Rejected');
});

test('Kronos clears prior forecast results when publication becomes unavailable',async({page})=>{
 await openKronos(page);
 await expect(page.locator('#scoredTargets')).toHaveText('2');
 await page.route('**/index.json*',route=>route.fulfill({status:503,body:'Unavailable'}));
 await page.locator('#reload').click();
 await expect(page.locator('#forecastStatus')).toHaveText('Unavailable');
 await expect(page.locator('#scoredTargets')).toHaveText('—');
 await expect(page.locator('#easyRows li')).toHaveCount(0);
 await expect(page.locator('#replay')).toBeDisabled();
 await expect(page.locator('#count')).toHaveText('200');
});

test('Kronos separates source gaps from outcomes that are still pending',async({page})=>{
 await openKronos(page,false,false,false,'gap');
 await expect(page.locator('#easyCount')).toContainText('data မပြည့် 2 ခု');
 await expect(page.locator('#pendingTargets')).toHaveText('0');
 await expect(page.locator('#scoredTargets')).toHaveText('0');
});

test('Kronos shows model OHLC candles and preserves line, replay and visibility controls',async({page},testInfo)=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await openKronos(page,false,false,false,'candles');
 await expect(page.locator('#predictionStyleStatus')).toContainText('ခရမ်းရောင်');
 await expect(page.getByLabel('Prediction display',{exact:true})).toHaveValue('candles');
 await expect(page.locator('#scoredTargets')).toHaveText('2');
 const comparison=await page.locator('#comparison').textContent();
 await page.getByLabel('Prediction display',{exact:true}).selectOption('line');
 await expect(page.locator('#predictionStyleStatus')).toContainText('Line =');
 await expect(page.locator('#comparison')).toHaveText(comparison);
 await page.getByLabel('Prediction display',{exact:true}).selectOption('candles');
 await page.locator('#replay').click();
 await page.locator('#reload').click();
 await expect(page.locator('#easyActual')).toContainText('ဖုံးထား');
 await expect(page.locator('#predictionStyleStatus')).toContainText('ခရမ်းရောင်');
 await page.locator('#forecastToggle').click();
 await expect(page.locator('#predictionStyleStatus')).toContainText('ဖုံးထားသည်');
 await page.locator('#forecastToggle').click();
 await expect(page.locator('#predictionStyleStatus')).toContainText('ခရမ်းရောင်');
 await page.locator('#kronosChart').scrollIntoViewIfNeeded();
 await page.locator('#kronosChart').screenshot({path:testInfo.outputPath('kronos-prediction-candles.png')});
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth+1)).toBe(false);
 expect(errors).toEqual([]);
});

test('Kronos uses the close line when raw model OHLC has invalid candle geometry',async({page})=>{
 await openKronos(page,false,false,false,'invalid-candles');
 await expect(page.locator('#predictionStyleStatus')).toContainText('စည်းမျဉ်းနှင့် မကိုက်ညီ');
 await expect(page.locator('#comparison')).toContainText('Evaluated bars: 2');
 await expect(page.locator('#forecastStatus')).not.toHaveText('Rejected');
});

test('Kronos keeps legacy close-only snapshots visible without inventing candles',async({page})=>{
 await openKronos(page);
 await expect(page.locator('#predictionStyleStatus')).toContainText('အဟောင်းမှာ Close ပဲရှိ');
 await page.getByLabel('Prediction display',{exact:true}).selectOption('line');
 await expect(page.locator('#predictionStyleStatus')).toContainText('Line =');
 await page.getByLabel('Prediction display',{exact:true}).selectOption('candles');
 await expect(page.locator('#predictionStyleStatus')).toContainText('အဟောင်းမှာ Close ပဲရှိ');
});

test('Kronos displays valid model candles and explicitly omits an invalid candle',async({page})=>{
 await openKronos(page,false,false,false,'partial-candles');
 await expect(page.locator('#predictionStyleStatus')).toContainText('1/2');
 await expect(page.locator('#predictionStyleStatus')).toContainText('ချန်ထားပါသည်');
 await expect(page.locator('#comparison')).toContainText('Evaluated bars: 2');
 await page.getByLabel('Prediction display',{exact:true}).selectOption('line');
 await expect(page.locator('#predictionStyleStatus')).toContainText('Line =');
 await page.getByLabel('Prediction display',{exact:true}).selectOption('candles');
 await expect(page.locator('#predictionStyleStatus')).toContainText('1/2');
});
