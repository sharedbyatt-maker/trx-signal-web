'use strict';
const syncNonce = new URL(location.href).searchParams.get('bridge');
const syncSource = window.opener;
const syncStatus = document.getElementById('sync-status');
let syncAccepted = false, syncQueue = Promise.resolve(), syncLastSeen = 0, syncPending = 0;
function syncSignal(type) { if (syncSource) syncSource.postMessage({type,nonce:syncNonce},'https://trxchart.com'); }
document.getElementById('sync-accept').addEventListener('click',()=>{
  if (!syncSource || !/^[a-f0-9]{48}$/.test(syncNonce||'')) { syncStatus.textContent='Open this window using the connection bookmark on TRXChart.'; return; }
  syncAccepted=true; syncLastSeen=Date.now();
  document.getElementById('sync-accept').disabled=true;
  document.getElementById('sync-stop').disabled=false;
  syncStatus.textContent='Connected. Open Terminal → History on TRXChart once.';
  syncSignal('trx-history-ready');
});
function stopSync(message) {
  syncAccepted=false; syncSignal('trx-history-stop');
  document.getElementById('sync-accept').disabled=true;
  document.getElementById('sync-stop').disabled=true;
  syncStatus.textContent=message;
}
document.getElementById('sync-stop').addEventListener('click',()=>stopSync('Stopped. Run the connection bookmark again to reconnect.'));
window.addEventListener('message',event=>{
  if (!syncAccepted || event.origin!=='https://trxchart.com' || event.source!==syncSource || event.data?.nonce!==syncNonce || event.data.type!=='trx-history') return;
  syncLastSeen=Date.now();
  const data=event.data;
  if (data.error) {syncStatus.textContent=String(data.error).slice(0,200);return;}
  if (data.connected) {syncStatus.textContent=data.waiting?'Connected. Open Terminal → History on TRXChart once.':'Connected. Reading Real / Demo history…';return;}
  if (!['real','demo'].includes(data.mode) || data.history?.success!==true || !Array.isArray(data.history.list) || data.history.list.length>5000 || syncPending>=4) return;
  ++syncPending;
  syncQueue=syncQueue.then(async()=>{
    if (!syncAccepted) return;
    const controller=new AbortController(), timer=setTimeout(()=>controller.abort(),20000);
    try {
      const response=await fetch('/api/admin/trade-journal/sync',{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':document.querySelector('meta[name="csrf-token"]').content},body:JSON.stringify({mode:data.mode,source_timezone:'Asia/Yangon',history:data.history}),signal:controller.signal});
      const result=await response.json();
      if (!response.ok) {
        if (response.status===401 || response.status===403) stopSync('Admin session expired. Sign in and reconnect.');
        throw Error(result.error||'Sync failed.');
      }
      if (!syncAccepted) return;
      document.getElementById('sync-'+data.mode).textContent=new Date().toLocaleTimeString()+' · '+result.summary.trades+' today · P/L '+result.summary.pnl.toLocaleString()+' MMK';
      syncStatus.textContent='Saved '+data.mode.toUpperCase()+' history. Only captured records are included.';
    } catch(error) {syncStatus.textContent=error.name==='AbortError'?'Save timed out. Next sync will retry.':error.message;}
    finally {clearTimeout(timer);}
  }).finally(()=>--syncPending);
});
setInterval(()=>{
  if (!syncAccepted) return;
  if (syncSource.closed) stopSync('TRXChart tab closed. Sync stopped.');
  else if (Date.now()-syncLastSeen>150000) syncStatus.textContent='No history received for over 2 minutes. Check TRXChart login and keep both tabs open.';
},10000);
window.addEventListener('pagehide',()=>syncSignal('trx-history-stop'));
