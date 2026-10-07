const assert=require('node:assert/strict');
const fs=require('node:fs');const vm=require('node:vm');
const context={window:{},AbortController,setTimeout,clearTimeout,Promise,Error};
vm.runInNewContext(fs.readFileSync('static/js/transport.js','utf8'),context);
(async()=>{
 let aborted=false;
 await assert.rejects(context.window.TRXNet.run(signal=>{signal.addEventListener('abort',()=>aborted=true);return new Promise(()=>{});},15),/timed out/);
 assert.equal(aborted,true);
 assert.equal(await context.window.TRXNet.run(async()=>42,15),42);
 await assert.rejects(context.window.TRXNet.run(async()=>{throw new Error('bad JSON');},15),/bad JSON/);
 // Exercise the actual history loader with a delayed snapshot and a live arrival.
 const appSource=fs.readFileSync('static/js/app.js','utf8');
 let finishHistory;
 const historyContext={document:{getElementById:()=>null},Date,Set,Map,Promise,Error,
   TRXNet:{run:operation=>operation()},fetch:()=>new Promise(resolve=>finishHistory=resolve)};
 vm.runInNewContext(appSource.slice(0,appSource.indexOf('function setConn('))+`
   globalThis.fixture={loadFullHistory,setRows:rows=>{fullRows=rows;rebuildFullIssueSet();},
     rows:()=>fullRows,setTime:(raw,utc)=>{lastResultTime=raw;lastResultUtc=utc;},
     time:()=>[lastResultTime,lastResultUtc]};`,historyContext);
 const row=(issue,number,time)=>({issue,number,block_time:time,type:number>=5?'BIG':'SMALL'});
 const older=row('100',2,'2026-10-07 10:00:00');
 historyContext.fixture.setRows([older,row('101',3,'2026-10-07 10:01:00')]);
 const loading=historyContext.fixture.loadFullHistory(true);
 const newest=row('102',8,'2026-10-07 10:02:00');
 historyContext.fixture.setRows([older,row('101',3,'2026-10-07 10:01:00'),newest]);
 historyContext.fixture.setTime(newest.block_time,'2026-10-07T03:32:00Z');
 finishHistory({ok:true,json:async()=>({history:[['101',9,'2026-10-07 10:01:00']],
   last_time:'2026-10-07 10:01:00',last_time_utc:'2026-10-07T03:31:00Z'})});
 await loading;
 assert.deepEqual(Array.from(historyContext.fixture.rows(),r=>[r.issue,r.number]),[['101',9],['102',8]],
   'A full snapshot corrects older rows but must retain live rounds arriving while it loads');
 assert.deepEqual(Array.from(historyContext.fixture.time()),[newest.block_time,'2026-10-07T03:32:00Z']);
 const finalSnapshot=historyContext.fixture.loadFullHistory(true);
 finishHistory({ok:true,json:async()=>({history:[['101',4,'2026-10-07 10:01:00']],
   last_time:'2026-10-07 10:01:00',last_time_utc:'2026-10-07T03:31:00Z'})});
 await finalSnapshot;
 assert.deepEqual(Array.from(historyContext.fixture.rows(),r=>[r.issue,r.number]),[['101',4]],
   'Without concurrent arrivals the full response remains authoritative');
 console.log('Transport timeout, abort, recovery and delayed history checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});

