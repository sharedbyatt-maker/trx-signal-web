// Dependency-free UI integration checks. Chart rendering still needs browser QA.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const KronosResearch=require('./static/js/kronos-research.js');
assert.equal(KronosResearch.randomAbsoluteError(2,0),1);
assert.equal(KronosResearch.randomAbsoluteError(2,2),2);
assert.ok(KronosResearch.randomAbsoluteError(1100,0)>20);
async function boot(unavailable=false){
 const nodes=new Map();
 function element(id){if(!nodes.has(id))nodes.set(id,{textContent:'',value:'',clientWidth:1000,clientHeight:480,events:{},classList:{toggle(){}},addEventListener(k,v){this.events[k]=v;},replaceChildren(){this.children=[];},append(v){(this.children??=[]).push(v);}});return nodes.get(id);}
 const now=Date.now(), start=Math.floor(now/60000)*60000-200*60000;
 const rows=Array.from({length:200},(_,i)=>[String(100000+i),i%10,new Date(start+i*60000+390*60000).toISOString().slice(0,19)]);
 const origin=180;
 const snapshot={schema:'kronos-round-snapshot-v1',data_source:'big-small-walk',model:'Kronos-mini',source:'official-kronos-inference-cpu',research_only:true,timeframe_minutes:1,origin_issue:rows[origin][0],forecast_close:[900,901],forecast_delta:[1,2],generated_at_utc:new Date(start+origin*60000+1000).toISOString()};
 let projection=[];
 const chart={addCandlestickSeries(){return{setData(){}};},addAreaSeries(){return{setData(x){projection=x;}};},applyOptions(){},timeScale(){return{fitContent(){}};}};
 const context={KronosResearch,setInterval(){},console,Date,Set,Map,Number,JSON,Math,Error,ResizeObserver:class{observe(){}},window:{LightweightCharts:true},LightweightCharts:{createChart(){return chart;},CrosshairMode:{Normal:0}},document:{getElementById:element,querySelectorAll(){return[];},createElement(){return{};}},fetch:async url=>{
  if(url.startsWith('/api/history'))return{ok:true,json:async()=>({history:rows,last_time_utc:new Date(now-60000).toISOString()})};
  if(url.endsWith('index.json'))return{ok:!unavailable,status:404,json:async()=>({schema:'kronos-index-v1',forecasts:[{file:'forecasts/test.json',timeframe:1,origin_issue:snapshot.origin_issue,generated_at_utc:snapshot.generated_at_utc}]})};
  if(url.endsWith('status.json'))return{ok:true,json:async()=>({status:'ready'})};
  return{ok:true,text:async()=>JSON.stringify(snapshot)};
 }};
 vm.runInNewContext(fs.readFileSync('static/js/kronos.js','utf8'),context);
 for(let i=0;i<12;i++)await new Promise(setImmediate);
 return{element,projection:()=>projection};
}
(async()=>{
 const app=await boot();
 assert.match(app.element('forecastStatus').textContent,/Historical/);
 assert.match(app.element('comparison').textContent,/Evaluated bars: 2/);
 assert.equal(app.projection().length,3);
 assert.equal(app.projection()[1].value-app.projection()[0].value,1,'uses deltas, not old absolute base');
 app.element('forecastToggle').events.click();
 assert.equal(app.projection().length,0);
 assert.equal(app.element('forecastToggle').textContent,'Forecast OFF');
 const missing=await boot(true);
 assert.equal(missing.element('forecastStatus').textContent,'Unavailable');
 assert.equal(missing.projection().length,0);
 console.log('Kronos UI: historical evaluation, rebasing, toggle and unavailable states passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
