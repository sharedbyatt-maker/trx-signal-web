/* Manual Drawing Tools v2 + Fibonacci v2 — isolated overlay for Lightweight Charts v4
   Phase 2 adds per-object Fib levels/extensions/reverse/labels/fill/right-extension.
   Chart, signals, strategy, feed and indicator calculations remain unchanged. */
window.TRXDraw = (() => {
  const STORE_KEY = "trx_drawings_v3"; // keep existing drawings backward-compatible
  const PREF_KEY = "trx_draw_v2_prefs";
  const SYNC_TOKEN_KEY = "trx_draw_sync_token";
  const SAFETY_BACKUP_KEY = "trx_drawings_safety_backup_v1";
  const MAX_CLIENT_DRAWINGS = 500;
  const FIB_LEVELS = [0, 0.236, 0.382, 0.5, 0.618, 0.786, 1];
  const FIB_EXT_LEVELS = [1.272, 1.414, 1.618, 2.0];
  const FIB_COLORS = ["#787b86", "#f23645", "#ff9800", "#089981", "#2962ff", "#ff9800", "#f23645", "#00bcd4", "#9c27b0", "#e91e63", "#607d8b"];
  const DEFAULT_FIB_LEVELS = [...FIB_LEVELS, ...FIB_EXT_LEVELS];

  function normalizeFibLevels(levels) {
    const src = Array.isArray(levels) && levels.length ? levels : FIB_LEVELS;
    const seen = new Set();
    return src.map((x) => typeof x === "number" ? { value: x, enabled: true } : x)
      .filter((x) => x && Number.isFinite(Number(x.value)))
      .map((x) => ({ value: Number(x.value), enabled: x.enabled !== false }))
      .filter((x) => { const k = x.value.toFixed(6); if (seen.has(k)) return false; seen.add(k); return true; })
      .sort((a, b) => a.value - b.value);
  }
  function activeFibLevels(d) { return normalizeFibLevels(d.fibLevels).filter((x) => x.enabled); }
  function fibPrice(d, lv) {
    const p0 = d.points[0].p, p1 = d.points[1].p;
    const a = d.fibReverse ? p1 : p0, b = d.fibReverse ? p0 : p1;
    return a + (b - a) * lv;
  }
  const HIT_PX = 9;
  const HANDLE_PX = 7;
  const HANDLE_TOUCH_PX = 13;
  const SNAP_PX = 12;

  let canvas = null, ctx = null, hintEl = null, wrapEl = null, panelEl = null, api = null;
  let tool = "cursor", color = "#2962ff", drawings = [], placing = null, placeStage = 0;
  let hover = null, selectedId = null, downXY = null, drag = null, restored = false;
  let magnet = true;
  let history = [], historyAt = -1, historyApplying = false, practice = false, liveDrawingState = null;
  let fibMode = 'manual', presets = [], activePreset = null, managerEl = null;
  const syncControls=[];
  const PRESET_KEY = 'trx_drawing_presets_v1';
  const clone = value => JSON.parse(JSON.stringify(value));
  function historySignature(rows) {
    return JSON.stringify(rows.map(d=>({...d,points:d.points.map(p=>({...p,t:p.lb||p.anchorLb?null:p.t}))})));
  }
  function resetHistory() { history = [clone(serializeDrawings())]; historyAt = 0; updateHistoryButtons(); }
  function recordHistory() {
    if(historyApplying)return;
    const rows=serializeDrawings();
    if(historyAt>=0 && historySignature(rows)===historySignature(history[historyAt]))return;
    history=history.slice(0,historyAt+1);history.push(clone(rows));
    if(history.length>101)history.shift();historyAt=history.length-1;updateHistoryButtons();
  }
  function updateHistoryButtons(){
    if($('dt-undo'))$('dt-undo').disabled=historyAt<=0&&!placing;
    if($('dt-redo'))$('dt-redo').disabled=historyAt>=history.length-1;
  }
  function travelHistory(delta){
    if(drag)return;
    const at=historyAt+delta;if(at<0||at>=history.length)return;
    historyAt=at;historyApplying=true;
    try{placing=null;placeStage=0;replaceFromRows(clone(history[at]));saveLocal();queueServerSave();setTool('cursor');}
    finally{historyApplying=false;updateHistoryButtons();updateManager();}
  }
  function redo(){travelHistory(1);}
  async function beginPractice(){
    if(practice)return;
    if(serverPushRequest)await serverPushRequest;
    clearTimeout(serverSyncTimer);serverPushQueued=false;
    liveDrawingState={rows:clone(serializeDrawings()),history:clone(history),at:historyAt};
    practice=true;syncControls.forEach(b=>b.disabled=true);drawings=[];selectedId=null;placing=null;drag=null;setTool('cursor');resetHistory();updateManager();setSyncStatus('REPLAY DRAWINGS · TEMPORARY');redraw();
  }
  function endPractice(){
    if(!practice)return;practice=false;syncControls.forEach(b=>b.disabled=false);
    replaceFromRows(liveDrawingState.rows);history=liveDrawingState.history;historyAt=liveDrawingState.at;liveDrawingState=null;
    setTool('cursor');updateHistoryButtons();updateManager();setSyncStatus(syncToken()?'SYNC READY':'LOCAL ONLY');queueServerSave();redraw();
  }
  let serverRevision = null, serverConflict = false, serverSyncTimer = null, syncStatusEl = null;
  let serverPushRequest = null, serverPushQueued = false;
  async function syncRequest(url, options={}) {
    return TRXNet.run(async signal => {
      const r=await fetch(url,{...options,signal});
      const data=await r.json();
      return {ok:r.ok,status:r.status,data};
    });
  }
  let moveFrame = 0, pendingMove = null;

  const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  const $ = (id) => document.getElementById(id);
  const coarse = () => !!(window.matchMedia && window.matchMedia("(pointer: coarse)").matches);
  const handleRadius = () => coarse() ? HANDLE_TOUCH_PX : HANDLE_PX;

  const HINTS = {
    cursor: "Cursor — select · endpoint ကိုဆွဲပြင် · line ကိုဆွဲရွှေ့ · Del delete",
    trend: "Trend Line — drag or click 2 points · Magnet snaps to candle OHLC",
    ray: "Ray — drag or click 2 points · extends right",
    hline: "S/R Line — click one level",
    vline: "Vertical Line — click one bar",
    rect: "Rectangle — drag or click 2 corners",
    fib: "Fibonacci — drag swing high/low",
  };

  function defaults(d) {
    return {
      ...d,
      width: Number.isFinite(Number(d.width)) ? Math.max(1, Math.min(4, Number(d.width || 2))) : 2,
      style: ["solid", "dashed", "dotted"].includes(d.style) ? d.style : "solid",
      locked: !!d.locked,
      hidden: !!d.hidden,
      extendLeft: !!d.extendLeft,
      extendRight: d.type === "ray" ? d.extendRight !== false : !!d.extendRight,
      fibLevels: d.type === "fib" ? normalizeFibLevels(d.fibLevels) : d.fibLevels,
      fibMode: d.type === "fib" && ["up","down"].includes(d.fibMode) ? d.fibMode : "manual",
      fibReverse: d.type === "fib" ? !!d.fibReverse : false,
      fibLabelSide: d.type === "fib" && d.fibLabelSide === "right" ? "right" : "left",
      fibFill: d.type === "fib" ? (Number.isFinite(Number(d.fibFill ?? .06)) ? Math.max(0, Math.min(0.25, Number(d.fibFill ?? .06))) : .06) : 0,
      fibExtendRight: d.type === "fib" ? !!d.fibExtendRight : false,
    };
  }

  function loadPrefs() {
    try { const p = JSON.parse(localStorage.getItem(PREF_KEY) || "{}"); magnet = p.magnet !== false; fibMode=['manual','up','down'].includes(p.fibMode)?p.fibMode:'manual'; }
    catch (_e) { magnet = true; }
    try {const raw=JSON.parse(localStorage.getItem(PRESET_KEY)||'[]');presets=Array.isArray(raw)?raw.filter(p=>p&&typeof p.id==='string'&&typeof p.name==='string'&&['trend','ray','hline','vline','rect','fib'].includes(p.type)&&p.style&&typeof p.style==='object'&&(!p.style.fibLevels||Array.isArray(p.style.fibLevels)&&p.style.fibLevels.length<=64)).slice(0,20).map(p=>({id:p.id.slice(0,96),name:p.name.slice(0,40),type:p.type,style:presetStyle(defaults({...p.style,type:p.type,color:/^#[0-9a-f]{6}$/i.test(p.style.color)?p.style.color:'#2962ff'}))})):[];}
    catch (_e) { magnet = true; }
  }
  function savePrefs() {
    try { localStorage.setItem(PREF_KEY, JSON.stringify({ magnet, fibMode })); } catch (_e) {}
  }

  function labelOf(t) {
    return api && api.fulls && api.fulls[t - 1] ? api.fulls[t - 1] : null;
  }
  function serializePoint(p) {
    const lb = p.lb || labelOf(p.t);
    const n = api && Array.isArray(api.fulls) ? api.fulls.length : 0;
    const anchorLb = !lb && n > 0 && p.t != null && p.t > n ? api.fulls[n - 1] : null;
    const offset = anchorLb ? Math.max(0, Math.round(Number(p.t) - n)) : null;
    return { p: Number(p.p), lb: lb || null, t: p.t, anchorLb: anchorLb || null, offset };
  }
  function rowsSignature(rows) {
    try { return JSON.stringify(rows || []); } catch (_e) { return ""; }
  }
  function backupLocalSnapshot(reason) {
    try {
      localStorage.setItem(SAFETY_BACKUP_KEY, JSON.stringify({schema:2,reason,created_at:new Date().toISOString(),drawings:serializeDrawings()}));
    } catch (_e) {}
  }
  function sanitizeClientRows(value) {
    if (!Array.isArray(value) || value.length > MAX_CLIENT_DRAWINGS) throw new Error("Invalid drawing list");
    const allowed = new Set(["trend","ray","hline","vline","rect","fib"]);
    return value.map((row) => {
      if (!row || typeof row !== "object" || !allowed.has(row.type)) throw new Error("Invalid drawing type");
      const need = needPoints(row.type);
      if (!Array.isArray(row.points) || row.points.length < need || row.points.length > 2) throw new Error("Invalid drawing points");
      const points = row.points.slice(0, need).map((pt) => {
        if (!pt || pt.p == null || typeof pt.p === "boolean" || !Number.isFinite(Number(pt.p))) throw new Error("Invalid drawing point");
        const t = pt.t == null ? null : Number(pt.t);
        if (t != null && (!Number.isInteger(t) || t < 1 || t > 10000000)) throw new Error("Invalid drawing time");
        const offset = pt.offset == null ? null : Number(pt.offset);
        if (offset != null && (!Number.isInteger(offset) || offset < 0 || offset > 10000)) throw new Error("Invalid future offset");
        return {p:Number(pt.p),t,lb:pt.lb==null?null:String(pt.lb).slice(0,96),anchorLb:pt.anchorLb==null?null:String(pt.anchorLb).slice(0,96),offset};
      });
      const out={...row,id:String(row.id||"").slice(0,96),type:row.type,points};
      if(row.type==="fib" && row.fibLevels!=null && (!Array.isArray(row.fibLevels) || row.fibLevels.length>64)) throw new Error("Invalid Fibonacci levels");
      return out;
    });
  }
  function mergeRowsPreservingLocal(serverRows, localRows) {
    const merged = sanitizeClientRows(serverRows).map((x)=>JSON.parse(JSON.stringify(x)));
    const byId = new Map(merged.map((x,i)=>[x.id,i]));
    sanitizeClientRows(localRows).forEach((local) => {
      const idx = local.id ? byId.get(local.id) : null;
      if (idx == null) { merged.push(local); if(local.id)byId.set(local.id,merged.length-1); return; }
      if (rowsSignature(merged[idx]) === rowsSignature(local)) return;
      // Preserve both versions on a same-id conflict: local keeps the canonical id,
      // server copy is retained under a new id so neither device's edit disappears.
      const serverCopy={...merged[idx],id:`${merged[idx].id||"drawing"}-srv-${uid()}`};
      merged[idx]=local; merged.push(serverCopy);
    });
    if (merged.length > MAX_CLIENT_DRAWINGS) throw new Error("Merged drawing limit exceeded");
    return merged;
  }
  function serializeDrawings() {
    return drawings.map((d) => ({
      id: d.id, type: d.type, color: d.color, width: d.width, style: d.style,
      locked: !!d.locked, hidden: !!d.hidden, extendLeft: !!d.extendLeft,
      extendRight: !!d.extendRight,
      fibLevels: d.type === "fib" ? normalizeFibLevels(d.fibLevels) : undefined,
      fibMode: d.type === "fib" ? d.fibMode : undefined,
      fibReverse: d.type === "fib" ? !!d.fibReverse : undefined,
      fibLabelSide: d.type === "fib" ? d.fibLabelSide : undefined,
      fibFill: d.type === "fib" ? d.fibFill : undefined,
      fibExtendRight: d.type === "fib" ? !!d.fibExtendRight : undefined,
      points: d.points.map(serializePoint),
    }));
  }
  function saveLocal() {
    if(practice)return;
    try { localStorage.setItem(STORE_KEY, JSON.stringify(serializeDrawings())); } catch (_e) {}
  }
  function save() { recordHistory(); saveLocal(); queueServerSave(); updateManager(); }
  function needPoints(type) { return (type === "hline" || type === "vline") ? 1 : 2; }
  function labelIndexMap() {
    if (api && api.labelMap instanceof Map && api.labelMap.size) return api.labelMap;
    if (api && api.fulls && api.fulls.length) return new Map(api.fulls.map((lb, i) => [lb, i + 1]).filter(x => x[0]));
    return new Map(((api && api.labels) || []).map((lb, i) => [lb, i + 1]));
  }
  function replaceFromRows(raw) {
    const map = labelIndexMap(); drawings = [];
    sanitizeClientRows(raw).forEach((row) => {
      const pts = [];
      (row.points || []).forEach((p) => {
        let t = null;
        if (p.lb != null && map.has(p.lb)) t = map.get(p.lb);
        else if (p.anchorLb != null && map.has(p.anchorLb) && Number.isInteger(Number(p.offset))) t = map.get(p.anchorLb) + Number(p.offset);
        else if (p.t != null) t = p.t;
        pts.push({ t, p: Number(p.p), lb: p.lb != null ? p.lb : null, anchorLb:p.anchorLb||null, offset:p.offset==null?null:Number(p.offset) });
      });
      if (pts.length >= needPoints(row.type)) drawings.push(defaults({
        ...row, id: row.id || uid(), color: row.color || "#2962ff",
        points: pts.slice(0, needPoints(row.type)),
      }));
    });
    selectedId = null; updatePanel(); updateManager(); redraw();
  }
  function restore() {
    if (!api || !api.labels) return;
    restored = true;
    try { replaceFromRows(JSON.parse(localStorage.getItem(STORE_KEY) || "[]")); }
    catch (_e) { drawings = []; }
    resetHistory(); updatePanel();
    if (syncToken()) pullServer(false);
  }

  function syncToken() { try { return localStorage.getItem(SYNC_TOKEN_KEY) || ""; } catch (_e) { return ""; } }
  function setSyncToken(v) { try { if(v)localStorage.setItem(SYNC_TOKEN_KEY,v);else localStorage.removeItem(SYNC_TOKEN_KEY); } catch(_e){} }
  function authHeaders(extra={}) { const t=syncToken(); return {...extra,...(t?{"X-Drawings-Token":t}:{})}; }
  function setSyncStatus(txt,bad=false) { if(syncStatusEl){syncStatusEl.textContent=txt;syncStatusEl.style.color=bad?"#f23645":"#9aa0aa";} }
  function queueServerSave() {
    if (practice || !syncToken() || serverRevision == null || serverConflict) return;
    clearTimeout(serverSyncTimer); serverSyncTimer=setTimeout(()=>pushServer(),900);
  }
  async function pushServer() {
    if(serverPushRequest){serverPushQueued=true;return serverPushRequest;}
    serverPushRequest=writeServer();
    try{return await serverPushRequest;}
    finally {
      serverPushRequest=null;
      if(serverPushQueued){serverPushQueued=false;queueServerSave();}
    }
  }
  async function writeServer() {
    if (practice || !syncToken() || serverRevision == null || serverConflict) return false;
    setSyncStatus("SYNCING…");
    try {
      const r=await syncRequest("/api/drawings",{method:"PUT",headers:authHeaders({"Content-Type":"application/json"}),body:JSON.stringify({expected_revision:serverRevision,drawings:serializeDrawings()})});
      const j=r.data;
      if(practice)return false;
      if(r.status===401){setSyncToken("");serverRevision=null;setSyncStatus("AUTH NEEDED",true);return false;}
      if(r.status===409){backupLocalSnapshot("revision-conflict");serverConflict=true;setSyncStatus("CONFLICT · TAP SYNC",true);return false;}
      if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);
      serverRevision=Number(j.revision);serverConflict=false;setSyncStatus(`SYNCED r${serverRevision}`);return true;
    } catch(e){setSyncStatus("LOCAL · SERVER ERROR",true);return false;}
  }
  async function pullServer(interactive=true) {
    if(practice)return false;
    if(serverPushRequest)await serverPushRequest;
    if(!syncToken()&&interactive){const t=window.prompt("Drawing Sync Token");if(!t)return false;setSyncToken(t.trim());}
    if(!syncToken())return false;setSyncStatus("LOADING…");
    try{
      const r=await syncRequest("/api/drawings",{headers:authHeaders()});const j=r.data;
      if(practice)return false;
      if(r.status===401){setSyncToken("");serverRevision=null;setSyncStatus("AUTH NEEDED",true);return false;}
      if(r.status===503){serverRevision=null;setSyncStatus("SERVER SYNC DISABLED",true);return false;}
      if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);
      const remote=sanitizeClientRows(j.drawings||[]), local=serializeDrawings();
      const remoteRev=Number(j.revision||0), same=rowsSignature(remote)===rowsSignature(local);
      const storage=j.storage||{};
      if(storage.recovered_from_backup) setSyncStatus(`RECOVERED ${storage.recovered_from_backup}`);
      if(storage.mode==="host-filesystem" && syncStatusEl) syncStatusEl.title="Server drawings use host filesystem; configure persistent storage and DRAWINGS_STORAGE_DURABLE=1 for redeploy durability.";

      if(serverConflict){
        backupLocalSnapshot("before-conflict-merge");
        if(!interactive){serverRevision=remoteRev;setSyncStatus("CONFLICT · TAP SYNC",true);return false;}
        if(!window.confirm("Server drawings changed on another device. Merge both versions? Cancel keeps your local drawings unchanged.")){serverRevision=remoteRev;setSyncStatus("CONFLICT PRESERVED",true);return false;}
        const merged=mergeRowsPreservingLocal(remote,local);
        serverRevision=remoteRev;serverConflict=false;replaceFromRows(merged);resetHistory();saveLocal();
        setSyncStatus("MERGED · SAVING…");return await pushServer();
      }

      if(remote.length && local.length && !same){
        backupLocalSnapshot("server-diff-detected");
        serverRevision=remoteRev;serverConflict=true;
        if(!interactive){setSyncStatus("DIFF · TAP SYNC",true);return false;}
        if(!window.confirm("Local and server drawings differ. Merge both safely? Cancel keeps local drawings unchanged.")){setSyncStatus("DIFF PRESERVED",true);return false;}
        const merged=mergeRowsPreservingLocal(remote,local);serverConflict=false;replaceFromRows(merged);resetHistory();saveLocal();return await pushServer();
      }

      serverRevision=remoteRev;serverConflict=false;
      if(remote.length){replaceFromRows(remote);resetHistory();saveLocal();setSyncStatus(`PULLED r${serverRevision}`);}
      else if(local.length){setSyncStatus("SERVER EMPTY · UPLOADING");await pushServer();}
      else setSyncStatus(`SYNCED r${serverRevision}`);
      return true;
    }catch(e){setSyncStatus("LOCAL · SERVER ERROR",true);return false;}
  }
  function exportDrawings(){
    const payload={schema:2,exported_at:new Date().toISOString(),drawings:serializeDrawings()};
    const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`trx-drawings-${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }
  function importDrawings(){
    if(practice)return;
    const inp=document.createElement("input");inp.type="file";inp.accept="application/json,.json";inp.onchange=()=>{const f=inp.files&&inp.files[0];if(!f)return;if(f.size>1024*1024){window.alert("Drawing backup is too large");return;}const rd=new FileReader();rd.onload=()=>{try{const j=JSON.parse(String(rd.result||"{}"));const rows=sanitizeClientRows(Array.isArray(j)?j:j.drawings);backupLocalSnapshot("before-import");replaceFromRows(rows);save();setSyncStatus("IMPORTED · SAVED");}catch(_e){window.alert("Invalid drawing backup file");}};rd.readAsText(f);};inp.click();
  }
  async function restoreLocalSafetyBackup(){
    if(practice)return;
    if(serverPushRequest)await serverPushRequest;
    clearTimeout(serverSyncTimer);
    try{const raw=localStorage.getItem(SAFETY_BACKUP_KEY);if(!raw){window.alert("No local safety backup yet");return;}const j=JSON.parse(raw);const rows=sanitizeClientRows(j.drawings||[]);if(!window.confirm(`Restore local safety backup from ${j.created_at||"unknown time"}? Current drawings will be backed up first.`))return;backupLocalSnapshot("before-local-recovery");replaceFromRows(rows);resetHistory();saveLocal();serverConflict=true;setSyncStatus("LOCAL BACKUP RESTORED · SYNC REVIEW",true);}catch(_e){window.alert("Local safety backup is invalid");}
  }
  async function restoreBackup(){
    if(practice)return;
    if(serverPushRequest)await serverPushRequest;
    clearTimeout(serverSyncTimer);
    if(!syncToken()){const t=window.prompt("Drawing Sync Token");if(!t)return;setSyncToken(t.trim());}
    try{const r=await syncRequest("/api/drawings/backups",{headers:authHeaders()});const j=r.data;if(!r.ok)throw new Error();const list=j.backups||[];if(!list.length){window.alert("No server backups yet");return;}const msg=list.map(x=>`r${x.revision} · ${x.count} drawings · ${x.updated_at||""}`).join("\n");const v=window.prompt(`Restore which revision?\n\n${msg}`);if(v==null)return;const rev=Number(String(v).replace(/^r/i,""));if(!Number.isInteger(rev))return;const rr=await syncRequest("/api/drawings/restore",{method:"POST",headers:authHeaders({"Content-Type":"application/json"}),body:JSON.stringify({revision:rev,expected_revision:serverRevision})});const jj=rr.data;if(!rr.ok)throw new Error(jj.error||"restore failed");serverRevision=Number(jj.revision);serverConflict=false;replaceFromRows(jj.drawings||[]);resetHistory();saveLocal();setSyncStatus(`RESTORED → r${serverRevision}`);}catch(e){setSyncStatus("RESTORE FAILED",true);}
  }
  function buildPersistenceToolbar(){
    const host=$("drawing-options-persistence");if(!host)return;const sep=document.createElement("span");sep.className="dt-sep";host.appendChild(sep);
    const mk=(txt,title,fn)=>{const b=document.createElement("button");b.type="button";b.className="dt-btn txt";b.textContent=txt;b.title=title;b.addEventListener("click",fn);host.appendChild(b);return b;};
    syncControls.push(mk("SYNC","Connect/pull/merge server drawings",()=>pullServer(true)),mk("IMPORT","Import validated drawing backup",importDrawings),mk("BACKUPS","Restore a server backup",restoreBackup),mk("LOCAL BKP","Restore latest local safety backup",restoreLocalSafetyBackup));mk("EXPORT","Download drawing backup",exportDrawings);
    syncStatusEl=document.createElement("span");syncStatusEl.style.cssText="font:10px Consolas,monospace;color:#9aa0aa;padding:0 4px";syncStatusEl.textContent=syncToken()?"SYNC READY":"LOCAL ONLY";host.appendChild(syncStatusEl);
  }

  function toXY(pt) {
    if (!api || !pt || pt.t == null || pt.t < 1) return null;
    const scale=api.chart.timeScale();
    const x = scale.timeToCoordinate(pt.t) ?? (pt.t>api.labels.length ? scale.logicalToCoordinate(pt.t-1) : null);
    const y = api.series.priceToCoordinate(pt.p);
    return x == null || y == null ? null : { x, y };
  }
  function xOnly(pt) {
    if (!api || !pt || pt.t == null || pt.t < 1) return null;
    const scale=api.chart.timeScale();
    const x = scale.timeToCoordinate(pt.t) ?? (pt.t>api.labels.length ? scale.logicalToCoordinate(pt.t-1) : null);
    return x == null ? null : { x, y: 0 };
  }
  function nearestOHLC(t, rawP, y) {
    if (!magnet || !api || !Array.isArray(api.bars) || t < 1 || t > api.bars.length) return rawP;
    const b = api.bars[t - 1];
    if (!b) return rawP;
    const vals = [b.o, b.h, b.l, b.c].filter(v => Number.isFinite(v));
    let best = rawP, bestPx = SNAP_PX + 1;
    vals.forEach((v) => {
      const yy = api.series.priceToCoordinate(v);
      if (yy == null) return;
      const d = Math.abs(yy - y);
      if (d < bestPx) { bestPx = d; best = v; }
    });
    return bestPx <= SNAP_PX ? best : rawP;
  }
  function fromXY(x, y, snap = true) {
    if (!api || !api.labels || !api.labels.length) return null;
    const n = api.labels.length;
    const ct = api.chart.timeScale().coordinateToTime(x);
    const logical = ct == null ? api.chart.timeScale().coordinateToLogical(x) : null;
    let t = ct != null && Number.isFinite(Number(ct)) ? Math.round(ct) : logical != null ? Math.round(logical)+1 : n;
    t = Math.max(1, Math.min(n + 12, t));
    let p = api.series.coordinateToPrice(y);
    if (p == null || isNaN(p)) return null;
    if (snap) p = nearestOHLC(t, p, y);
    return { t, p };
  }
  function endpoints(d) {
    const a = d.type === "vline" ? xOnly(d.points[0]) : toXY(d.points[0]);
    const b = d.points.length > 1 ? toXY(d.points[1]) : null;
    return { a, b };
  }
  function distSeg(px, py, a, b) {
    const dx = b.x - a.x, dy = b.y - a.y, len2 = dx * dx + dy * dy;
    let t = len2 ? ((px - a.x) * dx + (py - a.y) * dy) / len2 : 0;
    t = Math.max(0, Math.min(1, t));
    return Math.hypot(px - (a.x + t * dx), py - (a.y + t * dy));
  }
  function extendedEnds(d, a, b) {
    if (!a || !b || !canvas) return { a, b };
    const w = canvas.clientWidth, dx = b.x - a.x, dy = b.y - a.y;
    let aa = a, bb = b;
    if (d.extendLeft && dx !== 0) {
      const k = (0 - a.x) / dx;
      aa = { x: 0, y: a.y + dy * k };
    }
    if ((d.type === "ray" || d.extendRight) && dx !== 0) {
      const k = (w + 40 - a.x) / dx;
      if (k >= 0) bb = { x: w + 40, y: a.y + dy * k };
    }
    return { a: aa, b: bb };
  }
  function dashOf(d) { return d.style === "dashed" ? [8, 5] : d.style === "dotted" ? [2, 4] : []; }
  function setHint(txt) { if (hintEl) hintEl.textContent = txt; }

  function lockChart(lock) {
    if (api) api.chart.applyOptions({ handleScroll: !lock, handleScale: !lock });
    if (wrapEl) {
      wrapEl.style.cursor = "";
      wrapEl.classList.toggle("drawing-active", !!lock);
      wrapEl.classList.toggle("drawing-dragging", !!(lock && drag));
    }
  }
  function setTool(next) {
    if(next!=="cursor")window.TRXChart?.cancelInspect();
    if (placing && tool === next) next = "cursor";
    placing = null; placeStage = 0; drag = null; tool = next;
    if (next !== "cursor") selectedId = null;
    document.querySelectorAll(".dt-btn[data-tool]").forEach((b) => b.classList.toggle("active", b.dataset.tool === next));
    lockChart(next !== "cursor"); setHint(HINTS[next] || HINTS.cursor); updatePanel(); redraw();
  }

  function selected() { return drawings.find(d => d.id === selectedId) || null; }
  function handleHit(px, py) {
    const d = selected();
    if (!d || d.hidden || d.locked) return null;
    const { a, b } = endpoints(d); const r = handleRadius() + 5;
    if (a && Math.hypot(px - a.x, py - a.y) <= r) return { id: d.id, index: 0 };
    if (b && Math.hypot(px - b.x, py - b.y) <= r) return { id: d.id, index: 1 };
    return null;
  }
  function hitTest(px, py) {
    for (let i = drawings.length - 1; i >= 0; i--) {
      const d = drawings[i]; if (d.hidden) continue;
      const { a, b } = endpoints(d); if (!a) continue;
      if (d.type === "hline") { if (Math.abs(py - a.y) <= HIT_PX) return d.id; }
      else if (d.type === "vline") { if (Math.abs(px - a.x) <= HIT_PX) return d.id; }
      else if (d.type === "rect") {
        if (!b) continue;
        const x1 = Math.min(a.x,b.x), x2 = Math.max(a.x,b.x), y1 = Math.min(a.y,b.y), y2 = Math.max(a.y,b.y);
        const nearH = Math.abs(py-y1)<=HIT_PX || Math.abs(py-y2)<=HIT_PX;
        const nearV = Math.abs(px-x1)<=HIT_PX || Math.abs(px-x2)<=HIT_PX;
        if ((nearV && py>=y1-HIT_PX && py<=y2+HIT_PX) || (nearH && px>=x1-HIT_PX && px<=x2+HIT_PX)) return d.id;
      } else if (d.type === "fib") {
        if (!b) continue;
        if (distSeg(px,py,a,b)<=HIT_PX) return d.id;
        for (const it of activeFibLevels(d)) {
          const yy = api.series.priceToCoordinate(fibPrice(d, it.value));
          if (yy != null && Math.abs(py - yy) <= 5) return d.id;
        }
      } else if (b) {
        const ee = extendedEnds(d,a,b);
        if (distSeg(px,py,ee.a,ee.b)<=HIT_PX) return d.id;
      }
    }
    return null;
  }

  function resize() {
    if (!canvas || !wrapEl) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = Math.max(1, Math.round(wrapEl.clientWidth*dpr));
    canvas.height = Math.max(1, Math.round(wrapEl.clientHeight*dpr));
    canvas.style.width = wrapEl.clientWidth+"px"; canvas.style.height = wrapEl.clientHeight+"px";
    ctx.setTransform(dpr,0,0,dpr,0,0); redraw();
  }
  function drawLine(a,b,c,width,dash) {
    ctx.strokeStyle=c; ctx.lineWidth=width; ctx.setLineDash(dash||[]); ctx.beginPath(); ctx.moveTo(a.x,a.y); ctx.lineTo(b.x,b.y); ctx.stroke(); ctx.setLineDash([]);
  }
  function priceLabel(y,txt,c) {
    if (!Number.isFinite(y) || y < 0 || y > canvas.clientHeight) return;
    const w=canvas.clientWidth; ctx.font="10px Consolas, monospace"; const tw=ctx.measureText(txt).width+10;
    ctx.fillStyle=c; ctx.globalAlpha=.85; ctx.fillRect(w-tw-58,Math.max(0,Math.min(canvas.clientHeight-16,y-8)),tw,16);
    ctx.globalAlpha=1; ctx.fillStyle="#fff"; ctx.textBaseline="middle"; ctx.fillText(txt,w-tw-53,Math.max(8,Math.min(canvas.clientHeight-8,y+1)));
  }
  function drawHandle(pt, locked) {
    if (!pt) return; const r=handleRadius();
    ctx.save(); ctx.fillStyle=locked?"#787b86":"#fff"; ctx.strokeStyle=locked?"#aaa":"#2962ff"; ctx.lineWidth=2;
    ctx.beginPath(); ctx.arc(pt.x,pt.y,r,0,Math.PI*2); ctx.fill(); ctx.stroke(); ctx.restore();
  }
  function renderOne(d, ghost=false) {
    if (d.hidden && !ghost) return;
    const w=canvas.clientWidth,h=canvas.clientHeight,sel=d.id===selectedId&&!ghost,c=d.color||"#2962ff";
    const lw=ghost?2:(d.width||2)+(sel?1:0), dash=dashOf(d), {a,b}=endpoints(d);
    ctx.save(); if (d.locked) ctx.globalAlpha=.72;
    if (d.type==="hline"&&a) {
      ctx.globalAlpha=d.locked?.08:.12; ctx.fillStyle=c; ctx.fillRect(0,a.y-6,w,12); ctx.globalAlpha=d.locked?.72:1;
      drawLine({x:0,y:a.y},{x:w,y:a.y},c,lw,dash); priceLabel(a.y,d.points[0].p.toFixed(1),c);
    } else if (d.type==="vline"&&a) drawLine({x:a.x,y:0},{x:a.x,y:h},c,lw,dash);
    else if (a&&b) {
      if (d.type==="rect") {
        ctx.strokeStyle=c; ctx.lineWidth=lw; ctx.setLineDash(dash); ctx.strokeRect(Math.min(a.x,b.x),Math.min(a.y,b.y),Math.abs(b.x-a.x),Math.abs(b.y-a.y)); ctx.setLineDash([]);
        ctx.globalAlpha=.08; ctx.fillStyle=c; ctx.fillRect(Math.min(a.x,b.x),Math.min(a.y,b.y),Math.abs(b.x-a.x),Math.abs(b.y-a.y)); ctx.globalAlpha=d.locked?.72:1;
      } else if (d.type==="fib") {
        const x1=Math.min(a.x,b.x), x2=Math.max(a.x,b.x);
        const right = d.fibExtendRight ? w : Math.min(w, x2 + 60);
        const levels = activeFibLevels(d);
        const rendered = levels.map((it,i) => ({
          value: it.value, price: fibPrice(d,it.value), color: FIB_COLORS[i % FIB_COLORS.length] || c
        })).map((it) => ({ ...it, y: api.series.priceToCoordinate(it.price) })).filter((it) => it.y != null);
        if (d.fibFill > 0 && rendered.length > 1) {
          const sorted = [...rendered].sort((u,v)=>u.y-v.y);
          ctx.save(); ctx.globalAlpha = d.fibFill;
          for (let i=0;i<sorted.length-1;i++) {
            ctx.fillStyle = sorted[i].color;
            ctx.fillRect(x1, sorted[i].y, Math.max(1,right-x1), Math.max(0,sorted[i+1].y-sorted[i].y));
          }
          ctx.restore();
        }
        rendered.forEach((it)=>{
          drawLine({x:x1,y:it.y},{x:right,y:it.y},it.color,1,[5,4]);
          const levelTxt = Number.isInteger(it.value) ? it.value.toFixed(1) : it.value.toFixed(3).replace(/0+$/,"").replace(/\.$/,"");
          const txt = levelTxt + "  " + it.price.toFixed(1);
          ctx.font="10px Consolas, monospace"; ctx.fillStyle=it.color; ctx.textBaseline="bottom";
          if (d.fibLabelSide === "right") {
            const tw=ctx.measureText(txt).width; ctx.fillText(txt,Math.max(x1+2,right-tw-4),Math.max(10,it.y-2));
          } else ctx.fillText(txt,x1+4,Math.max(10,it.y-2));
        });
        drawLine(a,b,"rgba(209,212,220,.55)",1,[]);
      } else { const ee=extendedEnds(d,a,b); drawLine(ee.a,ee.b,c,lw,dash); }
    }
    ctx.restore();
    if ((sel||ghost)&&!d.hidden) { drawHandle(a,d.locked); if (b) drawHandle(b,d.locked); }
  }
  function redraw() {
    if(!ctx||!canvas)return; ctx.clearRect(0,0,canvas.clientWidth,canvas.clientHeight); if(!api)return;
    drawings.forEach(d=>renderOne(d));
    if(placing){ if(hover&&placing.points.length===1){ const cur=fromXY(hover.x,hover.y,true); renderOne({...placing,id:"_ghost",points:[placing.points[0],cur||placing.points[0]]},true);} else renderOne(placing,true); }
    // One-point tools get a live preview before click, so placing an S/R or
    // vertical marker feels anchored to the pointer instead of appearing late.
    if(hover && (tool==="hline" || tool==="vline")){
      const cur=fromXY(hover.x,hover.y,true);
      if(cur) renderOne(defaults({id:"_hover",type:tool,color,points:[{...cur,lb:labelOf(cur.t)}],width:2,style:"solid"}),true);
    }
  }

  function commit(type,pts,c) {
    if(drawings.length>=MAX_CLIENT_DRAWINGS){setHint("Drawing limit: 500 · export and remove unused drawings");return;}
    const style=activePreset&&activePreset.type===type?activePreset.style:{};
    const d=defaults({id:uid(),type,color:c||color,points:pts,width:2,style:"solid",locked:false,hidden:false,extendLeft:false,extendRight:type==="ray",fibLevels:type==="fib"?FIB_LEVELS.map(value=>({value,enabled:true})):undefined,...clone(style)});
    if(type==='fib'){const mode=fibMode!=='manual'?fibMode:d.fibMode;if(mode==='up'||mode==='down')orientFib(d,mode);}
    d.points.forEach(p=>{p.lb=labelOf(p.t)||p.lb;if(!p.lb&&p.t>api.fulls.length){p.anchorLb=api.fulls.at(-1);p.offset=p.t-api.fulls.length;}}); drawings.push(d); selectedId=d.id; save(); updatePanel();
  }
  function undo(){ if(placing){placing=null;placeStage=0;setTool("cursor");redraw();return;} travelHistory(-1); }
  function clearAll(){ drawings=[]; placing=null; selectedId=null; drag=null; save(); updatePanel(); redraw(); }
  function deleteSelected(){ if(!selectedId)return; drawings=drawings.filter(d=>d.id!==selectedId); selectedId=null; save(); updatePanel(); redraw(); }
  function duplicateSelected(){ const d=selected(); if(!d||drawings.length>=MAX_CLIENT_DRAWINGS)return; const cp=defaults(JSON.parse(JSON.stringify(d))); cp.id=uid(); cp.locked=false; cp.hidden=false; cp.points=cp.points.map(p=>({ ...p,t:p.t==null?p.t:p.t+1,p:Number.isFinite(p.p)?p.p+.5:p.p,lb:null })); cp.points.forEach(p=>{p.lb=labelOf(p.t)||null;}); drawings.push(cp); selectedId=cp.id; save(); updatePanel(); redraw(); }
  function toggleLock(){ const d=selected(); if(!d)return; d.locked=!d.locked; drag=null; save(); updatePanel(); redraw(); }
  function toggleHide(){ const d=selected(); if(!d)return; d.hidden=true; selectedId=null; save(); updatePanel(); redraw(); }
  function showAll(){ drawings.forEach(d=>d.hidden=false); save(); updatePanel(); redraw(); }
  function setSelectedStyle(key,value){ const d=selected(); if(!d)return; if(key==="width") d.width=Math.max(1,Math.min(4,Number(value)||2)); else if(key==="style"&&["solid","dashed","dotted"].includes(value)) d.style=value; else if(key==="extendLeft") d.extendLeft=!!value; else if(key==="extendRight") d.extendRight=!!value; save(); updatePanel(); redraw(); }

  function ensureFibLevel(d,value,enabled=true){
    if(!d||d.type!=="fib"||!Number.isFinite(Number(value)))return;
    const v=Number(value); d.fibLevels=normalizeFibLevels(d.fibLevels);
    const found=d.fibLevels.find(x=>Math.abs(x.value-v)<1e-9);
    if(found) found.enabled=enabled; else if(d.fibLevels.length<64)d.fibLevels.push({value:v,enabled});
    d.fibLevels=normalizeFibLevels(d.fibLevels);
  }
  function setFibLevelEnabled(value,enabled){const d=selected();if(!d||d.type!=="fib")return;ensureFibLevel(d,value,enabled);save();updateFibPanel();redraw();}
  function removeCustomFibLevel(value){const d=selected();if(!d||d.type!=="fib")return;const fixed=new Set(DEFAULT_FIB_LEVELS.map(v=>v.toFixed(6)));d.fibLevels=normalizeFibLevels(d.fibLevels).filter(x=>fixed.has(x.value.toFixed(6))||Math.abs(x.value-value)>1e-9);save();updateFibPanel();redraw();}
  function setFibOption(key,value){const d=selected();if(!d||d.type!=="fib")return;
    if(key==="reverse"){d.fibMode='manual';d.fibReverse=!!value;}
    else if(key==="label")d.fibLabelSide=value==="right"?"right":"left";
    else if(key==="fill")d.fibFill=Math.max(0,Math.min(.25,Number(value)||0));
    else if(key==="extendRight")d.fibExtendRight=!!value;
    save();updateFibPanel();redraw();
  }
  let fibPanelEl=null;
  function fibMiniButton(text,title){const b=document.createElement("button");b.type="button";b.textContent=text;b.title=title||text;b.style.cssText="height:25px;padding:0 7px;border:1px solid #363a45;border-radius:4px;background:#1e222d;color:#d1d4dc;font:10px Consolas,monospace;cursor:pointer";return b;}
  function buildFibPanel(){
    fibPanelEl=document.createElement("div");fibPanelEl.id="fib-v2-panel";
    fibPanelEl.style.cssText="position:absolute;z-index:31;right:8px;top:72px;display:none;min-width:280px;max-width:min(96%,520px);padding:8px;background:rgba(19,23,34,.98);border:1px solid #434651;border-radius:7px;box-shadow:0 6px 22px rgba(0,0,0,.32);color:#d1d4dc;font:11px Consolas,monospace";
    wrapEl.appendChild(fibPanelEl);
  }
  function updateFibPanel(){
    if(!fibPanelEl)return;const d=selected();if(!d||d.type!=="fib"){fibPanelEl.style.display="none";fibPanelEl.innerHTML="";return;}
    fibPanelEl.style.display="block";fibPanelEl.innerHTML="";
    const title=document.createElement("div");title.textContent="FIBONACCI v2";title.style.cssText="font-weight:700;margin-bottom:7px;color:#fff";fibPanelEl.appendChild(title);
    fibPanelEl.appendChild(fibModeControl(d));
    const levelWrap=document.createElement("div");levelWrap.style.cssText="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:7px";
    const levels=normalizeFibLevels(d.fibLevels);const fixed=[...DEFAULT_FIB_LEVELS];
    fixed.forEach((lv)=>{const found=levels.find(x=>Math.abs(x.value-lv)<1e-9);const lab=document.createElement("label");lab.style.cssText="display:flex;align-items:center;gap:3px;padding:2px 4px;border:1px solid #363a45;border-radius:4px";const cb=document.createElement("input");cb.type="checkbox";cb.checked=!!(found&&found.enabled);cb.addEventListener("change",()=>setFibLevelEnabled(lv,cb.checked));lab.append(cb,document.createTextNode(String(lv)));levelWrap.appendChild(lab);});
    fibPanelEl.appendChild(levelWrap);
    const customTitle=document.createElement("div");customTitle.textContent="CUSTOM LEVELS";customTitle.style.cssText="margin:4px 0;color:#9aa0aa";fibPanelEl.appendChild(customTitle);
    const customs=levels.filter(x=>!fixed.some(v=>Math.abs(v-x.value)<1e-9));
    const customRow=document.createElement("div");customRow.style.cssText="display:flex;flex-wrap:wrap;gap:5px;margin-bottom:6px";
    customs.forEach((it)=>{const chip=fibMiniButton(`${it.enabled?"✓":"○"} ${it.value} ×`,`Toggle / remove custom level`);chip.addEventListener("click",(ev)=>{if(ev.shiftKey)removeCustomFibLevel(it.value);else setFibLevelEnabled(it.value,!it.enabled);});customRow.appendChild(chip);});fibPanelEl.appendChild(customRow);
    const addRow=document.createElement("div");addRow.style.cssText="display:flex;gap:5px;margin-bottom:8px";const inp=document.createElement("input");inp.type="number";inp.step="0.001";inp.placeholder="custom e.g. 2.618";inp.style.cssText="width:145px;height:25px;background:#11151d;color:#fff;border:1px solid #363a45;border-radius:4px;padding:0 5px";const add=fibMiniButton("+ ADD","Add custom Fib level");add.addEventListener("click",()=>{const v=Number(inp.value);if(inp.value.trim()&&Number.isFinite(v)){ensureFibLevel(d,v,true);save();updateFibPanel();redraw();}});addRow.append(inp,add);fibPanelEl.appendChild(addRow);
    const opts=document.createElement("div");opts.style.cssText="display:flex;flex-wrap:wrap;gap:5px;align-items:center";
    const rev=fibMiniButton(d.fibReverse?"REVERSE ✓":"REVERSE","Reverse Fib anchors");rev.addEventListener("click",()=>setFibOption("reverse",!d.fibReverse));
    const side=fibMiniButton(`LABEL ${d.fibLabelSide==="right"?"RIGHT":"LEFT"}`,"Toggle label side");side.addEventListener("click",()=>setFibOption("label",d.fibLabelSide==="right"?"left":"right"));
    const ext=fibMiniButton(d.fibExtendRight?"EXT RIGHT ✓":"EXT RIGHT","Extend Fib levels to right edge");ext.addEventListener("click",()=>setFibOption("extendRight",!d.fibExtendRight));
    const fill=document.createElement("input");fill.type="range";fill.min="0";fill.max="0.25";fill.step="0.01";fill.value=String(d.fibFill??.06);fill.title="Background opacity";fill.addEventListener("input",()=>{d.fibFill=Number(fill.value);fillLab.textContent=`FILL ${Math.round(d.fibFill*100)}%`;saveLocal();queueServerSave();redraw();});fill.addEventListener("change",()=>{recordHistory();updateManager();});
    const fillLab=document.createElement("span");fillLab.textContent=`FILL ${Math.round((d.fibFill||0)*100)}%`;
    const close=fibMiniButton("DONE","Close Fib settings");close.addEventListener("click",()=>{fibPanelEl.style.display="none";});
    opts.append(rev,side,ext,fillLab,fill,close);fibPanelEl.appendChild(opts);layoutFibPanel();
  }

  function layoutFibPanel(){
    if(!fibPanelEl||!panelEl||!wrapEl)return;
    const top=panelEl.offsetTop+panelEl.offsetHeight+8;
    fibPanelEl.style.top=top+"px";
    fibPanelEl.style.minWidth="0";
    fibPanelEl.style.boxSizing="border-box";
    const bottom=window.matchMedia("(max-width:600px)").matches&&!$("draw-tools")?.classList.contains("collapsed")?64:8;
    fibPanelEl.style.maxHeight=Math.max(32,wrapEl.clientHeight-top-bottom)+"px";
    fibPanelEl.style.overflowY="auto";
  }

  function panelButton(text,id,title){ const b=document.createElement("button"); b.type="button"; b.id=id; b.textContent=text; b.title=title||text; b.style.cssText="height:26px;padding:0 7px;border:1px solid #363a45;border-radius:4px;background:#1e222d;color:#d1d4dc;font:11px Consolas,monospace;cursor:pointer"; return b; }
  function buildPanel(){
    panelEl=document.createElement("div"); panelEl.id="draw-v2-panel"; panelEl.style.cssText="position:absolute;z-index:25;right:8px;top:36px;display:none;align-items:center;gap:5px;flex-wrap:wrap;max-width:min(96%,620px);padding:5px 6px;background:rgba(19,23,34,.96);border:1px solid #363a45;border-radius:6px;box-shadow:0 4px 16px rgba(0,0,0,.25)";
    const width=document.createElement("select"); width.id="dt-v2-width"; width.title="Line width"; width.style.cssText="height:26px;background:#1e222d;color:#d1d4dc;border:1px solid #363a45;border-radius:4px;font:11px Consolas"; [1,2,3,4].forEach(v=>{const o=document.createElement("option");o.value=v;o.textContent=`${v}px`;width.appendChild(o);});
    const style=document.createElement("select"); style.id="dt-v2-style"; style.title="Line style"; style.style.cssText=width.style.cssText; [["solid","Solid"],["dashed","Dash"],["dotted","Dot"]].forEach(([v,t])=>{const o=document.createElement("option");o.value=v;o.textContent=t;style.appendChild(o);});
    const left=panelButton("← EXT","dt-v2-left","Extend left"), right=panelButton("EXT →","dt-v2-right","Extend right"), lock=panelButton("🔒","dt-v2-lock","Lock / unlock"), hide=panelButton("👁−","dt-v2-hide","Hide selected"), dup=panelButton("⧉","dt-v2-dup","Duplicate selected"), fib=panelButton("FIB ⚙","dt-v2-fib","Fibonacci v2 settings"), show=panelButton("SHOW HIDDEN","dt-v2-show","Show all hidden drawings"), mag=panelButton("MAGNET","dt-v2-mag","Snap endpoints to candle OHLC");
    panelEl.append(width,style,left,right,lock,hide,dup,fib,show,mag); wrapEl.appendChild(panelEl);
    width.addEventListener("change",()=>setSelectedStyle("width",width.value)); style.addEventListener("change",()=>setSelectedStyle("style",style.value));
    left.addEventListener("click",()=>{const d=selected();if(d)setSelectedStyle("extendLeft",!d.extendLeft);}); right.addEventListener("click",()=>{const d=selected();if(d)setSelectedStyle("extendRight",!d.extendRight);}); lock.addEventListener("click",toggleLock); hide.addEventListener("click",toggleHide); dup.addEventListener("click",duplicateSelected); fib.addEventListener("click",()=>{const d=selected();if(d&&d.type==="fib"){updateFibPanel();fibPanelEl.style.display="block";}}); show.addEventListener("click",showAll); mag.addEventListener("click",toggleMagnet);
  }
  function toggleMagnet(){magnet=!magnet;savePrefs();updatePanel();}
  function useCursor(){if(drag?.origData){const d=selected();if(d)d.points=clone(drag.origData);}placing=null;drag=null;selectedId=null;setTool('cursor');updatePanel();redraw();}
  function updatePanel(){
    const globalMag=$("chart-magnet");if(globalMag){globalMag.textContent="Magnet "+(magnet?"ON":"OFF");globalMag.setAttribute("aria-pressed",String(magnet));}
    if(!panelEl)return; const d=selected(), hidden=drawings.some(x=>x.hidden); panelEl.style.display=(d||hidden)?"flex":"none";
    const q=(id)=>document.getElementById(id), active=(el,on)=>{if(!el)return;el.style.background=on?"#2962ff":"#1e222d";el.style.color=on?"#fff":"#d1d4dc";};
    const w=q("dt-v2-width"),s=q("dt-v2-style"); if(w)w.disabled=!d;if(s)s.disabled=!d;if(d&&w)w.value=String(d.width||2);if(d&&s)s.value=d.style||"solid";
    ["dt-v2-left","dt-v2-right","dt-v2-lock","dt-v2-hide","dt-v2-dup"].forEach(id=>{const e=q(id);if(e)e.disabled=!d;});
    const fibBtn=q("dt-v2-fib");if(fibBtn){fibBtn.disabled=!(d&&d.type==="fib");fibBtn.style.display=(d&&d.type==="fib")?"inline-block":"none";}
    if(!(d&&d.type==="fib")&&fibPanelEl)fibPanelEl.style.display="none";
    active(q("dt-v2-left"),!!(d&&d.extendLeft)); active(q("dt-v2-right"),!!(d&&(d.type==="ray"||d.extendRight))); active(q("dt-v2-lock"),!!(d&&d.locked)); active(q("dt-v2-mag"),magnet); const sh=q("dt-v2-show");if(sh)sh.style.display=hidden?"inline-block":"none";
    if(d)setHint(`${d.type.toUpperCase()} selected${d.locked?" · LOCKED":""} · drag handles to edit endpoints · Magnet ${magnet?"ON":"OFF"}`); else setHint(HINTS[tool]||HINTS.cursor);
    updateHistoryButtons();layoutFibPanel();
  }


  function orientFib(d,mode){
    d.fibMode=mode;
    // Ratios measure backward from the swing end: up ends at high; down ends at low.
    d.fibReverse=mode==='up'?d.points[0].p<d.points[1].p:d.points[0].p>d.points[1].p;
  }
  function fibModeControl(d){
    const lab=document.createElement('label');lab.className='study-field';lab.textContent='FIB MODE ';
    const sel=document.createElement('select');sel.setAttribute('aria-label',d?'Selected Fibonacci mode':'New Fibonacci mode');
    [['manual','Manual / Reverse'],['up','တက်လှိုင်း ပြန်ကျမှု'],['down','ကျလှိုင်း ပြန်တက်မှု']].forEach(([value,text])=>{const o=document.createElement('option');o.value=value;o.textContent=text;sel.append(o);});
    sel.value=d?(d.fibMode||'manual'):fibMode;
    sel.addEventListener('change',()=>{if(d){if(sel.value==='manual')d.fibMode='manual';else orientFib(d,sel.value);save();updateFibPanel();redraw();}else{fibMode=sel.value;savePrefs();setHint(fibMode==='manual'?HINTS.fib:'Fibonacci · swing အစနှင့် အဆုံးကိုဆွဲပါ · 0 / 1 အလိုအလျောက်ချိန်ပေးမည်');}});
    lab.append(sel);return lab;
  }
  function presetStyle(d){
    const out={};['color','width','style','extendLeft','extendRight','fibLevels','fibReverse','fibLabelSide','fibFill','fibExtendRight','fibMode'].forEach(k=>{if(d[k]!==undefined)out[k]=clone(d[k]);});return out;
  }
  function persistPresets(){try{localStorage.setItem(PRESET_KEY,JSON.stringify(presets));return true;}catch(_e){setHint('Preset မသိမ်းနိုင်ပါ · browser storage ကို စစ်ပါ');return false;}}
  function buildManager(){
    const host=$('draw-tools');if(!host)return;
    const list=panelButton('☷','dt-list','Drawing list and saved presets');list.className='dt-btn txt';list.setAttribute('aria-label','Drawing list and saved presets');host.append(list);$('drawing-options-controls')?.append(fibModeControl(null));
    const options=$('drawing-options'),toggle=$('dt-options');
    const closeOptions=()=>{options.hidden=true;toggle.setAttribute('aria-expanded','false');};
    toggle.addEventListener('click',()=>{const open=options.hidden;closeOptions();if(open){options.hidden=false;toggle.setAttribute('aria-expanded','true');managerEl.hidden=true;list.setAttribute('aria-expanded','false');if(fibPanelEl)fibPanelEl.style.display='none';}});
    $('dt-options-close').addEventListener('click',closeOptions);
    document.addEventListener('keydown',ev=>{if(ev.key==='Escape'){closeOptions();managerEl.hidden=true;list.setAttribute('aria-expanded','false');}});
    $('dt-toggle-btn').addEventListener('click',()=>{window.TRXChart?.cancelInspect();if(host.classList.contains('collapsed')){closeOptions();managerEl.hidden=true;list.setAttribute('aria-expanded','false');if(fibPanelEl)fibPanelEl.style.display='none';setTool('cursor');}});
    managerEl=document.createElement('section');managerEl.id='drawing-manager';managerEl.className='draw-drawer';managerEl.hidden=true;managerEl.setAttribute('aria-label','Drawing list and presets');wrapEl.append(managerEl);
    list.addEventListener('click',()=>{managerEl.hidden=!managerEl.hidden;list.setAttribute('aria-expanded',String(!managerEl.hidden));if(!managerEl.hidden){closeOptions();if(fibPanelEl)fibPanelEl.style.display='none';updateManager();}});
    list.setAttribute('aria-expanded','false');
  }
  function updateManager(){
    if(!managerEl||managerEl.hidden)return;
    managerEl.replaceChildren();
    const header=document.createElement('div');header.className='draw-row';const title=document.createElement('strong');title.textContent=practice?'REPLAY DRAWINGS · temporary':'DRAWINGS · '+drawings.length;
    const close=panelButton('Close','dt-list-close');close.addEventListener('click',()=>{managerEl.hidden=true;$('dt-list').setAttribute('aria-expanded','false');});header.append(title,close);managerEl.append(header);
    const presetRow=document.createElement('div');presetRow.className='draw-row';
    const sel=document.createElement('select');sel.id='drawing-preset';sel.setAttribute('aria-label','Saved drawing preset');const empty=document.createElement('option');empty.value='';empty.textContent='Saved presets';sel.append(empty);
    presets.forEach(p=>{const o=document.createElement('option');o.value=p.id;o.textContent=p.name+' · '+p.type;sel.append(o);});sel.value=activePreset?.id||'';
    sel.addEventListener('change',()=>{activePreset=presets.find(p=>p.id===sel.value)||null;const d=selected();if(activePreset&&d&&d.type===activePreset.type){Object.assign(d,clone(activePreset.style));if(d.type==='fib'&&d.fibMode&&d.fibMode!=='manual')orientFib(d,d.fibMode);save();updatePanel();redraw();}});
    const saveButton=panelButton('Save selected preset','dt-preset-save');saveButton.disabled=!selected();saveButton.addEventListener('click',()=>{const d=selected();if(!d)return;const name=window.prompt('Preset name (max 40 characters)');if(!name?.trim())return;const p={id:uid(),name:name.trim().slice(0,40),type:d.type,style:presetStyle(d)};if(presets.length>=20){setHint('Preset limit: 20');return;}presets.push(p);activePreset=p;persistPresets();updateManager();});
    const remove=panelButton('Remove preset','dt-preset-remove');remove.disabled=!activePreset;remove.addEventListener('click',()=>{if(!activePreset)return;presets=presets.filter(p=>p.id!==activePreset.id);activePreset=null;persistPresets();updateManager();});
    presetRow.append(sel,saveButton,remove);managerEl.append(presetRow);
    const note=document.createElement('p');note.className='draw-note';note.textContent='Preset ကို ရွေးပြီး same tool ဖြင့် အသစ်ဆွဲနိုင်သည်။ Local browser only · Export drawings for backup.';managerEl.append(note);
    const rows=document.createElement('div');rows.className='drawing-list';
    if(!drawings.length){const empty=document.createElement('p');empty.textContent='Drawing မရှိသေးပါ။ Chart ပေါ်မှာ tool တစ်ခုရွေးပြီး ဆွဲပါ။';rows.append(empty);}
    drawings.forEach((d,i)=>{
      const row=document.createElement('div');row.className='draw-row drawing-row';row.dataset.drawingId=d.id;
      const choose=panelButton(`${d.type.toUpperCase()} ${i+1}${d.hidden?' · hidden':''}${d.locked?' · locked':''}`,'');choose.setAttribute('aria-label',`Select ${d.type} ${i+1}`);choose.addEventListener('click',()=>{selectedId=d.id;setTool('cursor');updatePanel();redraw();updateManager();const ts=d.points.map(p=>p.t).filter(Number.isFinite);if(ts.length){const mid=(Math.min(...ts)+Math.max(...ts))/2;const range=api.chart.timeScale().getVisibleLogicalRange();const half=Math.max(15,((range?.to||100)-(range?.from||0))/2);api.chart.timeScale().setVisibleLogicalRange({from:mid-half,to:mid+half});}});
      const hide=panelButton(d.hidden?'Show':'Hide','');hide.setAttribute('aria-label',`${d.hidden?'Show':'Hide'} ${d.type} ${i+1}`);hide.addEventListener('click',()=>{d.hidden=!d.hidden;save();updatePanel();redraw();});
      const lock=panelButton(d.locked?'Unlock':'Lock','');lock.setAttribute('aria-label',`${d.locked?'Unlock':'Lock'} ${d.type} ${i+1}`);lock.addEventListener('click',()=>{d.locked=!d.locked;save();updatePanel();redraw();});
      const del=panelButton('Delete','');del.setAttribute('aria-label',`Delete ${d.type} ${i+1}`);del.addEventListener('click',()=>{selectedId=d.id;deleteSelected();});row.append(choose,hide,lock,del);rows.append(row);
    });managerEl.append(rows);
  }
  function localXY(ev){const r=canvas.getBoundingClientRect();return{x:ev.clientX-r.left,y:ev.clientY-r.top};}
  function onDown(x,y,ev){
    downXY={x,y};
    if(tool==="cursor"){
      const hh=handleHit(x,y);
      if(hh){const d=selected();drag={id:hh.id,mode:"handle",index:hh.index,origData:JSON.parse(JSON.stringify(d.points))};lockChart(true);ev.preventDefault();ev.stopPropagation();redraw();return;}
      const id=hitTest(x,y);
      if(id){selectedId=id;const d=selected();if(d&&!d.locked){const ptsPx=d.points.map(p=>d.type==="vline"?xOnly(p):toXY(p));if(ptsPx.every(Boolean)){drag={id,mode:"move",start:{x,y},origPx:ptsPx,origData:JSON.parse(JSON.stringify(d.points))};lockChart(true);ev.preventDefault();}}ev.stopPropagation();updatePanel();redraw();}
      else if(selectedId){selectedId=null;updatePanel();redraw();}
      return;
    }
    if(!placing&&tool!=="hline"&&tool!=="vline"){const pt=fromXY(x,y,true);if(pt){placing=defaults({type:tool,color,points:[{...pt,lb:labelOf(pt.t)}],width:2,style:"solid",extendRight:tool==="ray"});placeStage=1;updateHistoryButtons();redraw();}}
  }
  function onMove(x,y){
    hover={x,y};
    if(drag){const d=drawings.find(z=>z.id===drag.id);if(!d||d.locked){drag=null;lockChart(tool!=="cursor");return;}
      if(drag.mode==="handle"){
        const np=fromXY(x,y,true);if(np){if(d.type==="vline")d.points[drag.index]={...d.points[drag.index],t:np.t,lb:labelOf(np.t)||null};else if(d.type==="hline")d.points[0]={...d.points[0],p:np.p};else d.points[drag.index]={t:np.t,p:np.p,lb:labelOf(np.t)||null};redraw();}return;
      }
      const dx=x-drag.start.x,dy=y-drag.start.y;d.points=drag.origPx.map((o,i)=>{if(d.type==="hline"){const p=api.series.coordinateToPrice(o.y+dy);return{...drag.origData[i],p:(p==null||isNaN(p))?drag.origData[i].p:p};}const np=fromXY(o.x+dx,d.type==="vline"?0:o.y+dy,false);if(!np)return drag.origData[i];return d.type==="vline"?{...drag.origData[i],t:np.t,lb:labelOf(np.t)||null}:{t:np.t,p:np.p,lb:labelOf(np.t)||null};});redraw();return;
    }
    if(placing&&placing.points.length===1)redraw();
    else if(tool==="hline"||tool==="vline")redraw();
    else if(tool==="cursor")redraw();
  }
  function finishTwoPoint(pt){placing.points.push({...pt,lb:labelOf(pt.t)});commit(placing.type,placing.points,placing.color);placing=null;placeStage=0;setTool("cursor");redraw();}
  function onUp(x,y){
    const moved=downXY?Math.hypot(x-downXY.x,y-downXY.y):0;
    if(drag){const d=selected();if(d&&d.type==='fib'&&d.fibMode&&d.fibMode!=='manual')orientFib(d,d.fibMode);if(moved>1)save();drag=null;downXY=null;lockChart(false);updatePanel();redraw();return;}
    const wasDown=!!downXY;downXY=null;if(tool==="cursor")return;const pt=fromXY(x,y,true);if(!pt)return;
    if(tool==="hline"||tool==="vline"){if(!wasDown||moved>6)return;commit(tool,[{t:pt.t,p:tool==="hline"?pt.p:0,lb:labelOf(pt.t)}]);setTool("cursor");redraw();return;}
    if(!placing)return;if(moved>8)finishTwoPoint(pt);else if(placeStage===1&&wasDown)placeStage=2;else if(placeStage===2&&wasDown){const a0=toXY(placing.points[0]);if(!(a0&&Math.hypot(x-a0.x,y-a0.y)<3))finishTwoPoint(pt);}
  }

  function bindEvents(){
    const control=ev=>!!ev.target.closest?.('#draw-v2-panel,#fib-v2-panel,#drawing-manager,#drawing-options,#draw-tools,button,input,select,textarea,a');
    const clearMove=()=>{if(moveFrame)cancelAnimationFrame(moveFrame);moveFrame=0;pendingMove=null;};
    wrapEl.addEventListener("pointerdown",ev=>{if(ev.button!==0||control(ev)||window.TRXChart?.isInspecting())return;const p=localXY(ev);if(tool!=="cursor"||handleHit(p.x,p.y)||hitTest(p.x,p.y)){try{wrapEl.setPointerCapture(ev.pointerId);}catch(_e){} ev.stopPropagation();}onDown(p.x,p.y,ev);},true);
    // Coalesce high-frequency mouse/stylus events to one drawing update per
    // animation frame. This removes redundant coordinate conversion + full
    // overlay redraws while preserving the latest pointer position.
    wrapEl.addEventListener("pointermove",ev=>{
      if((control(ev)||window.TRXChart?.isInspecting())&&!drag)return;
      pendingMove=localXY(ev);
      if(moveFrame)return;
      moveFrame=requestAnimationFrame(()=>{
        moveFrame=0;
        const p=pendingMove; pendingMove=null;
        if(p)onMove(p.x,p.y);
      });
    }, {passive:true});
    const finish=(ev)=>{if((control(ev)||window.TRXChart?.isInspecting())&&!drag)return;clearMove();const p=localXY(ev);if(tool==="cursor"&&drag){ev.stopPropagation();onMove(p.x,p.y);}onUp(p.x,p.y);redraw();try{if(wrapEl.hasPointerCapture(ev.pointerId))wrapEl.releasePointerCapture(ev.pointerId);}catch(_e){}};
    wrapEl.addEventListener("pointerup",finish,true);wrapEl.addEventListener("pointercancel",ev=>{clearMove();if(drag){const d=selected();if(d&&drag.origData)d.points=drag.origData;}drag=null;downXY=null;placing=null;placeStage=0;setTool("cursor");try{if(wrapEl.hasPointerCapture(ev.pointerId))wrapEl.releasePointerCapture(ev.pointerId);}catch(_e){}redraw();},true);
    wrapEl.addEventListener("pointerleave",()=>{if(!drag){clearMove();hover=null;redraw();}});wrapEl.addEventListener("contextmenu",ev=>{if(tool!=="cursor"){ev.preventDefault();setTool("cursor");}});
    document.querySelectorAll(".dt-btn[data-tool]").forEach(btn=>btn.addEventListener("click",()=>setTool(btn.dataset.tool)));
    document.querySelectorAll(".dt-swatch").forEach(sw=>sw.addEventListener("click",()=>{color=sw.dataset.color;document.querySelectorAll(".dt-swatch").forEach(s=>s.classList.toggle("active",s.dataset.color===color));const d=selected();if(d){d.color=color;save();redraw();}if(placing)placing.color=color;}));
    $("chart-magnet")?.addEventListener("click",toggleMagnet);
    const bind=(id,fn)=>{const el=$(id);if(el)el.addEventListener("click",fn);};bind("dt-undo",undo);bind("dt-redo",redo);bind("dt-clear",clearAll);bind("dt-del",deleteSelected);
    document.addEventListener("keydown",ev=>{if(/input|textarea|select/i.test((document.activeElement||{}).tagName||""))return;if((ev.key==="Delete"||ev.key==="Backspace")&&selectedId&&!drag){ev.preventDefault();deleteSelected();}if(ev.key==="Escape")setTool("cursor");if((ev.key==="z"||ev.key==="Z")&&(ev.ctrlKey||ev.metaKey)){ev.preventDefault();ev.shiftKey?redo():undo();}if(ev.key.toLowerCase()==="y"&&(ev.ctrlKey||ev.metaKey)){ev.preventDefault();redo();}const hotkeys={t:"trend",r:"ray",h:"hline",v:"vline",b:"rect",f:"fib"};const k=ev.key.toLowerCase();if(hotkeys[k]&&!ev.ctrlKey&&!ev.metaKey&&!ev.altKey)setTool(hotkeys[k]);});
    new ResizeObserver(()=>{resize();layoutFibPanel();}).observe(wrapEl);
    new ResizeObserver(layoutFibPanel).observe(panelEl);
  }

  function onData(next){
    const newLabels=next.labels||[];const map=next.labelMap instanceof Map&&next.labelMap.size?next.labelMap:(next.fulls&&next.fulls.length?new Map(next.fulls.map((lb,i)=>[lb,i+1]).filter(x=>x[0])):new Map(newLabels.map((lb,i)=>[lb,i+1])));
    if(drawings.length)drawings.forEach(d=>d.points.forEach(p=>{if(p.lb!=null)p.t=map.has(p.lb)?map.get(p.lb):null;else if(p.anchorLb!=null)p.t=map.has(p.anchorLb)?map.get(p.anchorLb)+Number(p.offset||0):null;else if(p.t==null||p.t<1)p.t=null;}));
    api=next;if(!restored)restore();updatePanel();redraw();
  }
  function init(){
    if(canvas)return;wrapEl=$("tv-chart");if(!wrapEl)return;loadPrefs();canvas=document.createElement("canvas");canvas.className="draw-overlay";wrapEl.appendChild(canvas);ctx=canvas.getContext("2d");
    hintEl=document.createElement("div");hintEl.className="draw-hint";hintEl.textContent=HINTS.cursor;wrapEl.appendChild(hintEl);buildPanel();buildFibPanel();buildPersistenceToolbar();buildManager();bindEvents();updatePanel();resize();
  }
  document.addEventListener("DOMContentLoaded",init);if(document.readyState!=="loading")init();
  return {useCursor,onData,redraw,undo,redo,beginPractice,endPractice,clearAll,pullServer,pushServer,exportDrawings,_dbg:()=>({tool,apiReady:!!api,count:drawings.length,practice,historyAt,historyLength:history.length,fibMode,selectedId,dragging:!!drag,placing:!!placing,magnet,serverRevision,serverConflict,selected:selected()?{type:selected().type,locked:selected().locked,hidden:selected().hidden,width:selected().width,style:selected().style,extendLeft:selected().extendLeft,extendRight:selected().extendRight}:null,hidden:drawings.filter(d=>d.hidden).length})};
})();
