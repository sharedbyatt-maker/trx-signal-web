// Dependency-free UI integration checks. Chart rendering still needs browser QA.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const KronosResearch=require('./static/js/kronos-research.js');
assert.equal(KronosResearch.randomAbsoluteError(2,0),1);
assert.equal(KronosResearch.randomAbsoluteError(2,2),2);
assert.ok(KronosResearch.randomAbsoluteError(1100,0)>20);
async function boot(unavailable=false,gap=false,mode="history"){
 const nodes=new Map();
 function element(id){if(!nodes.has(id))nodes.set(id,{textContent:'',value:'',clientWidth:1000,clientHeight:480,events:{},classList:{toggle(){}},addEventListener(k,v){this.events[k]=v;},replaceChildren(){this.children=[];},append(v){(this.children??=[]).push(v);}});return nodes.get(id);}
 const now=Date.now(), start=Math.floor(now/60000)*60000-200*60000;
 const rows=Array.from({length:200},(_,i)=>[String(100000+i),i%10,new Date(start+i*60000+390*60000).toISOString().slice(0,19)]);
 if(gap)rows.splice(181,1);
 const origin=mode==="pending"?199:180;
 const snapshot={schema:'kronos-round-snapshot-v1',data_source:'big-small-walk',model:'Kronos-mini',source:'official-kronos-inference-cpu',research_only:true,timeframe_minutes:1,origin_issue:rows[origin][0],forecast_close:[900,901],forecast_delta:[1,2],generated_at_utc:new Date(start+(mode==="excluded"?190:origin)*60000+1000).toISOString()};
 let projection=[],view=null,chartOptions=null;const historyUrls=[];const fetchControl={override:null};
 const buttons=[1,5,15,60].map(tf=>{const node=element("tf-"+tf);node.dataset={tf:String(tf)};return node;});
 const chart={addCandlestickSeries(){return{setData(){}};},addAreaSeries(){return{setData(x){projection=x;}};},subscribeCrosshairMove(fn){this.inspect=fn;},subscribeClick(fn){this.tap=fn;},applyOptions(){},timeScale(){return{fitContent(){},setVisibleLogicalRange(v){view=v;},getVisibleLogicalRange(){return view;}};}};
 const context={KronosResearch,setInterval(){},console,Date,Set,Map,Number,JSON,Math,Error,ResizeObserver:class{observe(){}},window:{LightweightCharts:true,KronosResearch},LightweightCharts:{createChart(_element,options){chartOptions=options;return chart;},CrosshairMode:{Normal:0}},document:{getElementById:element,querySelectorAll(){return buttons;},createElement(){return element('created-'+nodes.size);}},fetch:async url=>{
  if(fetchControl.override){const response=fetchControl.override(url);if(response!==undefined)return response;}
  if(url.startsWith('/api/history')){historyUrls.push(url);return{ok:true,json:async()=>historyUrls.length===1?({history:rows,last_time_utc:new Date(now-60000).toISOString()}):({history:[],incremental:true,last_time_utc:null})};}
  url=url.split('?')[0];
  if(url.endsWith('index.json'))return{ok:!unavailable,status:404,json:async()=>({schema:'kronos-index-v1',forecasts:[{file:'forecasts/test.json',timeframe:1,origin_issue:snapshot.origin_issue,generated_at_utc:snapshot.generated_at_utc}]})};
  if(/status-(1|5)m\.json$/.test(url))return{ok:true,json:async()=>({status:'ready'})};
  return{ok:true,text:async()=>JSON.stringify(snapshot)};
 }};
 vm.runInNewContext(fs.readFileSync('static/js/kronos-dashboard.js','utf8'),context);
 context.KronosDashboard=context.window.KronosDashboard;
 vm.runInNewContext(fs.readFileSync('static/js/kronos-explain.js','utf8'),context);
 context.KronosExplain=context.window.KronosExplain;
 vm.runInNewContext(fs.readFileSync('static/js/kronos.js','utf8'),context);
 for(let i=0;i<12;i++)await new Promise(setImmediate);
 return{snapshot,rows,buttons,fetchControl,explain:context.KronosExplain,element,projection:()=>projection,historyUrls,chart,view:()=>view,chartOptions:()=>chartOptions};
}
async function settle(){for(let i=0;i<15;i++)await new Promise(setImmediate);}
async function regressions(app){
 const {expected}=KronosResearch.publicationSchedule(1,'2026-11-01T10:56:23Z',Date.parse('2026-11-01T11:20:00Z'));
 assert.equal(new Date(expected).toISOString(),'2026-11-01T10:57:00.000Z');
 assert.equal(KronosResearch.publicationSchedule(1,'2026-11-01T10:56:23Z',expected+180000).overdue,true);
 assert.equal(KronosResearch.publicationSchedule(15,new Date().toISOString()),null);
 const older={...app.snapshot,origin_issue:app.rows[170][0],generated_at_utc:new Date(Date.parse(app.snapshot.generated_at_utc)-600000).toISOString(),forecast_delta:[3,4]};
 const entries=[{file:'forecasts/test.json',timeframe:1,origin_issue:app.snapshot.origin_issue,generated_at_utc:app.snapshot.generated_at_utc},{file:'forecasts/older.json',timeframe:1,origin_issue:older.origin_issue,generated_at_utc:older.generated_at_utc},{file:'forecasts/test5.json',timeframe:5,origin_issue:app.snapshot.origin_issue,generated_at_utc:app.snapshot.generated_at_utc}];
 const json=data=>({ok:true,json:async()=>data,text:async()=>JSON.stringify(data)});
 const manifest=json({schema:'kronos-index-v1',forecasts:entries});
 const originalNext=app.element('nextForecast').textContent;
 let release,delayFive=false;
 app.fetchControl.override=url=>{
  if(url.includes('index.json'))return manifest;
  if(url.endsWith('older.json'))return json(older);
  if(url.endsWith('test5.json')){
   if(delayFive)return new Promise(resolve=>{release=()=>resolve(json({...app.snapshot,timeframe_minutes:5}));});
   return json({...app.snapshot,timeframe_minutes:5});
  }
 };
 app.element('forecastHistory').events.change({target:{value:'forecasts/older.json'}});await settle();
 assert.match(app.element('snapshotInfo').textContent,/origin 100170/);
 assert.equal(app.element('nextForecast').textContent,originalNext,'schedule follows latest publication even while viewing an archive');
 await app.element('reload').events.click();await settle();
 assert.match(app.element('snapshotInfo').textContent,/origin 100170/,'refresh preserves historical selection');
 app.element('replay').events.click();await settle();
 await app.element('reload').events.click();await settle();
 assert.match(app.element('easyActual').textContent,/ဖုံးထား/,'refresh preserves replay');
 assert.equal(app.element('scoredTargets').textContent,'—','replay hides actual outcome counts');
 app.element('latestForecast').events.click();await settle();
 assert.match(app.element('snapshotInfo').textContent,/origin 100180/);
 delayFive=true;app.buttons[1].events.click();await settle();
 assert.equal(typeof release,'function');
 app.buttons[0].events.click();await settle();
 release();await settle();
 assert.match(app.element('snapshotInfo').textContent,/1m$/,'late 5m response cannot replace 1m view');
 assert.match(app.element('easyTitle').textContent,/1m/);
 // Import survives refresh even if the remote manifest then goes offline.
 const text=JSON.stringify(older);
 await app.element('snapshot').events.change({target:{files:[{size:text.length,text:async()=>text}]}});await settle();
 app.fetchControl.override=url=>url.includes('index.json')?{ok:false,status:503}:undefined;
 await app.element('reload').events.click();await settle();
 assert.match(app.element('snapshotInfo').textContent,/origin 100170/);
 app.element('latestForecast').events.click();await settle();
 assert.equal(app.element('forecastStatus').textContent,'Unavailable');
 assert.equal(app.projection().length,0,'failed refresh must clear prior purple forecast');
 assert.equal(app.element('replay').disabled,true);
 assert.equal(app.element('scoredTargets').textContent,'—');
 assert.equal(app.element('count').textContent,'200','publication failure does not delete history');
}
(async()=>{
 const app=await boot();
 assert.equal(app.view().from,80);
 assert.equal(app.view().to,216);
 assert.equal(app.chartOptions().timeScale.tickMarkFormatter(1700000000,2),new Date((1700000000+420*60)*1000).toISOString().slice(5,10));
 assert.match(app.element('forecastStatus').textContent,/Historical/);
 assert.match(app.element('comparison').textContent,/Evaluated bars: 2/);
 assert.equal(app.projection().length,3);
 assert.equal(app.element('scoredTargets').textContent,'2');
 assert.equal(app.element('pendingTargets').textContent,'0');
 assert.match(app.element('easyTitle').textContent,/1m/);
 assert.match(app.element('easyCount').textContent,/စစ်ပြီး 2 ခု/);
 assert.match(app.element('easyVerdict').textContent,/ဦးတည်ချက် မကိုက်/);
 assert.equal(app.element('easyRows').children.length,2);
 app.element('replay').events.click();await new Promise(setImmediate);
 assert.match(app.element('easyActual').textContent,/ဖုံးထား/);
 assert.match(app.element('easyAverage').textContent,/မပြထား/);
 app.element('replay').events.click();await new Promise(setImmediate);
 app.chart.tap({time:app.projection()[1].time});
 assert.match(app.element('inspector').textContent,/forecast .*actual .*error/);
 app.chart.inspect({time:app.projection()[0].time-60});
 assert.match(app.element('inspector').textContent,/Historical candle/);
 assert.ok(app.projection()[0].time>1700000000,'chart uses real UTC timestamps, not 1970 ordinal indices');
 assert.equal(app.projection()[1].time-app.projection()[0].time,60);
 assert.equal(app.projection()[1].value-app.projection()[0].value,1,'uses deltas, not old absolute base');
 app.element('forecastToggle').events.click();
 assert.equal(app.projection().length,0);
 assert.equal(app.element('forecastToggle').textContent,'Forecast OFF');
 await app.element('reload').events.click();
 assert.match(app.historyUrls[1],/&since=100199/);
 assert.equal(app.element('count').textContent,'200');
 assert.match(app.element('forecastStatus').textContent,/Historical/);
 const exact=app.explain.describe({status:'completed',prediction:2,actual:2});
 assert.match(exact.label,/အတိအကျ/);assert.equal(exact.error,'0 steps');
 const partial=app.explain.describe({status:'completed',prediction:2,actual:1});
 assert.match(partial.label,/ဦးတည်ချက်ကိုက်၊ တန်ဖိုးကွာ/);assert.equal(partial.error,'1 steps');
 assert.match(app.explain.describe({status:'completed',prediction:0,actual:1}).label,/ကွာသည်/);
 const pending=await boot(false,false,'pending');
 assert.match(pending.element('easyActual').textContent,/စောင့်နေဆဲ/);
 assert.match(pending.element('easyCount').textContent,/စစ်ပြီး 0 ခု · စောင့်နေဆဲ 2 ခု/);
 const excluded=await boot(false,false,'excluded');
 assert.match(excluded.element('easyActual').textContent,/ရလဒ်ထဲ မထည့်/);
 assert.match(excluded.element('easyCount').textContent,/မပါဝင် 2 ခု/);
 const gap=await boot(false,true);
 assert.equal(gap.element('scoredTargets').textContent,'0');
 assert.equal(gap.element('pendingTargets').textContent,'0','missing data must not be counted as a pending outcome');
 assert.match(gap.element('easyCount').textContent,/data မပြည့် 2 ခု/);
 assert.match(gap.element('easyActual').textContent,/data မပြည့်/);
 assert.match(gap.element('comparison').textContent,/Pending/);
 const missing=await boot(true);
 assert.equal(missing.element('forecastStatus').textContent,'Unavailable');
 assert.equal(missing.projection().length,0);
 assert.match(missing.element('easyState').textContent,/forecast မရသေး/);
 assert.equal(missing.element('easyRows').children.length,0);

 await regressions(app);
 console.log('Kronos UI: historical evaluation, rebasing, toggle and unavailable states passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
