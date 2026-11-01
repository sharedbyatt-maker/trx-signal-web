(() => {
"use strict";
const $ = id => document.getElementById(id);
let rounds=[], tf=1, chart, candle, projected, resizeObserver, activeSnapshot=null, forecastVisible=true, sourceAgeMinutes=Infinity, firstPublication=true;
const PUBLICATION="https://raw.githubusercontent.com/sharedbyatt-maker/trx-signal-web/kronos-forecasts/";
const MAX_ROUNDS=10000;
function parseRound(r){
 if(!Array.isArray(r)||r.length<3)return null;
 const issue=String(r[0]??"");
 const number=Number(r[1]);
 const time=String(r[2]??"");
 if(!/^\d{4,}$/.test(issue)||!Number.isInteger(number)||number<0||number>9)return null;
 const mt=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(time);
 if(!mt)return null;
 const dt=new Date(Date.UTC(+mt[1],+mt[2]-1,+mt[3],+mt[4],+mt[5]));
 if(!Number.isFinite(dt.getTime())||dt.getUTCFullYear()!==+mt[1]||dt.getUTCMonth()+1!==+mt[2]||dt.getUTCDate()!==+mt[3]||dt.getUTCHours()!==+mt[4]||dt.getUTCMinutes()!==+mt[5])return null;
 if(!/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$/.test(time))return null;
 const explicit=/(Z|[+-]\d{2}:\d{2})$/.test(time);
 const minute=explicit?Math.floor((Date.parse(time)+390*60000)/60000):Math.floor(dt.getTime()/60000);
 if(!Number.isFinite(minute))return null;
 return {issue,number,time,minute};
}
function makeBars(){
 const bars=[];let level=100,lastKey=null;
 for(const r of rounds){
  const key=Math.floor(r.minute/tf);
  const open=level;level+=r.number>=5?1:-1;
  if(key!==lastKey){bars.push({bucket:key,time:bars.length+1,open,high:Math.max(open,level),low:Math.min(open,level),close:level});lastKey=key;}
  else {const b=bars[bars.length-1];b.high=Math.max(b.high,level);b.low=Math.min(b.low,level);b.close=level;}
 }
 return bars;
}
function initChart(){
 if(!window.LightweightCharts){$("historyStatus").textContent="Chart library unavailable";return;}
 chart=LightweightCharts.createChart($("kronosChart"),{width:$("kronosChart").clientWidth,height:$("kronosChart").clientHeight,layout:{background:{type:"solid",color:"#0c1c2c"},textColor:"#a7bbcd"},grid:{vertLines:{color:"#172c3e"},horzLines:{color:"#172c3e"}},rightPriceScale:{borderColor:"#304a61"},timeScale:{borderColor:"#304a61",rightOffset:12,fixLeftEdge:true},crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});
 candle=chart.addCandlestickSeries({upColor:"#04b99c",downColor:"#ee5162",wickUpColor:"#04b99c",wickDownColor:"#ee5162",borderVisible:false,priceFormat:{type:"price",precision:1,minMove:1}});
 projected=chart.addLineSeries({color:"#ae86fa",lineWidth:3,lineStyle:2,lastValueVisible:false,priceLineVisible:false});
 resizeObserver=new ResizeObserver(()=>chart.applyOptions({width:$("kronosChart").clientWidth,height:$("kronosChart").clientHeight}));resizeObserver.observe($("kronosChart"));
}
function render(){
 if(!candle)return;
 const bars=makeBars();candle.setData(bars);projected.setData([]);$("horizon").textContent="—";$("forecastStatus").textContent="Not loaded";$("snapshotInfo").textContent="No snapshot imported";$("comparison").textContent="No validated forecast loaded. Research snapshots can be compared only after their target rounds have occurred.";chart.timeScale().fitContent();
 $("issue").textContent=rounds.length?rounds[rounds.length-1].issue:"—";$("count").textContent=String(rounds.length);
}
async function load(){
 $("historyStatus").textContent="Loading existing /api/history…";
 try{
  const response=await fetch("/api/history?days=30",{cache:"no-store",headers:{Accept:"application/json"}});
  if(!response.ok)throw new Error("HTTP "+response.status);
  const json=await response.json();if(!Array.isArray(json.history))throw Error("History format unavailable");
  sourceAgeMinutes=(Date.now()-Date.parse(json.last_time_utc))/60000;
  const seen=new Set();rounds=json.history.map(parseRound).filter(Boolean).filter(r=>{if(seen.has(r.issue))return false;seen.add(r.issue);return true;}).sort((a,b)=>a.issue.length-b.issue.length||a.issue.localeCompare(b.issue)).slice(-MAX_ROUNDS);
  $("historyStatus").textContent=rounds.length?"Loaded "+rounds.length+" rounds · read-only":"No valid rounds available";
  render();
 }catch(err){$("historyStatus").textContent="History unavailable: "+err.message;rounds=[];render();}
}
async function importSnapshot(file){
 if(!file)return;
 try{
  if(file.size>150000)throw Error("Snapshot is too large");
  const snap=JSON.parse(await file.text());
  if(snap.schema!=="kronos-round-snapshot-v1"||snap.data_source!=="big-small-walk"||!["Kronos-mini","Kronos-small"].includes(snap.model)||snap.source!=="official-kronos-inference-cpu"||snap.research_only!==true)throw Error("Unsupported snapshot metadata");
  if(![1,5,15,60].includes(snap.timeframe_minutes)||snap.timeframe_minutes!==tf)throw Error("Choose the snapshot timeframe first");
  if(!Array.isArray(snap.forecast_close)||snap.forecast_close.length===0||snap.forecast_close.length>120)throw Error("Invalid forecast length");
  if(!/^\d{4,}$/.test(String(snap.origin_issue||"")))throw Error("Missing origin issue");
  const origin=rounds.findIndex(r=>r.issue===String(snap.origin_issue));if(origin===-1)throw Error("Origin issue not found in current history");
  const bars=makeBars();if(!bars.length)throw Error("History not available");
  const values=snap.forecast_close;
  if(values.some(v=>typeof v!=="number"||!Number.isFinite(v)||Math.abs(v)>1000000))throw Error("Invalid predicted value");
  const generation=Date.parse(snap.generated_at_utc);
  if(!Number.isFinite(generation)||generation>Date.now()+60000)throw Error("Invalid generation time");
  // Stable relative anchor survives a moving 10000-round viewer window.
  const originBucket=Math.floor(rounds[origin].minute/tf);
  const originBar=bars.findIndex(b=>b.bucket===originBucket);
  if(originBar<0)throw Error("Origin bar not available");
  let delta=snap.forecast_delta;
  if(!Array.isArray(delta)||delta.length!==values.length||delta.some(v=>typeof v!=="number"||!Number.isFinite(v))) {
   if(origin!==rounds.length-1)throw Error("Legacy snapshot cannot be rebased safely");
   delta=values.map(v=>v-bars[originBar].close);
  }
  if(snap.origin_bar_time_local) {
   const local=Date.parse(snap.origin_bar_time_local+"Z")/60000;
   if(Math.floor(local/tf)!==originBucket)throw Error("Origin timestamp mismatch");
  }
  const anchor=bars[originBar].close;
  // A later round in the same origin bucket changes that candle close.
  const withinOrigin=rounds.slice(origin+1).filter(r=>Math.floor(r.minute/tf)===originBucket);
  const originAnchor=anchor-withinOrigin.reduce((n,r)=>n+(r.number>=5?1:-1),0);
  const points=[{time:originBar+1,value:originAnchor}];
  let evaluated=0,error=0,persistence=0,excluded=0;
  for(let i=0;i<delta.length;i++){
   const bucket=originBucket+i+1;
   const actual=bars.find(b=>b.bucket===bucket);
   const time=actual?actual.time:bars.length+1+(bucket-bars[bars.length-1].bucket-1);
   if(time>points[points.length-1].time)points.push({time,value:originAnchor+delta[i]});
   // API local calendar is Asia/Yangon (UTC+06:30). Exclude bars already
   // started before publication and the currently incomplete source bar.
   const startUtc=(bucket*tf-390)*60000;
   if(startUtc<=generation){excluded++;continue;}
   if(actual&&bucket<bars[bars.length-1].bucket){
    evaluated++;error+=Math.abs(originAnchor+delta[i]-actual.close);
    persistence+=Math.abs(originAnchor-actual.close);
   }
  }
  projected.setData(forecastVisible?points:[]);
  activeSnapshot=snap;
  const ageMinutes=Math.max(0,(Date.now()-generation)/60000);
  const historical=origin!==rounds.length-1;
  $("horizon").textContent=values.length+" bars";
  $("forecastStatus").textContent=historical?"Historical · not latest":!Number.isFinite(sourceAgeMinutes)||sourceAgeMinutes>5||sourceAgeMinutes< -1?"Feed stale / unknown":ageMinutes>tf*2?"Stale":"Current · research";
  $("snapshotInfo").textContent=snap.model+" · origin "+snap.origin_issue+" · generated "+new Date(generation).toISOString()+" · "+Math.round(ageMinutes)+" min ago · "+tf+"m";
  $("comparison").textContent=evaluated?"Evaluated bars: "+evaluated+" · close MAE: "+(error/evaluated).toFixed(3)+" steps · persistence MAE: "+(persistence/evaluated).toFixed(3)+" steps · excluded already-started bars: "+excluded+". Continuous projection; no round win-rate claim.":"Pending: no fully completed, post-publication target bars available. Excluded already-started bars: "+excluded+". No measured accuracy yet.";

 }catch(err){activeSnapshot=null;projected?.setData([]);$("forecastStatus").textContent="Rejected";$("snapshotInfo").textContent=err.message;$("historyStatus").textContent="Snapshot rejected: "+err.message;}finally{$("snapshot").value="";}
}
document.querySelectorAll("[data-tf]").forEach(button=>button.addEventListener("click",()=>{firstPublication=false;tf=Number(button.dataset.tf);document.querySelectorAll("[data-tf]").forEach(x=>x.classList.toggle("chosen",x===button));render();autoSnapshot();}));
$("reload").addEventListener("click",()=>load().then(autoSnapshot));
$("forecastToggle").addEventListener("click",()=>{forecastVisible=!forecastVisible;$("forecastToggle").textContent="Forecast "+(forecastVisible?"ON":"OFF");if(!forecastVisible)projected.setData([]);else if(activeSnapshot)importSnapshot({size:0,text:async()=>JSON.stringify(activeSnapshot)});});
$("forecastHistory").addEventListener("change",async event=>{const path=event.target.value;if(!/^forecasts\/[a-zA-Z0-9-]+\.json$/.test(path))return;try{const r=await fetch(PUBLICATION+path,{cache:"no-store"});if(!r.ok)throw Error("HTTP "+r.status);await importSnapshot({size:0,text:()=>r.text()});}catch(e){$("snapshotInfo").textContent=e.message;}});$("snapshot").addEventListener("change",event=>importSnapshot(event.target.files?.[0]));
async function autoSnapshot(){
 activeSnapshot=null;
 try{
  const response=await fetch(PUBLICATION+"index.json",{cache:"no-store"});
  if(!response.ok)throw Error("No published forecast manifest (HTTP "+response.status+")");
  const manifest=await response.json();
  if(manifest.schema!=="kronos-index-v1"||!Array.isArray(manifest.forecasts))throw Error("Invalid manifest");
  if(firstPublication){
   firstPublication=false;
   const available=manifest.forecasts.find(x=>[1,5,15,60].includes(x.timeframe));
   if(available&&!manifest.forecasts.some(x=>x.timeframe===tf)){
    tf=available.timeframe;
    document.querySelectorAll("[data-tf]").forEach(x=>x.classList.toggle("chosen",Number(x.dataset.tf)===tf));
    render();
   }
  }
  const entries=manifest.forecasts.filter(x=>x.timeframe===tf&&/^forecasts\/[a-zA-Z0-9-]+\.json$/.test(x.file)).slice(0,60);
  $("forecastHistory").replaceChildren();
  for(const item of entries){const option=document.createElement("option");option.value=item.file;option.textContent=item.origin_issue+" · "+item.generated_at_utc;$("forecastHistory").append(option);}
  if(!entries.length)throw Error("No model output published for "+tf+"m yet");
  const res=await fetch(PUBLICATION+entries[0].file,{cache:"no-store"});
  if(!res.ok)throw Error("Forecast download HTTP "+res.status);
  await importSnapshot({size:0,text:()=>res.text()});
  try{const status=await fetch(PUBLICATION+"status.json",{cache:"no-store"});if(status.ok){const info=await status.json();if(info.status==="failed")$("snapshotInfo").textContent+=" · Last inference failed: "+info.reason;}}catch(_err){/* last successful snapshot remains available */}
 }catch(err){$("forecastStatus").textContent="Unavailable";$("snapshotInfo").textContent=err.message;}
}

initChart();load().then(autoSnapshot);
})();