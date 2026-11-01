(function(root){
'use strict';
let report=null,currentTf=1,requestId=0;
const $=id=>document.getElementById(id);
function summary(evaluated,pending,generated){
 $('scoredTargets').textContent=String(evaluated);
 $('pendingTargets').textContent=String(pending);
 const next=new Date();next.setUTCMinutes(17,0,0);if(next.getTime()<=Date.now())next.setUTCHours(next.getUTCHours()+1);
 $('nextForecast').textContent=new Date(next.getTime()+420*60000).toISOString().slice(11,16)+' Bangkok · 5m schedule';
 $('forecastAge').textContent=Math.max(0,Math.floor((Date.now()-Date.parse(generated))/60000))+' min ago';
}
function renderReport(tf){
 currentTf=tf;
 const days=Number($('reportWindow').value)||7;
 const today=new Date(Date.now()+420*60000).toISOString().slice(0,10);
 const cutoff=new Date(Date.now()+420*60000-(days-1)*86400000).toISOString().slice(0,10);
 $('dailyRows').replaceChildren();
 if(!report){$('dailySummary').textContent='Performance report unavailable; waiting for the next successful publication.';return;}
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
 $('reportUpdated').textContent='Bangkok calendar · last measured '+report.updated_at_utc+' · hourly updates · overlapping targets are correlated.';
}
async function loadReport(base,tf){
 const id=++requestId;
 try{
  const response=await fetch(base+'reports.json',{cache:'no-store'});
  if(!response.ok)throw Error('Report unavailable');
  const data=await response.json();
  if(data.calendar!=='Asia/Bangkok'||data.schema!=='kronos-daily-reports-v1'||!Array.isArray(data.days)||!Number.isFinite(Date.parse(data.updated_at_utc)))throw Error('Invalid report');
  for(const day of data.days){
   if(!/^\d{4}-\d{2}-\d{2}$/.test(day.day_local)||!Array.isArray(day.forecasts)||!Number.isInteger(day.targets)||day.targets<=0||!['error','persistence','random','majority'].every(k=>Number.isFinite(day[k])&&day[k]>=0))throw Error('Invalid daily metrics');
  }
  if(id!==requestId)return;
  report=data;
 }catch(_error){if(id!==requestId)return;report=null;}
 renderReport(currentTf);
}
root.KronosDashboard={summary,loadReport,renderReport};
})(window);
