const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
const source=fs.readFileSync('static/js/app.js','utf8');
let finish;
const context={document:{getElementById:()=>null},Date,Set,Map,Promise,Error,TRXNet:{run:f=>f()},fetch:()=>new Promise(r=>finish=r)};
vm.runInNewContext(source.slice(0,source.indexOf('function setConn('))+`
globalThis.fixture={normalizeRound,normalizeState,normalizeHistory,fetchFullHistory,
setRows:rows=>{fullRows=rows;rebuildFullIssueSet();},rows:()=>fullRows,time:()=>[lastResultTime,lastResultUtc]};`,context);
const f=context.fixture;
const round={issue:'20260913000000360',number:0,type:'SMALL',block_time:'2026-09-13 13:59:00'};
assert.equal(f.normalizeRound({...round,number:'0'}).number,0);
for(const bad of [{...round,number:99},{...round,number:null},{...round,type:'BIG'},{...round,issue:9007199254740993},{...round,issue:{}},{...round,block_time:'not-a-time'}])assert.throws(()=>f.normalizeRound(bad),/Invalid/);
assert.throws(()=>f.normalizeState({history:[round,null]}),/Invalid/);
assert.equal(f.normalizeHistory([[round.issue,0,round.block_time],[round.issue,0,round.block_time]],true).length,1);
const drawContext={window:{},document:{readyState:'loading',addEventListener(){}},Map,Set,JSON};
const drawSource=fs.readFileSync('static/js/draw.js','utf8').replace('  return {useCursor','  window.signature=rowsSignature; return {useCursor');
vm.runInNewContext(drawSource,drawContext);
const signature=drawContext.window.signature;
const drawing=p=>({id:'saved',type:'trend',width:2,points:[p]});
assert.equal(signature(drawing({p:100,t:10,lb:'exact-issue'})),signature(drawing({lb:'exact-issue',t:300,p:100,offset:null,anchorLb:null})));
assert.equal(signature(drawing({p:100,t:400,lb:null,anchorLb:'old',offset:40,futureTime:29000000})),signature(drawing({futureTime:29000000,p:100,t:500,anchorLb:'new',offset:10,lb:null})));
assert.notEqual(signature(drawing({p:100,t:10,lb:'exact-issue'})),signature(drawing({p:101,t:300,lb:'exact-issue'})));
assert.notEqual(signature(drawing({p:100,t:10})),signature(drawing({p:100,t:11})));
assert.notEqual(signature(drawing({p:100,anchorLb:'base',offset:10})),signature(drawing({p:100,anchorLb:'base',offset:11})));
(async()=>{
  f.setRows([round]);const request=f.fetchFullHistory(true,true),rejected=assert.rejects(request,/Invalid/);
  const background=f.fetchFullHistory(false);
  finish({ok:true,json:async()=>({history:[[round.issue,99,round.block_time]]})});await rejected;await background;
  assert.equal(f.rows()[0].number,0,'Malformed history must leave the previous buffer intact');
  const next=f.fetchFullHistory(true,true);
  finish({ok:true,json:async()=>({history:[['20260913000000362',2,'2026-09-13 14:01:00'],['20260913000000361',8,'2026-09-13 14:00:00']],last_time:round.block_time,last_time_utc:'2026-09-13T07:29:00Z'})});await next;
  assert.equal(f.rows().at(-1).issue,'20260913000000362');assert.equal(f.time()[0],'2026-09-13 14:01:00');assert.equal(f.time()[1],null);
  console.log('User View validation, history recovery, clock consistency and drawing signatures passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
