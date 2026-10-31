(() => {
"use strict";
const $ = id => document.getElementById(id);
let rounds=[], tf=1, chart, candle, projected, resizeObserver;
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
 return {issue,number,time,minute:Math.floor(dt.getTime()/60000)};
}
function makeBars(){
 const bars=[];let level=100,lastKey=null;
 for(const r of rounds){
  const key=Math.floor(r.minute/tf);
  const open=level;level+=r.number>=5?1:-1;
  if(key!==lastKey){bars.push({time:bars.length+1,open,high:Math.max(open,level),low:Math.min(open,level),close:level});lastKey=key;}
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
  const seen=new Set();rounds=json.history.slice(-MAX_ROUNDS).map(parseRound).filter(Boolean).filter(r=>{if(seen.has(r.issue))return false;seen.add(r.issue);return true;}).sort((a,b)=>a.issue.localeCompare(b.issue));
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
  // The snapshot must originate from the most recent round: never silently align stale paths to live bars.
  if(origin!==rounds.length-1)throw Error("Snapshot is historical; live overlay requires latest issue");
  const first=bars[bars.length-1].close;
  const values=snap.forecast_close.map(Number);if(values.some(v=>!Number.isFinite(v)||Math.abs(v)>1000000))throw Error("Invalid predicted value");
  projected.setData([{time:bars.length,value:first},...values.map((v,i)=>({time:bars.length+i+1,value:v}))]);
  $("horizon").textContent=values.length+" bars";$("forecastStatus").textContent="Imported · research";$("snapshotInfo").textContent="Unvalidated model output · origin "+snap.origin_issue+" · "+snap.model;
  $("comparison").textContent="Future outcomes not available yet; forecast path is an experimental synthetic-walk projection, not a BIG/SMALL win-rate claim.";
  $("historyStatus").textContent="Kronos model forecast displayed · experimental only";
 }catch(err){$("historyStatus").textContent="Snapshot rejected: "+err.message;}finally{$("snapshot").value="";}
}
document.querySelectorAll("[data-tf]").forEach(button=>button.addEventListener("click",()=>{tf=Number(button.dataset.tf);document.querySelectorAll("[data-tf]").forEach(x=>x.classList.toggle("chosen",x===button));render();}));
$("reload").addEventListener("click",load);$("snapshot").addEventListener("change",event=>importSnapshot(event.target.files?.[0]));
async function autoSnapshot(){
 try{
  const res=await fetch("/static/data/kronos_latest.json",{cache:"no-store"});
  if(!res.ok) return;
  const data=await res.text();
  await importSnapshot({size:data.length,text:async()=>data});
 }catch(err){$("snapshotInfo").textContent="No usable current model snapshot: "+err.message;}
}
initChart();load().then(autoSnapshot);
})();