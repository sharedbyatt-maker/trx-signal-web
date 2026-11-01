/* Exact baseline expectation for a symmetric +/-1 walk, not invented samples. */
(function(root){
'use strict';
function randomAbsoluteError(roundCount,actualDelta){
 if(!Number.isInteger(roundCount)||roundCount<0||roundCount>10000||!Number.isFinite(actualDelta))throw Error('Invalid random baseline input');
 if(roundCount===0)return Math.abs(actualDelta);
 // Normalize relative binomial weights from their mode to avoid underflow.
 const mode=Math.floor(roundCount/2);let total=1,error=Math.abs(2*mode-roundCount-actualDelta),weight=1;
 for(let k=mode;k<roundCount;k++){weight*=((roundCount-k)/(k+1));total+=weight;error+=weight*Math.abs(2*(k+1)-roundCount-actualDelta);}
 weight=1;
 for(let k=mode;k>0;k--){weight*=k/(roundCount-k+1);total+=weight;error+=weight*Math.abs(2*(k-1)-roundCount-actualDelta);}
 return error/total;
}
// This is a configured opportunity to run, never evidence of a scheduled run.
// Anchor to the last publication instead of moving an overdue time forward.
function publicationSchedule(tf,generated,now=Date.now()){
 if(![1,5].includes(tf))return null;
 const time=Date.parse(generated);
 if(!Number.isFinite(time))return null;
 const earliest=time+(tf===5?55:0)*60000;
 const expected=(Math.floor((earliest-120000)/300000)+1)*300000+120000;
 return {expected,overdue:now>expected+120000};
}
function forecastCandles(snapshot,points,anchor){
 if(snapshot.forecast_ohlc===undefined)return {candles:[],reason:'legacy'};
 const rows=snapshot.forecast_ohlc;
 const keys=['open','high','low','close'];
 if(!Array.isArray(rows)||rows.length!==points.length-1||!Number.isFinite(snapshot.origin_close)||!Array.isArray(snapshot.forecast_close)||snapshot.forecast_close.length!==rows.length)return {candles:[],reason:'invalid'};
 const candles=[],series=[];
 for(let i=0;i<rows.length;i++){
  const row=rows[i];
  const absent={time:points[i+1].time};
  if(!row||!keys.every(k=>typeof row[k]==='number'&&Number.isFinite(row[k])&&Math.abs(row[k])<=1000000)||row.high<Math.max(row.open,row.close)||row.low>Math.min(row.open,row.close)||row.high<row.low){series.push(absent);continue;}
  if(!Number.isFinite(snapshot.forecast_close[i])||Math.abs(row.close-snapshot.forecast_close[i])>0.00011){series.push(absent);continue;}
  const bar={time:points[i+1].time};
  for(const key of keys)bar[key]=anchor+row[key]-snapshot.origin_close;
  if(!keys.every(k=>Number.isFinite(bar[k])&&Math.abs(bar[k])<=1000000)||Math.abs(bar.close-points[i+1].value)>0.00011){series.push(absent);continue;}
  candles.push(bar);series.push(bar);
 }
 return {candles,series,missing:rows.length-candles.length,reason:candles.length===rows.length?null:candles.length?'partial':'invalid'};
}
const api={randomAbsoluteError,publicationSchedule,forecastCandles};
if(typeof module!=='undefined'&&module.exports)module.exports=api;else root.KronosResearch=api;
})(typeof window!=='undefined'?window:this);
