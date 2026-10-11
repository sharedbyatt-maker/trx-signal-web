/* Read-only browser bridge. Request credentials stay on trxchart.com. */
function trxHistoryBridge(destination) {
  'use strict';
  if (location.origin !== 'https://trxchart.com') return alert('Run this bookmark on your signed-in TRXChart page.');
  if (window.__trxHistoryBridge) return alert('History sync is already running in this tab.');
  const origin = new URL(destination).origin;
  const nonce = Array.from(crypto.getRandomValues(new Uint8Array(24)), b => b.toString(16).padStart(2, '0')).join('');
  const receiver = window.open(origin + '/admin/trxchart-sync-open?bridge=' + nonce, '_blank');
  if (!receiver) return alert('Allow the sync window to open, then run this bookmark again.');
  const original = window.fetch;
  let headers = null, accepted = false, running = false, stopped = false, timer;
  const active = new Set();
  const paths = {real:'/api/bet/history', demo:'/api/demo/history'};
  const send = data => receiver.postMessage({type:'trx-history', nonce, ...data}, origin);
  // Preserve large JSON integers before JSON.parse can round issue/order IDs.
  function exactJSON(raw) {
    return JSON.parse(raw.replace(/"(?:\\.|[^"\\])*"|-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/g, token => {
      if (/^-?\d+$/.test(token) && !Number.isSafeInteger(Number(token))) return JSON.stringify(token);
      return token;
    }));
  }
  async function read(response, mode) {
    if (stopped) return;
    if (!response.ok) throw Error(response.status===401 || response.status===403 ? 'TRXChart login expired. Sign in again and reconnect.' : 'History request failed ('+response.status+').');
    const text = await response.text();
    if (text.length > 8*1024*1024) throw Error('History response is too large.');
    const value = exactJSON(text);
    if (value.success !== true || !Array.isArray(value.list) || value.list.length > 5000) throw Error('Unexpected history response. No results synced.');
    const fields = ['addTime','issueNumber','selectType','amount','profitAmount','state','number','orderId','orderNumber','id'];
    const list = value.list.map(row => {
      if (!row || typeof row !== 'object' || Array.isArray(row)) throw Error('Invalid history record.');
      const clean = {};
      for (const key of fields) if (Object.hasOwn(row,key)) {
        if (row[key] !== null && !['string','number'].includes(typeof row[key])) throw Error('Invalid history field.');
        clean[key] = row[key];
      }
      return clean;
    });
    if (!stopped) send({mode, history:{success:true,list}, captured_at:new Date().toISOString()});
  }
  function stop() {
    stopped = true; clearInterval(timer);
    for (const controller of active) controller.abort();
    active.clear();
    window.removeEventListener('message', receive);
    if (window.fetch === wrapped) window.fetch = original;
    delete window.__trxHistoryBridge; headers = null;
  }
  async function poll() {
    if (stopped || receiver.closed) return stop();
    if (!accepted || !headers || running) return;
    running = true;
    try {
      for (const mode of ['real','demo']) {
        if (stopped) break;
        const controller = new AbortController();
        active.add(controller);
        const timeout = setTimeout(()=>controller.abort(),15000);
        try {
          const response = await original.call(window, paths[mode]+'?size=500', {method:'GET',headers,credentials:'same-origin',redirect:'error',signal:controller.signal});
          await read(response,mode);
        } finally { clearTimeout(timeout); active.delete(controller); }
      }
    } catch (error) { if (!stopped) send({error:error.name==='AbortError'?'History timed out. Next refresh will retry.':error.name==='SyntaxError'?'History response is not valid JSON. No results synced.':error.message}); }
    finally { running = false; }
  }
  function receive(event) {
    if (event.origin!==origin || event.source!==receiver || event.data?.nonce!==nonce) return;
    if (event.data.type==='trx-history-ready') { accepted=true; send({connected:true,waiting:!headers}); poll(); }
    if (event.data.type==='trx-history-stop') stop();
  }
  function wrapped(input, options) {
    const promise = original.call(this,input,options);
    try {
      // Inspect metadata only. Constructing Request(input) can consume a caller's
      // POST body; non-history fetches must retain their original semantics.
      const request = input instanceof Request ? input : null;
      const url = new URL(request ? request.url : String(input), location.origin);
      const mode = Object.keys(paths).find(key => url.origin===location.origin && url.pathname===paths[key]);
      const method = String(options?.method || request?.method || 'GET').toUpperCase();
      if (mode && method==='GET' && !stopped) {
        headers = new Headers(options?.headers ?? request?.headers);
        if (accepted) promise.then(response=>read(response.clone(),mode)).catch(()=>{if(!stopped)send({error:'History capture failed. Refresh history to retry.'});});
      }
    } catch (_) { /* Observation must never break the provider's own requests. */ }
    return promise;
  }
  window.addEventListener('message',receive);
  window.fetch = wrapped;
  window.__trxHistoryBridge = {stop};
  timer = setInterval(poll,60000);
  alert('Sync window opened. Accept sync there, then open Terminal → History here once. Keep both tabs open.');
}
