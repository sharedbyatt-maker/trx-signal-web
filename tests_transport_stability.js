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
 console.log('Transport timeout, abort and recovery checks passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
