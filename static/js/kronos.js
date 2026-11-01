(() => {
"use strict";
const $ = id => document.getElementById(id);
let rounds=[], tf=1, chart, candle, projected, projectedCandles, resizeObserver, activeSnapshot=null, forecastVisible=true, predictionStyle='candles', sourceAgeMinutes=Infinity, firstPublication=true, replayMode=false, lastSourceUtc=null;
const PUBLICATION="https://raw.githubusercontent.com/sharedbyatt-maker/trx-signal-web/kronos-forecasts/";
const MAX_ROUNDS=10000;
let inspectData=null,refreshing=false;
let requestVersion=0;
const selections=new Map(),snapshotCache=new Map(),publicationTimes=new Map();
const current=version=>version===requestVersion;
async function download(url){
 const options={cache:'no-store'};
 if(typeof AbortSignal!=='undefined'&&AbortSignal.timeout)options.signal=AbortSignal.timeout(15000);
 const response=await fetch(url,options);
 if(!response.ok)throw Error('HTTP '+response.status);
 return response;
}
async function snapshotFile(path){
 if(!snapshotCache.has(path)){
  const text=await (await download(PUBLICATION+path)).text();
  if(text.length>150000)throw Error('Snapshot is too large');
  snapshotCache.set(path,text);
  if(snapshotCache.size>100)snapshotCache.delete(snapshotCache.keys().next().value);
 }
 const text=snapshotCache.get(path);
 return {size:0,text:async()=>text};
}
function clearForecast(message){
 activeSnapshot=null;inspectData=null;projected?.setData([]);projectedCandles?.setData([]);
 $('predictionStyleStatus').textContent='စစ်ဆေးပြီးသော prediction မရှိသေးပါ။';
 $('replay').disabled=true;$('replay').textContent='Replay origin';
 $('horizon').textContent='—';$('comparison').textContent=message;
 for(const id of ['scoredTargets','pendingTargets','forecastAge','nextForecast'])$(id).textContent='—';
 $('inspector').textContent='No valid forecast loaded.';
}
function inspectTarget(event){
 if(!event.time||!inspectData)return;
 const predicted=inspectData.predicted.get(event.time);
 const actual=inspectData.actual.get(event.time);
 const label=new Date((event.time+420*60)*1000).toISOString().slice(0,16).replace("T"," ")+" Bangkok (UTC+07:00)";
 if(predicted===undefined){$("inspector").textContent=label+" · Historical candle · close "+(actual?actual.close.toFixed(3):"unavailable");return;}
 const eligible=event.time*1000>inspectData.generation;
 const complete=actual&&event.time<inspectData.latest;
 const visible=complete&&!replayMode&&inspectData.scorable.has(event.time);
 const ohlc=inspectData.candles.get(event.time);
 const targetEnd=new Date((event.time+tf*60+420*60)*1000).toISOString().slice(11,16);
 $("inspector").textContent=label+'–'+targetEnd+" · forecast close "+predicted.toFixed(3)+(ohlc?' · model O '+ohlc.open.toFixed(3)+' H '+ohlc.high.toFixed(3)+' L '+ohlc.low.toFixed(3)+' C '+ohlc.close.toFixed(3):'')+" · actual "+(visible?actual.close.toFixed(3):replayMode?"hidden in replay":complete?"unavailable: source gap or excluded target":"pending")+" · error "+(visible&&eligible?Math.abs(predicted-actual.close).toFixed(3):"not scored")+(!eligible?" · excluded: target started before generation":"")+" · walk steps";
}
function parseRound(r){
 if(!Array.isArray(r)||r.length<3)return null;
 const issue=String(r[0]??"");
 if(!/^[0-9]$/.test(String(r[1])))return null;
 const number=Number(r[1]);
 const time=String(r[2]??"");
 if(!/^\d{4,}$/.test(issue)||!Number.isInteger(number)||number<0||number>9)return null;
 const mt=/^(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})/.exec(time);
 if(!mt)return null;
 const dt=new Date(Date.UTC(+mt[1],+mt[2]-1,+mt[3],+mt[4],+mt[5]));
 if(!Number.isFinite(dt.getTime())||dt.getUTCFullYear()!==+mt[1]||dt.getUTCMonth()+1!==+mt[2]||dt.getUTCDate()!==+mt[3]||dt.getUTCHours()!==+mt[4]||dt.getUTCMinutes()!==+mt[5])return null;
 if(!/^\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}(:\d{2}(\.\d+)?)?(Z|[+-]\d{2}:\d{2})?$/.test(time))return null;
 const explicit=/(Z|[+-]\d{2}:\d{2})$/.test(time);
 if(!Number.isFinite(Date.parse(time.replace(" ","T")+(explicit?"":"Z"))))return null;
 const minute=explicit?Math.floor((Date.parse(time)+390*60000)/60000):Math.floor(dt.getTime()/60000);
 if(!Number.isFinite(minute))return null;
 return {issue,number,time,minute};
}
function makeBars(source=rounds){
 const bars=[];let level=100,lastKey=null;
 for(const r of source){
  const key=Math.floor(r.minute/tf);
  const open=level;level+=r.number>=5?1:-1;
  if(key!==lastKey){bars.push({bucket:key,time:key*tf*60-390*60,open,high:Math.max(open,level),low:Math.min(open,level),close:level});lastKey=key;}
  else {const b=bars[bars.length-1];b.high=Math.max(b.high,level);b.low=Math.min(b.low,level);b.close=level;}
 }
 return bars;
}
function initChart(){
 if(!window.LightweightCharts){$("historyStatus").textContent="Chart library unavailable";return;}
 chart=LightweightCharts.createChart($("kronosChart"),{width:$("kronosChart").clientWidth,height:$("kronosChart").clientHeight,layout:{background:{type:"solid",color:"#0c1c2c"},textColor:"#a7bbcd"},grid:{vertLines:{color:"#172c3e"},horzLines:{color:"#172c3e"}},rightPriceScale:{borderColor:"#304a61"},timeScale:{borderColor:"#304a61",rightOffset:12,fixLeftEdge:true,timeVisible:true,secondsVisible:false,tickMarkFormatter:(time,type)=>{const iso=new Date((time+420*60)*1000).toISOString();return type===0?iso.slice(0,4):type===1?iso.slice(0,7):type===2?iso.slice(5,10):iso.slice(11,16);}},localization:{timeFormatter:time=>new Date((time+420*60)*1000).toISOString().slice(0,16).replace("T"," ")+" Bangkok (UTC+07:00)"},crosshair:{mode:LightweightCharts.CrosshairMode.Normal}});
 candle=chart.addCandlestickSeries({upColor:"#04b99c",downColor:"#ee5162",wickUpColor:"#04b99c",wickDownColor:"#ee5162",borderVisible:false,priceFormat:{type:"price",precision:1,minMove:1}});
 projected=chart.addAreaSeries({lineColor:"#ae86fa",topColor:"rgba(174,134,250,0.3)",bottomColor:"rgba(174,134,250,0.03)",lineWidth:3,lineStyle:2,lastValueVisible:false,priceLineVisible:false});
 projectedCandles=chart.addCandlestickSeries({upColor:'rgba(174,134,250,0.06)',downColor:'rgba(174,134,250,0.06)',borderVisible:true,borderUpColor:'#c8a8ff',borderDownColor:'#c8a8ff',wickUpColor:'#ae86fa',wickDownColor:'#ae86fa',lastValueVisible:false,priceLineVisible:false,priceFormat:{type:'price',precision:4,minMove:0.0001}});
 chart.subscribeCrosshairMove(inspectTarget);chart.subscribeClick(inspectTarget);
 resizeObserver=new ResizeObserver(()=>chart.applyOptions({width:$("kronosChart").clientWidth,height:$("kronosChart").clientHeight}));resizeObserver.observe($("kronosChart"));
}
function render(){
 if(!candle)return;
 KronosExplain.reset(tf);
 inspectData=null;
 $('archiveMetrics').textContent='Archive comparisons loading for '+tf+'m…';
 $("inspector").textContent="Forecast ကို mouse နဲ့ထောက်ပါ၊ ဖုန်းမှာ ထိကြည့်ပါ။";
 for(const id of ["scoredTargets","pendingTargets","forecastAge","nextForecast"])$(id).textContent="—";
 KronosDashboard.renderReport(tf);
 $("replay").disabled=true;
 const replayOrigin=replayMode&&activeSnapshot?rounds.findIndex(r=>r.issue===String(activeSnapshot.origin_issue)):-1;
 const bars=makeBars(replayMode?(replayOrigin>=0?rounds.slice(0,replayOrigin+1):[]):rounds);candle.setData(bars);projected.setData([]);projectedCandles.setData([]);$("horizon").textContent="—";$("forecastStatus").textContent="Not loaded";$("snapshotInfo").textContent="No snapshot imported";$("comparison").textContent="No validated forecast loaded. Research snapshots can be compared only after their target rounds have occurred.";chart.timeScale().setVisibleLogicalRange({from:Math.max(0,bars.length-120),to:bars.length+16});
 $("issue").textContent=rounds.length?rounds[rounds.length-1].issue:"—";$("count").textContent=String(rounds.length);
}
async function load(){
 $("historyStatus").textContent="Loading existing /api/history…";
 try{
  const historyUrl=rounds.length?"/api/history?days=30&since="+encodeURIComponent(rounds[rounds.length-1].issue):"/api/history?days=30";
  const response=await download(historyUrl);
  const json=await response.json();if(!Array.isArray(json.history))throw Error("History format unavailable");
  if(Number.isFinite(Date.parse(json.last_time_utc)))lastSourceUtc=json.last_time_utc;
  sourceAgeMinutes=(Date.now()-Date.parse(lastSourceUtc))/60000;
  const incoming=json.incremental?[...rounds.map(r=>[r.issue,r.number,r.time]),...json.history]:json.history;
  const unique=new Map();
  for(const r of incoming.map(parseRound).filter(Boolean)){
   const previous=unique.get(r.issue);
   if(previous&&(previous.number!==r.number||previous.time!==r.time))throw Error("Conflicting duplicate round");
   unique.set(r.issue,r);
  }
  const candidate=Array.from(unique.values()).sort((a,b)=>a.issue.length-b.issue.length||a.issue.localeCompare(b.issue)).slice(-MAX_ROUNDS);
  if(candidate.some((r,i)=>i>0&&r.minute<=candidate[i-1].minute))throw Error("Round timestamps out of order or duplicate minute");
  rounds=candidate;
  $("historyStatus").textContent=rounds.length?"Loaded "+rounds.length+" rounds · read-only":"No valid rounds available";
 }catch(err){sourceAgeMinutes=Infinity;$("historyStatus").textContent="History unavailable; last loaded rounds retained: "+err.message;}
}
async function importSnapshot(file,dry=false,version=requestVersion){
 if(!file)return;
 try{
  if(file.size>150000)throw Error("Snapshot is too large");
  const snap=JSON.parse(await file.text());
  if(!current(version))return null;
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
  if(snap.source_timezone!==undefined&&snap.source_timezone!=='Asia/Yangon')throw Error('Unsupported source timezone');
  if((rounds[origin].minute-390)*60000>generation)throw Error('Input origin is after generation');
  // Stable relative anchor survives a moving 10000-round viewer window.
  const originBucket=Math.floor(rounds[origin].minute/tf);
  const originBar=bars.findIndex(b=>b.bucket===originBucket);
  if(originBar<0)throw Error("Origin bar not available");
  let delta=snap.forecast_delta;
  if(delta!==undefined&&(!Array.isArray(delta)||delta.length!==values.length||delta.some(v=>typeof v!=="number"||!Number.isFinite(v)||Math.abs(v)>1000000)))throw Error('Invalid forecast deltas');
  if(delta===undefined) {
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
  const points=[{time:bars[originBar].time,value:originAnchor}];
  let evaluated=0,error=0,persistence=0,excluded=0,randomError=0,majorityError=0,directions=0,correctDirections=0;
  const training=rounds.slice(Math.max(0,origin-(snap.lookback_bars||256)*tf+1),origin+1);
  const majority=Math.sign(training.reduce((sum,r)=>sum+(r.number>=5?1:-1),0));
  const contiguous=[];let expectedMinute=rounds[origin].minute+1;
  for(const row of rounds.slice(origin+1)){if(row.minute!==expectedMinute)break;contiguous.push(row);expectedMinute++;}
  const scorable=new Set(),explanations=[];
  for(let i=0;i<delta.length;i++){
   const bucket=originBucket+i+1;
   const actual=bars.find(b=>b.bucket===bucket);
   const time=actual?actual.time:bucket*tf*60-390*60;
   if(time>points[points.length-1].time)points.push({time,value:originAnchor+delta[i]});
   // API local calendar is Asia/Yangon (UTC+06:30). Exclude bars already
   // started before publication and the currently incomplete source bar.
   const startUtc=(bucket*tf-390)*60000;
   const explanation={horizon:i+1,startMs:startUtc,endMs:startUtc+tf*60000,prediction:delta[i],actual:null,status:'pending'};
   explanations.push(explanation);
   if(startUtc<=generation){explanation.status='excluded';excluded++;continue;}
   const targetRows=contiguous.filter(r=>r.minute<(bucket+1)*tf);
   if(actual&&explanation.endMs<=Date.now()&&bucket<bars[bars.length-1].bucket&&targetRows.length&&targetRows[targetRows.length-1].minute===(bucket+1)*tf-1){
    scorable.add(time);
    evaluated++;error+=Math.abs(originAnchor+delta[i]-actual.close);
    const observedDelta=actual.close-originAnchor;
    explanation.status='completed';explanation.actual=observedDelta;
    persistence+=Math.abs(observedDelta);
    const n=rounds.slice(origin+1).filter(r=>Math.floor(r.minute/tf)<=bucket).length;
    randomError+=KronosResearch.randomAbsoluteError(n,observedDelta);
    majorityError+=Math.abs(majority*n-observedDelta);
    if(delta[i]!==0&&observedDelta!==0){directions++;correctDirections+=Math.sign(delta[i])===Math.sign(observedDelta)?1:0;}
   }else if(bucket<bars[bars.length-1].bucket){explanation.status='unavailable';}
  }
  if(dry)return {evaluated,error,persistence,randomError,majorityError,excluded,horizon:values.length};
  const projection=KronosResearch.forecastCandles(snap,points,originAnchor);
  const showCandles=predictionStyle==='candles'&&projection.candles.length>0;
  projected.setData(forecastVisible&&!showCandles?points:[]);
  projectedCandles.setData(forecastVisible&&showCandles?projection.candles:[]);
  $('predictionStyleStatus').textContent=!forecastVisible?'Prediction ကို ဖုံးထားသည်။':showCandles?'ခရမ်းရောင် ဘောင်ပါတဲ့ candles = model ခန့်မှန်းထားသော OHLC · အစိမ်း/အနီ = တကယ်ထွက်လာသော rounds။':predictionStyle==='line'?'Line = candle တစ်တိုင်စီ၏ ခန့်မှန်းထားသော ပိတ်တန်ဖိုး (Close)။':projection.reason==='legacy'?'ဒီ forecast အဟောင်းမှာ Close ပဲရှိလို့ line အဖြစ် ပြထားပါသည်။ Candle အတွက် OHLC ပါသော forecast အသစ် လိုအပ်သည်။':'Model OHLC က candle စည်းမျဉ်းနှင့် မကိုက်ညီလို့ Close line ကိုသာ ပြထားပါသည်။ အမြီး/ကိုယ်ထည်ကို ပြန်ဖန်တီးမထားပါ။';
  activeSnapshot=snap;
  inspectData={predicted:new Map(points.slice(1).map(p=>[p.time,p.value])),candles:new Map(projection.candles.map(p=>[p.time,p])),actual:new Map((replayMode?makeBars(rounds.slice(0,origin+1)):bars).map(b=>[b.time,b])),generation,scorable,latest:bars[bars.length-1].time};
  KronosDashboard.summary(replayMode?'—':evaluated,replayMode?'—':explanations.filter(row=>row.status==='pending').length,snap.generated_at_utc,publicationTimes.get(tf)||null);
  $("replay").disabled=false;
  candle.setData(replayMode?makeBars(rounds.slice(0,origin+1)):bars);
  $("replay").textContent=replayMode?"Show actual":"Replay origin";
  const ageMinutes=Math.max(0,(Date.now()-generation)/60000);
  const historical=origin!==rounds.length-1;
  $("horizon").textContent=values.length+" bars";
  $("forecastStatus").textContent=!Number.isFinite(sourceAgeMinutes)||sourceAgeMinutes>5||sourceAgeMinutes< -1?"Feed stale / unknown":bars[bars.length-1].bucket>originBucket+values.length?"Historical · horizon ended":ageMinutes>tf*values.length?"Stale · not latest":historical?"Active · older origin":"Current · research";
  KronosExplain.render({tf,generated:snap.generated_at_utc,status:$("forecastStatus").textContent,rows:explanations,replay:replayMode});
  $("snapshotInfo").textContent=snap.model+"@"+(snap.model_revision||"unknown").slice(0,8)+" · origin "+snap.origin_issue+" · generated "+new Date(generation).toISOString()+" · "+Math.round(ageMinutes)+" min ago · "+tf+"m";
  $("comparison").textContent=evaluated?"Evaluated bars: "+evaluated+" · close MAE: "+(error/evaluated).toFixed(3)+" steps · persistence MAE: "+(persistence/evaluated).toFixed(3)+" steps · expected random MAE: "+(randomError/evaluated).toFixed(3)+" · past-majority MAE: "+(majorityError/evaluated).toFixed(3)+" · origin-to-target direction: "+(directions?correctDirections+"/"+directions:"no non-tied samples")+" · excluded already-started bars: "+excluded+". Continuous projection; no round win-rate claim.":"Pending: no fully completed, post-publication target bars available. Excluded already-started bars: "+excluded+". No measured accuracy yet.";

  if(replayMode)$("comparison").textContent="Replay: only rounds known at the original forecast origin are visible. Select Show actual for the subsequent comparison.";
  return true;
 }catch(err){if(dry)throw err;if(!current(version))return null;clearForecast(err.message);KronosExplain.reset(tf,'ဒီ forecast ကို စစ်မရသေးပါ။ မူလ round data သို့မဟုတ် forecast ဖိုင် မကိုက်ညီပါ။');$("forecastStatus").textContent="Rejected";$("snapshotInfo").textContent=err.message;return false;}finally{if(!dry&&current(version))$("snapshot").value="";}
}
document.querySelectorAll("[data-tf]").forEach(button=>button.addEventListener("click",()=>{firstPublication=false;tf=Number(button.dataset.tf);replayMode=false;document.querySelectorAll("[data-tf]").forEach(x=>x.classList.toggle("chosen",x===button));clearForecast('Loading selected timeframe.');render();autoSnapshot();}));
async function refresh(){
 if(refreshing)return;refreshing=true;
 try{
 const version=++requestVersion;
 const view=chart?.timeScale().getVisibleLogicalRange?.();
 await load();if(!current(version))return;
 render();await autoSnapshot(version);
 if(current(version)&&view)chart.timeScale().setVisibleLogicalRange(view);
 }finally{refreshing=false;}
}
$("reload").addEventListener("click",refresh);
$("replay").addEventListener("click",()=>{if(!activeSnapshot)return;replayMode=!replayMode;importSnapshot({size:0,text:async()=>JSON.stringify(activeSnapshot)});});
$("forecastToggle").addEventListener("click",()=>{forecastVisible=!forecastVisible;$("forecastToggle").textContent="Forecast "+(forecastVisible?"ON":"OFF");if(!forecastVisible){projected.setData([]);projectedCandles.setData([]);$('predictionStyleStatus').textContent='Prediction ကို ဖုံးထားသည်။';}else if(activeSnapshot)importSnapshot({size:0,text:async()=>JSON.stringify(activeSnapshot)});});
$('predictionStyle').addEventListener('change',event=>{predictionStyle=event.target.value==='line'?'line':'candles';if(activeSnapshot)importSnapshot({size:0,text:async()=>JSON.stringify(activeSnapshot)});});
$("forecastHistory").addEventListener("change",event=>{const path=event.target.value;if(!/^forecasts\/[a-zA-Z0-9-]+\.json$/.test(path))return;selections.set(tf,{path});replayMode=false;autoSnapshot();});
$("latestForecast").addEventListener('click',()=>{selections.delete(tf);replayMode=false;autoSnapshot();});
$("snapshot").addEventListener("change",async event=>{
 const file=event.target.files?.[0];if(!file)return;
 const version=++requestVersion;
 if(file.size>150000){clearForecast('Snapshot is too large');return;}
 const text=await file.text();if(!current(version))return;
 replayMode=false;
 if(await importSnapshot({size:file.size,text:async()=>text},false,version)){
  selections.set(tf,{text});$('selectionStatus').textContent='ကိုယ်တိုင်ထည့်ထားသော forecast · auto-refresh လုပ်လည်း ဒီဖိုင်ကို ဆက်ကြည့်ပါမယ်။';
 }
});
async function archiveMetrics(entries,version){
 const timeframe=tf;
 let forecasts=0,completed=0,pending=0,unavailable=0,n=0,error=0,persistence=0,random=0,majority=0;
 for(const entry of entries.slice(0,24)){
  if(!current(version)||tf!==timeframe)return;
  try{
   const report=await importSnapshot(await snapshotFile(entry.file),true,version);
   if(!report)return;
   forecasts++;n+=report.evaluated;error+=report.error;persistence+=report.persistence;
   random+=report.randomError;majority+=report.majorityError;
   if(report.evaluated+report.excluded===report.horizon)completed++;else pending++;
  }catch(_error){unavailable++;}
 }
 if(!current(version)||tf!==timeframe)return;
 $("archiveMetrics").textContent="Archive sample: "+forecasts+" forecasts · completed "+completed+" · pending "+pending+" · unavailable "+unavailable+" · evaluated target bars "+n+(n?" · model MAE "+(error/n).toFixed(3)+" · persistence "+(persistence/n).toFixed(3)+" · expected random "+(random/n).toFixed(3)+" · past-majority "+(majority/n).toFixed(3):" · awaiting future outcomes")+". Latest 24 snapshots for this timeframe; overlapping targets are correlated, not independent trials.";
}
async function autoSnapshot(version=++requestVersion){
 const timeframe=tf;
 const selection=selections.get(timeframe);
 KronosDashboard.loadReport(PUBLICATION,timeframe);
 KronosDashboard.loadBacktest(PUBLICATION,timeframe);
 try{
  if(selection?.text){
   $('selectionStatus').textContent='ကိုယ်တိုင်ထည့်ထားသော forecast · auto-refresh လုပ်လည်း ဒီဖိုင်ကို ဆက်ကြည့်ပါမယ်။';
   await importSnapshot({size:0,text:async()=>selection.text},false,version);
   return;
  }
  const response=await download(KronosDashboard.publicationURL(PUBLICATION,"index.json")).catch(error=>{throw Error('No published forecast manifest ('+error.message+')');});
  const manifest=await response.json();
  if(!current(version))return;
  if(manifest.schema!=="kronos-index-v1"||!Array.isArray(manifest.forecasts))throw Error("Invalid manifest");
  if(firstPublication){
   firstPublication=false;
   const available=manifest.forecasts.find(x=>[1,5,15,60].includes(x.timeframe));
   if(available&&!manifest.forecasts.some(x=>x.timeframe===tf)){
    tf=available.timeframe;
    document.querySelectorAll("[data-tf]").forEach(x=>x.classList.toggle("chosen",Number(x.dataset.tf)===tf));
    render();return autoSnapshot();
   }
  }
  const all=manifest.forecasts.filter(x=>x.timeframe===timeframe&&/^forecasts\/[a-zA-Z0-9-]+\.json$/.test(x.file)&&Number.isFinite(Date.parse(x.generated_at_utc))).sort((a,b)=>Date.parse(b.generated_at_utc)-Date.parse(a.generated_at_utc));
  const entries=all.slice(0,60);
  if(entries.length)publicationTimes.set(timeframe,entries[0].generated_at_utc);else publicationTimes.delete(timeframe);
  const chosen=selection?.path?all.find(x=>x.file===selection.path):entries[0];
  if(chosen&&!entries.includes(chosen))entries.push(chosen);
  $("forecastHistory").replaceChildren();
  for(const item of entries){
   const option=document.createElement("option");option.value=item.file;
   option.textContent=new Date(item.generated_at_utc).toLocaleString('en-GB',{timeZone:'Asia/Bangkok',hour12:false})+' Bangkok · '+item.origin_issue;
   $("forecastHistory").append(option);
  }
  $('selectionStatus').textContent=selection?.text?'ကိုယ်တိုင်ထည့်ထားသော forecast · auto-refresh လုပ်လည်း ဒီဖိုင်ကို ဆက်ကြည့်ပါမယ်။':selection?.path?'အဟောင်း forecast ကို ရွေးကြည့်နေသည် · auto-refresh လုပ်လည်း ဒီရွေးချယ်မှုကို ထိန်းထားပါမယ်။':'နောက်ဆုံးထုတ်ထားသော forecast ကို အလိုအလျောက် ရွေးပြနေသည်။';
  if(!chosen&&!selection?.text)throw Error(selection?.path?'Selected forecast is no longer in the active index; choose Latest forecast.':"No model output published for "+timeframe+"m yet");
  if(chosen)$("forecastHistory").value=chosen.file;
  const file=selection?.text?{size:0,text:async()=>selection.text}:await snapshotFile(chosen.file);
  if(!current(version))return;
  if(!await importSnapshot(file,false,version))return;
  archiveMetrics(entries,version);
  try{
   const status=await download(KronosDashboard.publicationURL(PUBLICATION,"status-"+timeframe+"m.json"));
   const info=await status.json();
   if(current(version)&&info.status==="failed"){
    $("snapshotInfo").textContent+=" · Last inference failed: "+info.reason;
    $('publicationStatus').textContent='နောက်ဆုံး forecast ထုတ်ရန် ကြိုးစားမှု မအောင်မြင်ပါ။ အရင်အောင်မြင်ထားသော forecast ကိုသာ ပြထားပါသည်။';
   }
  }catch(_err){/* Keep the validated forecast; status is supplemental. */}
 }catch(err){
  if(!current(version))return;
  clearForecast(err.message);
  KronosExplain.reset(timeframe,'ဒီ timeframe အတွက် forecast မရသေးပါ။ ရလဒ်ကို မဆုံးဖြတ်နိုင်သေးပါ။');
  $("forecastStatus").textContent="Unavailable";$("snapshotInfo").textContent=err.message;
  $("archiveMetrics").textContent="No validated archive available.";
  $('publicationStatus').textContent='Forecast ကို ယခု မယူနိုင်သေးပါ။ Refresh history သည် prediction အသစ် ထုတ်ပေးခြင်း မဟုတ်ပါ။';
 }
}

$("reportWindow").addEventListener("change",()=>KronosDashboard.renderReport(tf));
initChart();refresh();
setInterval(refresh,30000);
})();
