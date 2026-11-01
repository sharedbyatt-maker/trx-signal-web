(function(root){
'use strict';
let report=null,currentTf=1,requestId=0,reportFailed=false;
const backtests=new Map();
const backtestRequests=new Map();
const publicationURL=(base,file)=>base+file+'?v='+Math.floor(Date.now()/30000);
const fetchOptions=()=>typeof AbortSignal!=='undefined'&&AbortSignal.timeout?{cache:'no-store',signal:AbortSignal.timeout(15000)}:{cache:'no-store'};
const $=id=>document.getElementById(id);
const metricKeys=['error','persistence','random','majority'];
function appendMetrics(body,label,targets,metrics){
 const row=document.createElement('tr');
 for(const value of [label,targets,...metricKeys.map(k=>targets?(metrics[k]/targets).toFixed(3):'—')]){
  const cell=document.createElement('td');cell.textContent=String(value);row.append(cell);
 }
 body.append(row);
}
function renderBacktest(tf){
 const backtest=backtests.get(tf);
 $('backtestRows').replaceChildren();$('backtestDetails').textContent='';
 if(!backtest||backtest.timeframe!==tf){$('backtestSummary').textContent='No retrospective backtest available for this timeframe. Scheduled research covers 1m and 5m.';return;}
 for(const entry of backtest.horizons)appendMetrics($('backtestRows'),entry.horizon,entry.targets,entry);
 const origins=backtest.origins;
 $('backtestSummary').textContent=`${origins.length} historical origins · ${backtest.lookback_bars} input bars each · retrospective only · sample too small to establish predictive value.`;
 $('backtestDetails').textContent='Computed '+backtest.generated_at_utc+' · bounded to 8 origins per run · non-overlapping target windows. '+(origins.length?'Input cutoffs '+origins[0].input_end_utc+' to '+origins[origins.length-1].input_end_utc+'.':'Not enough complete source history yet.');
}
function summary(evaluated,pending,generated){
 $('scoredTargets').textContent=String(evaluated);
 $('pendingTargets').textContent=String(pending);
 const schedule=root.KronosResearch.publicationSchedule(currentTf,generated);
 $('nextForecast').textContent=schedule?(schedule.overdue?'နောက်ကျနေသည် · ':'')+new Date(schedule.expected+420*60000).toISOString().slice(11,16)+' Bangkok · '+currentTf+'m estimate':'ဒီ timeframe အတွက် auto schedule မရှိပါ';
 $('publicationStatus').textContent=schedule?.overdue?'Forecast အသစ် မရောက်သေးပါ။ အောက်ကအချိန်က စီစဉ်ထားသည့်အချိန်သာဖြစ်ပြီး timer အလုပ်လုပ်ကြောင်း အတည်ပြုချက် မဟုတ်ပါ။':'အချိန်သည် ခန့်မှန်းသာဖြစ်သည်။ Refresh က ရှိပြီးသား forecast ကိုသာ ပြန်ယူပြီး model ကို မမောင်းပါ။';
 $('forecastAge').textContent=Math.max(0,Math.floor((Date.now()-Date.parse(generated))/60000))+' min ago';
}
function renderReport(tf){
 currentTf=tf;
 renderBacktest(tf);
 const days=Number($('reportWindow').value)||7;
 const today=new Date(Date.now()+420*60000).toISOString().slice(0,10);
 const cutoff=new Date(Date.now()+420*60000-(days-1)*86400000).toISOString().slice(0,10);
 $('dailyRows').replaceChildren();
 $('horizonRows').replaceChildren();$('baselineVerdict').textContent='Measured horizon comparisons unavailable.';
 $('reportUpdated').textContent='';
 if(!report){$('reportSimple').textContent='Report မရသေးပါ။ Forecast ရလဒ်အသစ်တွေ publish ပြီးမှ ပြနိုင်ပါမယ်။';$('dailySummary').textContent='Performance report unavailable; waiting for the next successful publication.';return;}
 const entries=report.days.filter(x=>x.timeframe===tf&&x.day_local>=cutoff&&x.day_local<=today);
 const totals={targets:0,error:0,persistence:0,random:0,majority:0};const forecasts=new Set();
 for(const entry of entries){
  for(const key of Object.keys(totals))totals[key]+=entry[key];
  entry.forecasts.forEach(x=>forecasts.add(x));
  const row=document.createElement('tr');
  for(const value of [entry.day_local,entry.model,entry.targets,(entry.error/entry.targets).toFixed(3),(entry.persistence/entry.targets).toFixed(3),(entry.random/entry.targets).toFixed(3),(entry.majority/entry.targets).toFixed(3)]){
   const cell=document.createElement('td');cell.textContent=String(value);row.append(cell);
  }
  $('dailyRows').append(row);
 }
 $('dailySummary').textContent=totals.targets?`${forecasts.size} forecasts · ${totals.targets} scored targets · model MAE ${(totals.error/totals.targets).toFixed(3)} · persistence ${(totals.persistence/totals.targets).toFixed(3)} · expected random ${(totals.random/totals.targets).toFixed(3)} · past-majority ${(totals.majority/totals.targets).toFixed(3)}.`:'No completed targets in this window yet.';
 $('reportSimple').textContent=totals.targets?`${tf}m · ရွေးထားသော ${days} ရက်အတွင်း forecast ${forecasts.size} ခုရဲ့ target ${totals.targets} ခုကို စစ်ထားပါတယ်။ ပျမ်းမျှ ${(totals.error/totals.targets).toFixed(3)} steps လွဲပါတယ်။ မပြောင်းဘူးလို့ယူဆတဲ့ နည်းက ${(totals.persistence/totals.targets).toFixed(3)} steps လွဲပါတယ်။ `+(totals.error<totals.persistence?'ဒီ sample မှာ Kronos ရဲ့ ပျမ်းမျှလွဲချက် ပိုနည်းပါတယ်။':totals.error>totals.persistence?'ဒီ sample မှာ ရိုးရိုးမပြောင်းဘူးလို့ယူဆတဲ့နည်းထက် Kronos ပိုလွဲပါတယ်။':'ဒီ sample မှာ ပျမ်းမျှလွဲချက် တူနေပါတယ်။')+' ဒါက အနိုင်ရာခိုင်နှုန်း မဟုတ်ပါ။':`${tf}m · ဒီကာလအတွက် publish လုပ်ပြီးသော report ထဲမှာ စစ်ပြီး target မရှိသေးပါ။ အပေါ်က ရလဒ်သည် လတ်တလော round data နဲ့ တွက်ထားလို့ ပိုသစ်နိုင်ပါတယ်။`;
 for(const horizon of [1,3,6,12]){
  const selected=entries.flatMap(x=>x.horizons||[]).filter(x=>x.horizon===horizon);
  const aggregate={targets:0,error:0,persistence:0,random:0,majority:0};
  for(const point of selected)for(const key of Object.keys(aggregate))aggregate[key]+=point[key];
  appendMetrics($('horizonRows'),horizon,aggregate.targets,aggregate);
 }
 if(totals.targets){
  const measuredDays=new Set(entries.map(x=>x.day_local)).size;
  const gaps=['persistence','random','majority'].map(k=>`${k} ${((totals[k]-totals.error)/totals.targets).toFixed(3)}`).join(' · ');
  const early=forecasts.size<30||measuredDays<3;
  $('baselineVerdict').textContent=(early?'Data မလုံလောက်သေးပါ။ Early sample: ':'Descriptive comparison only: ')+`${forecasts.size} forecasts across ${measuredDays} Bangkok days. Baseline MAE minus model MAE: ${gaps}. Positive = model lower error; negative = baseline lower error. `+(early?'At least 30 forecasts and 3 days are required to leave the early-sample label; this is a display rule, not statistical proof. ':'Overlapping targets remain correlated; these differences do not establish predictive value.');
 }
 const age=Math.max(0,Math.floor((Date.now()-Date.parse(report.updated_at_utc))/60000));
 if(age>15||reportFailed)$('reportSimple').textContent+=' Report update နောက်ကျနေပါတယ်။ နောက်ဆုံးအောင်မြင်ခဲ့သော စာရင်းကိုသာ ပြထားပါတယ်။';
 $('reportUpdated').textContent='Bangkok calendar · last measured '+report.updated_at_utc+' · '+age+' min ago · five-minute publication schedule, may be delayed · overlapping targets are correlated.'+(age>15?' Report delayed; this is the last successful measurement.':'');
}
async function loadReport(base,tf){
 currentTf=tf;
 const id=++requestId;
 try{
  const response=await fetch(publicationURL(base,'reports.json'),fetchOptions());
  if(!response.ok)throw Error('Report unavailable');
  const data=await response.json();
  if(data.calendar!=='Asia/Bangkok'||data.schema!=='kronos-daily-reports-v1'||!Array.isArray(data.days)||!Number.isFinite(Date.parse(data.updated_at_utc)))throw Error('Invalid report');
  for(const day of data.days){
   if(!/^\d{4}-\d{2}-\d{2}$/.test(day.day_local)||!Array.isArray(day.forecasts)||!Number.isInteger(day.targets)||day.targets<=0||!['error','persistence','random','majority'].every(k=>Number.isFinite(day[k])&&day[k]>=0))throw Error('Invalid daily metrics');
   if(day.horizons!==undefined&&(!Array.isArray(day.horizons)||!day.horizons.every(x=>[1,3,6,12].includes(x.horizon)&&Number.isInteger(x.targets)&&x.targets>0&&metricKeys.every(k=>Number.isFinite(x[k])&&x[k]>=0))))throw Error('Invalid horizon metrics');
  }
  if(id!==requestId)return;
  report=data;reportFailed=false;
 }catch(_error){if(id!==requestId)return;reportFailed=true;}
 renderReport(currentTf);
}
async function loadBacktest(base,tf=currentTf){
 if(![1,5].includes(tf)){renderBacktest(currentTf);return;}
 const id=(backtestRequests.get(tf)||0)+1;backtestRequests.set(tf,id);
 try{
  const response=await fetch(publicationURL(base,tf===1?'backtest-1m.json':'backtest.json'),fetchOptions());
  if(!response.ok)throw Error('Unavailable');
  const data=await response.json();
  if(data.timeframe!==tf||data.schema!=='kronos-walk-forward-v1'||data.retrospective_only!==true||!Number.isFinite(Date.parse(data.generated_at_utc))||!Array.isArray(data.origins)||data.origins.length>8||!Array.isArray(data.horizons)||data.horizons.length!==4||!data.horizons.every((x,i)=>x.horizon===[1,3,6,12][i]&&x.targets===data.origins.length&&metricKeys.every(k=>Number.isFinite(x[k])&&x[k]>=0)))throw Error('Invalid backtest');
  if(!data.origins.every(x=>Number.isFinite(Date.parse(x.input_end_utc))&&Number.isFinite(Date.parse(x.last_target_end_utc))))throw Error('Invalid cutoffs');
  if(backtestRequests.get(tf)!==id)return;
  backtests.set(tf,data);
 }catch(_error){if(backtestRequests.get(tf)!==id)return;backtests.delete(tf);}
 renderBacktest(currentTf);
}
root.KronosDashboard={summary,loadReport,loadBacktest,renderReport,publicationURL};
})(window);
