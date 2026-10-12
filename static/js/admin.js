'use strict';
const byId = id => document.getElementById(id);
function quietStatus(id,text){const el=byId(id);if(el.textContent!==text)el.textContent=text;}
const csrf = document.querySelector('meta[name="csrf-token"]').content;
const names = {ema:'EMA 5 / 15',sma:'SMA 20 / 50',bb:'Bollinger Bands',rsi:'RSI 14',macd:'MACD',stoch:'Stochastic',tl:'Trend lines',sr:'Support / Resistance',pat:'Patterns',hss:'H / SS · 5m',sig:'Signal arrows'};
let journalData=null;
let journalAccount=null;
let leavingAdmin=false;
let revision = null, settings = null, polling = false, busy = false, maintenanceBusy = false;
function toast(message,type='success'){
  const host=byId('toast-region');
  const item=document.createElement('div');item.className=`toast toast-${type}`;
  item.setAttribute('role',['error','win','loss'].includes(type)?'alert':'status');
  const icon=document.createElement('span');icon.className='toast-icon';icon.setAttribute('aria-hidden','true');icon.textContent=type==='error'?'!':type==='success'?'✓':'i';
  const content=document.createElement('div'),title=document.createElement('strong'),text=document.createElement('p');
  title.textContent=({success:'Done',error:'Action failed',info:'Draft updated',warning:'Refresh needed',win:'WIN · အနိုင်',loss:'LOSS · အရှုံး'})[type];text.textContent=message;content.append(title,text);
  const close=document.createElement('button');close.type='button';close.className='toast-close';close.setAttribute('aria-label','Dismiss notification');close.textContent='×';
  let timer;const dismiss=()=>{clearTimeout(timer);item.remove();};
  const resume=()=>{clearTimeout(timer);if(!item.matches(':hover')&&!item.contains(document.activeElement))timer=setTimeout(dismiss,type==='error'||type==='warning'?12000:7000);};
  close.addEventListener('click',dismiss);item.addEventListener('mouseenter',()=>clearTimeout(timer));item.addEventListener('mouseleave',resume);item.addEventListener('focusin',()=>clearTimeout(timer));item.addEventListener('focusout',resume);
  item.append(icon,content,close);host.append(item);
  while(host.children.length>3)host.firstElementChild.querySelector('button').click();
  resume();
}
function notice(message,error=false,options={}){byId('notice').textContent=message;byId('notice').classList.toggle('error',error);if(options.popup!==false)toast(message,options.type||(error?'error':'success'));}
let actionCommitted=false, lastMaintenance=null, draftNotified=false;
async function api(url,method='GET',body){const controller=new AbortController();const timer=setTimeout(()=>controller.abort(),(url.startsWith('/api/admin/trxchart-account')||url==='/api/admin/trxchart-order')?75000:url.startsWith('/api/admin/trongrid')?60000:20000);try{const response=await fetch(url,{method,credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':csrf},body:body===undefined?undefined:JSON.stringify(body),signal:controller.signal});if(response.status===401){leavingAdmin=true;location.href='/admin/login';throw Error('Session expired.');}const data=await response.json().catch(()=>null);if(!response.ok){const error=Error(data?.error||(url==='/api/admin/trxchart-order'?'Order response unavailable. Check REAL history before another order.':`Request failed (${response.status}). Please retry when the server is available.`));error.status=response.status;throw error;}if(!data||typeof data!=='object')throw Error('Server returned an invalid response. Please refresh and try again.');if(busy&&(method==='PUT'||method==='DELETE'||url==='/api/admin/restore'||url==='/api/admin/maintenance'||url==='/api/admin/trade-journal/import'))actionCommitted=true;return data;}catch(e){if(url==='/api/admin/trxchart-order'&&(e.name==='AbortError'||e.name==='TypeError'))throw Error('Order response unavailable. Check REAL history before another order. Do not resend this request.');if(e.name==='AbortError')throw Error('Request timed out. Check system status and try again.');throw e;}finally{clearTimeout(timer);}}
function sameValue(a,b){if(Object.is(a,b))return true;if(!a||!b||typeof a!=='object'||typeof b!=='object')return false;const keys=Object.keys(a);return keys.length===Object.keys(b).length&&keys.every(k=>Object.hasOwn(b,k)&&sameValue(a[k],b[k]));}
function number(v){return v==null?'—':Number(v).toLocaleString('en-US',{maximumFractionDigits:1});}
function date(v){if(!v)return '—';const iso=/^\d{4}-\d{2}-\d{2} /.test(v)?v.replace(' ','T')+'Z':v;const d=new Date(iso);return Number.isNaN(d.valueOf())?String(v):d.toLocaleString();}
function cell(value){const td=document.createElement('td');td.textContent=value==null?'—':String(value);return td;}
function table(id,rows,format){const target=byId(id);target.replaceChildren();if(!rows.length){const tr=document.createElement('tr'),td=cell('No records yet.');td.colSpan=8;tr.append(td);target.append(tr);return;}for(const row of rows){const tr=document.createElement('tr');for(const value of format(row)){const td=cell(value);if(typeof value==='number')td.classList.toggle(value<0?'negative':'positive',value!==0);tr.append(td);}target.append(tr);}}
function stats(id,items){const target=byId(id);target.replaceChildren();for(const [label,value] of items){const box=document.createElement('div');box.className='stat';const title=document.createElement('span');title.textContent=label;const strong=document.createElement('strong');strong.textContent=value;box.append(title,strong);target.append(box);}}
for(const [key,label] of Object.entries(names)){const wrap=document.createElement('label');wrap.className='toggle';const input=document.createElement('input');input.type='checkbox';input.id=`indicator-${key}`;wrap.append(input,document.createTextNode(label));byId('indicator-settings').append(wrap);}
async function loadSettings(){const data=await api('/api/admin/settings');settings=data.settings;revision=data.revision;byId('timeframe').value=String(settings.timeframe);byId('range').value=String(settings.range);byId('telegram').checked=settings.telegram;byId('alerts').checked=settings.alerts;for(const key of Object.keys(names))byId(`indicator-${key}`).checked=settings.indicators[key];}
async function loadStatus(){const data=await api('/api/admin/status'),h=data.health,e=h.engine,f=h.feed,q=h.queues;const badge=byId('health-badge');badge.textContent=h.status;badge.className=`badge ${h.ok?'good':'bad'}`;stats('status-cards',[['Feed',h.status],['Data rows',number(e.full_history_rows)],['Data age',f.result_age_sec==null?'—':number(f.result_age_sec)+' s'],['Uptime',number(h.uptime_sec/60)+' min']]);const target=byId('status-detail');target.replaceChildren();for(const [label,value] of [['Memory used',h.resources?.rss_mb==null?'—':number(h.resources.rss_mb)+' MB'],['Peak memory',h.resources?.peak_rss_mb==null?'—':number(h.resources.peak_rss_mb)+' MB'],['Open file descriptors',h.resources?.open_fds==null?'—':number(h.resources.open_fds)],['Latest issue',f.last_issue],['Last update',date(e.last_update)],['Engine thread',e.thread_alive?'Running':'Stopped'],['L1 observer',e.l1_thread_alive?'Running':'Stopped'],['Telegram worker',q.telegram_worker_alive?'Running':'Stopped'],['Telegram queue',`${number(q.telegram)} / ${number(q.telegram_max)}`],['Dropped messages',number(q.telegram_dropped)],['Feed failures',number(f.failure_count)],['Last error',e.error||f.last_error||'None'],['Feed note',f.note||'—']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=value??'—';target.append(dt,dd);}byId('telegram-badge').textContent=data.telegram_configured?'Configured':'Not configured';byId('storage-note').hidden=data.storage.persistent;byId('storage-note').textContent=data.storage.note;const job=data.maintenance;const signature=JSON.stringify([job.action,job.status,job.updated]);if(lastMaintenance!==null&&signature!==lastMaintenance&&['complete','failed'].includes(job.status)){toast(job.status==='complete'?`${job.action.replaceAll('_',' ')} completed.`:`${job.action.replaceAll('_',' ')} failed. ${job.error||'Check system status.'}`,job.status==='complete'?'success':'error');}lastMaintenance=signature;byId('job-status').textContent=job.action?`${job.action.replaceAll('_',' ')} · ${job.status}${job.error?' · '+job.error:''}`:'No active maintenance job.';maintenanceBusy=['queued','running'].includes(job.status);updateMaintenanceControls();}
let eventData=[], logCursors={audit:null,telegram:null}, logGeneration=0,logExpanded=false;
function renderEvents(){table('delivery-rows',eventData.filter(e=>e.kind==='telegram'),e=>[date(e.detail.imported_from_backup_at||e.at),e.detail.text||e.detail.message,e.detail.result]);table('audit-rows',eventData.filter(e=>e.kind!=='telegram'),e=>[date(e.at),e.kind.replaceAll('_',' '),JSON.stringify(e.detail)]);byId('more-audit').disabled=!logCursors.audit;byId('more-delivery').disabled=!logCursors.telegram;}
async function loadEvents(){logExpanded=false;const generation=++logGeneration;const rows=await Promise.all(['audit','telegram'].map(kind=>api('/api/admin/events?kind='+kind+'&limit=100&search='+encodeURIComponent(byId(kind==='audit'?'audit-filter':'delivery-filter').value))));if(generation!==logGeneration)return;eventData=rows.flatMap(r=>r.events);['audit','telegram'].forEach((kind,i)=>logCursors[kind]=rows[i].next_before);renderEvents();}
for(const [id,kind] of [['more-audit','audit'],['more-delivery','telegram']])byId(id).addEventListener('click',()=>run(async()=>{if(!logCursors[kind])return;const generation=logGeneration;const data=await api('/api/admin/events?kind='+kind+'&limit=100&before='+logCursors[kind]+'&search='+encodeURIComponent(byId(kind==='audit'?'audit-filter':'delivery-filter').value));if(generation!==logGeneration)return;logExpanded=true;eventData.push(...data.events);logCursors[kind]=data.next_before;renderEvents();},'Older records loaded.'));
let reportData=null;
async function loadReports(){const selected=byId('report-date').value;const data=await api('/api/admin/reports?days=31'+(selected?'&date='+encodeURIComponent(selected):''));reportData=data;const l=data.l1,s=data.twelve_step.report,d=l.daily_summary||{};stats('l1-summary',[['Bets',number(d.bets)],['Win rate',number(d.win_rate)+'%'],['Model P/L',number(d.pnl)+' MMK'],['Total staked',number(d.staked)+' MMK']]);stats('step-summary',[['Bets',number(s.settled_bets)],['Win rate',number(s.bet_win_rate)+'%'],['Model P/L',number(s.pnl??s.net_pnl)+' MMK'],['Total staked',number(s.staked??s.total_staked)+' MMK']]);table('l1-trades',(l.trades||[]).slice().reverse(),r=>[r.time||r.issue,r.target||r.signal,number(r.stake),r.won===true?'WIN':r.won===false?'LOSS':'—',r.pnl??'—']);table('step-days',data.twelve_step.history||[],r=>[r.date,number(r.settled_bets),number(r.bet_wins),number(r.bet_losses),r.pnl??r.net_pnl??'—']);const signalRow=r=>[r.issue||r.target_issue,r.signal||r.target||r.bet,r.result??(r.won===true?'WIN':r.won===false?'LOSS':'—'),number(r.stake)];table('signal-rows',data.signals||[],signalRow);table('step-signals',data.step_signals||[],signalRow);}
async function run(fn,message){if(busy)return;busy=true;actionCommitted=false;byId('admin-work-state').hidden=false;byId('admin-work-state').textContent='Working…';document.querySelector('.admin-main').setAttribute('aria-busy','true');const locked=Array.from(document.querySelectorAll('input,select,textarea,button:not(.toast-close):not(#menu-backdrop)')).map(el=>[el,el.disabled]);for(const [el] of locked)el.disabled=true;try{await fn();notice(message);}catch(e){notice(actionCommitted?'Change accepted, but the dashboard refresh failed. '+e.message:e.message,true,{type:actionCommitted?'warning':'error'});}finally{byId('admin-work-state').hidden=true;document.querySelector('.admin-main').removeAttribute('aria-busy');for(const [el,wasDisabled] of locked)if(el.isConnected)el.disabled=wasDisabled;busy=false;renderEvents();updateReadyControls();}}
byId('settings-form').addEventListener('submit',e=>{e.preventDefault();if(!e.submitter||e.submitter.closest('section')?.hidden)return;run(async()=>{if(!settings)throw Error('Settings are still loading.');const value=structuredClone(settings);const isChart=e.submitter?.closest('section')?.id==='chart';if(isChart){const indicators={};for(const key of Object.keys(names))indicators[key]=byId(`indicator-${key}`).checked;Object.assign(value,{timeframe:Number(byId('timeframe').value),range:Number(byId('range').value),indicators});}else{Object.assign(value,{telegram:byId('telegram').checked,alerts:byId('alerts').checked});}const data=await api('/api/admin/settings','PUT',{revision,settings:value});revision=data.revision;settings=data.settings;updateDraftSummary();await loadEvents();},'Settings saved. Reload the terminal to apply chart defaults.');});
byId('reload-settings').addEventListener('click',()=>run(loadSettings,'Latest settings loaded.'));
byId('refresh-reports').addEventListener('click',()=>run(loadReports,'Reports refreshed.'));
byId('report-date').addEventListener('change',()=>run(loadReports,'Selected report loaded.'));
byId('logout').addEventListener('click',()=>run(async()=>{await api('/api/admin/logout','POST',{});leavingAdmin=true;location.href='/admin/login';},'Signed out.'));
for(const btn of document.querySelectorAll('[data-action]'))btn.addEventListener('click',()=>run(async()=>{await api('/api/admin/maintenance','POST',{action:btn.dataset.action});await loadStatus();await loadEvents();},'Maintenance job queued. Its result appears below.'));
byId('restore-backup').addEventListener('click',()=>run(async()=>{if(!restoreReady())throw Error('Wait for all settings to load before restoring a backup. Use Refresh data to retry.');const file=byId('backup-file').files[0];if(!file)throw Error('Choose a backup file first.');if(file.size>8*1024*1024)throw Error('Backup must be smaller than 8 MB.');let data;try{data=JSON.parse(await file.text());}catch(_){throw Error('The file is not valid JSON.');}await api('/api/admin/restore','POST',{...data,expected_revision:revision,expected_control_revisions:{l1:strategyData.l1.revision,twelve:strategyData.twelve.revision,telegram:policyData.revision,messages:messageData.revision}});await loadSettings();await Promise.all([loadStrategy('l1'),loadStrategy('twelve'),loadPolicy(),loadMessages(),loadEvents()]);},'Backup restored. Reload the terminal to apply defaults.'));
let lastDashboardSync=null;
function showSync(state,message){byId('sync-state').textContent=state;byId('sync-state').className='badge '+(state==='Up to date'?'good':'bad');byId('sync-time').textContent=message;}
async function refreshLive(){
  const tasks=[['System status',loadStatus],['Live API',loadApiRuntime],...(!logExpanded?[['Audit / delivery',loadEvents]]:[])];
  const results=await Promise.allSettled(tasks.map(([,load])=>load()));
  const failures=[];
  results.forEach((result,i)=>{if(result.status!=='rejected')return;failures.push(tasks[i][0]+': '+result.reason.message);if(i===0){byId('health-badge').textContent='Refresh failed';byId('health-badge').className='badge bad';}if(i===1){byId('api-runtime-badge').textContent='Refresh failed';byId('api-runtime-badge').className='badge bad';byId('api-runtime-note').textContent='Status could not be refreshed. Displayed data may be old.';}});
  if(failures.length){showSync('Partial refresh',lastDashboardSync?'Last complete refresh: '+date(lastDashboardSync):'No complete refresh yet. Use Refresh data to retry.');throw Error(failures.join(' · '));}
  lastDashboardSync=new Date().toISOString();showSync('Up to date','Last complete refresh: '+date(lastDashboardSync)+' · Auto refresh every 10 s');
}
async function poll(){if(busy||polling||document.hidden||leavingAdmin)return;polling=true;try{await refreshLive();}catch(e){notice(e.message,true,{popup:false});}finally{polling=false;}}
setInterval(poll,10000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)poll();});
window.addEventListener('online',poll);
window.addEventListener('offline',()=>showSync('Offline','Your browser is offline. Displayed data may be old.'));

const pageNames={trade:'Trade · REAL orders and live results',journal:'Trade Results · Daily performance and history',system:'System Status · Live health and engine activity',chart:'Chart Settings · Defaults for the public terminal',l1:'L1 Strategy · Frozen rules and money controls',twelve:'12-Step Strategy · Frozen rules and money controls',notifications:'Telegram & Alerts · Delivery and connection controls',reports:'Reports · Model results and signal history',maintenance:'Maintenance · Data, cache and backups',audit:'Audit Log · Settings and operation history',security:'Password & Security · Protect admin access',connection:'Data API Connection · Endpoint and write-only credentials'};
function showPage(name){if(!pageNames[name])name='system';for(const section of document.querySelectorAll('.page'))section.hidden=section.id!==name;for(const link of document.querySelectorAll('nav [data-page]')){const active=link.dataset.page===name;link.classList.toggle('active',active);if(active)link.setAttribute('aria-current','page');else link.removeAttribute('aria-current');}byId('page-subtitle').textContent=pageNames[name];closeMenu();}
function closeMenu(){document.querySelector('.sidebar').classList.remove('open');byId('menu-toggle').setAttribute('aria-expanded','false');byId('menu-backdrop').hidden=true;}
byId('menu-backdrop').addEventListener('click',closeMenu);document.addEventListener('keydown',e=>{if(e.key==='Escape'&&document.querySelector('.sidebar').classList.contains('open')){closeMenu();byId('menu-toggle').focus();}});window.matchMedia('(min-width: 721px)').addEventListener('change',e=>{if(e.matches)closeMenu();});
window.addEventListener('hashchange',()=>showPage(location.hash.slice(1)));
showPage(location.hash.slice(1));
byId('menu-toggle').addEventListener('click',()=>{const open=document.querySelector('.sidebar').classList.toggle('open');byId('menu-toggle').setAttribute('aria-expanded',String(open));byId('menu-backdrop').hidden=!open;});
const strategyData={},moneyNames={bankroll:'Bankroll',base:'Base bet',tp:'Daily take profit',sl:'Daily stop loss',withdrawal:'Withdrawal milestone'};
function escapeText(value){const span=document.createElement('span');span.textContent=String(value);return span.innerHTML;}
function moneyDraft(name){const data=strategyData[name];const value=structuredClone(data.settings);for(const key of Object.keys(moneyNames))if(key in value)value[key]=Number(byId(`${name}-${key}`).value);value.multipliers=Array.from({length:3},(_,t)=>Array.from({length:4},(_,s)=>Number(byId(`${name}-m-${t}-${s}`).value)));return value;}
function roundStake(base,multiplier){if(!Number.isSafeInteger(base)||base<0||!Number.isFinite(multiplier)||multiplier<0)return NaN;return Number((BigInt(base)*BigInt(Math.round(multiplier*10000))+5000n)/10000n);}
function previewMoney(name){const value=moneyDraft(name);const output=byId(`${name}-preview`);const fragment=document.createDocumentFragment();let large=false;value.multipliers.forEach((row,t)=>{const line=document.createElement('div');line.textContent=`T${t+1} · `+row.map(m=>{const stake=roundStake(value.base,m);if(stake>value.bankroll)large=true;return number(stake);}).join(' → ')+' MMK';fragment.append(line);});output.replaceChildren(fragment);byId(`${name}-funds`).textContent=large?'Some ladder stakes exceed bankroll. The risk banner will show observe only for an unaffordable pending stake.':'All ladder stakes are within the configured bankroll.';byId(`${name}-draft`).textContent=sameValue(value,strategyData[name].settings)?`Saved · revision ${strategyData[name].revision}`:'Unsaved changes · Save to apply';updateDraftSummary();}
function fillMoney(name,value){for(const key of Object.keys(moneyNames))if(key in value)byId(`${name}-${key}`).value=value[key];value.multipliers.forEach((row,t)=>row.forEach((v,s)=>byId(`${name}-m-${t}-${s}`).value=v));previewMoney(name);}
async function loadStrategy(name){const data=await api(`/api/admin/strategies/${name}`);strategyData[name]=data;const host=byId(name);if(!host.children.length){const fields=Object.keys(moneyNames).filter(k=>k in data.settings).map(key=>`<label>${moneyNames[key]} · MMK<input id="${name}-${key}" type="number" min="${['tp','sl'].includes(key)?0:1}" max="1000000000" step="1" required></label>`).join('');const matrix=Array.from({length:3},(_,t)=>`<h3>Tier ${t+1} multipliers</h3><div class="multiplier-grid">`+Array.from({length:4},(_,s)=>`<label>Step ${s+1} · × base<input id="${name}-m-${t}-${s}" type="number" min="1" max="10000" step="0.0001" required ${t===0&&s===0?'readonly':''}></label>`).join('')+'</div>').join('');host.innerHTML=`<div class="section-heading"><div><span class="eyebrow">STRATEGY MANAGEMENT</span><h2>${escapeText(data.info.name)}</h2></div><span class="badge">RULES LOCKED</span></div><div class="strategy-columns"><article><h3>Description <span class="readonly-tag">READ ONLY</span></h3><p class="muted">${escapeText(data.info.description)}</p><h3>Strategy rules <span class="readonly-tag">READ ONLY</span></h3><ul class="rule-list">${data.info.rules.map(r=>`<li>${escapeText(r)}</li>`).join('')}</ul><h3>Default settings <span class="readonly-tag">REFERENCE</span></h3><dl id="${name}-defaults" class="defaults-list"></dl><div id="${name}-default-ladder" class="ladder-preview muted"></div></article><article><form class="money-form" id="${name}-form"><h3>Current settings</h3><p class="muted">Money controls only. TP / SL = 0 disables that limit. Signals continue in observe mode; execution is manual.</p><div class="form-grid">${fields}</div>${matrix}<h3>Stake ladder preview</h3><div id="${name}-preview" class="ladder-preview"></div><p id="${name}-funds" class="muted"></p><p class="muted">${escapeText(data.effective)}</p><p id="${name}-draft" class="draft-state"></p><div class="actions"><button type="submit">Save ${escapeText(data.info.name)} settings</button><button id="${name}-reload" type="button" class="secondary">Reload saved</button><button id="${name}-reset" type="button" class="secondary">Restore defaults</button></div></form></article></div>`;const defaults=byId(`${name}-defaults`);for(const [key,label] of Object.entries(moneyNames))if(key in data.defaults){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=label;dd.textContent=number(data.defaults[key])+' MMK'+(['tp','sl'].includes(key)&&!data.defaults[key]?' · Disabled':'');defaults.append(dt,dd);}byId(`${name}-default-ladder`).textContent=data.defaults.multipliers.map((r,t)=>`T${t+1}: `+r.map(m=>number(Math.round(data.defaults.base*m))).join(' → ')).join(' / ');byId(`${name}-form`).addEventListener('input',()=>previewMoney(name));byId(`${name}-form`).addEventListener('submit',e=>{e.preventDefault();run(async()=>{const result=await api(`/api/admin/strategies/${name}`,'PUT',{revision:strategyData[name].revision,settings:moneyDraft(name)});strategyData[name]=result;fillMoney(name,result.settings);await loadEvents();},'Strategy money settings saved. New source issues use this configuration; issued stakes stay fixed.');});byId(`${name}-reload`).addEventListener('click',()=>run(()=>loadStrategy(name),'Saved strategy settings loaded.'));byId(`${name}-reset`).addEventListener('click',()=>{fillMoney(name,strategyData[name].defaults);updateDraftSummary();notice('Default money settings loaded into the draft. Save to apply.',false,{type:'info'});});}fillMoney(name,data.settings);updateDraftSummary();}
let policyData=null;
function fillPolicy(value){for(const group of ['engines','types'])for(const [key,on] of Object.entries(value[group]))byId(`policy-${group}-${key}`).checked=on;byId('quiet-enabled').checked=value.quiet.enabled;byId('quiet-start').value=value.quiet.start;byId('quiet-end').value=value.quiet.end;fillStreak(value.streak);byId('policy-state').textContent='Saved policy loaded';updateDraftSummary();}
async function loadPolicy(){const data=await api('/api/admin/telegram');policyData=data;const host=byId('telegram-policy');if(!host.children.length){for(const group of ['engines','types']){const heading=document.createElement('h3');heading.textContent=group==='engines'?'Strategy / market channels':'Message types';const grid=document.createElement('div');grid.className='toggle-grid';for(const key of Object.keys(data.settings[group])){if(group==='types'&&key==='streak')continue;const label=document.createElement('label');label.className='toggle';const input=document.createElement('input');input.type='checkbox';input.id=`policy-${group}-${key}`;label.append(input,document.createTextNode(({l1:'L1 CAPITAL',twelve:'12-STEP',market:'Market alerts',result:'Results & progression',wait:'Waiting',withdrawal:'Withdrawal milestone',daily:'Daily reports',radar:'Radar',rsi:'RSI alerts',streak:'B/S streak',signal:'Signals'})[key]||key));grid.append(label);}host.append(heading,grid);}}fillPolicy(data.settings);fillCredentials(data);}
function fillCredentials(data){byId('credential-state').textContent=data.credentials.error||`${data.credentials.source} · ${data.credentials.configured?'Configured · Destination '+data.credentials.chat_mask:'Not configured'}`;updateDraftSummary();}
async function loadCredentials(){fillCredentials(await api('/api/admin/telegram'));}
function policyDraft(){const value=structuredClone(policyData.settings);for(const group of ['engines','types'])for(const key of Object.keys(value[group]))value[group][key]=byId(`policy-${group}-${key}`).checked;value.quiet={enabled:byId('quiet-enabled').checked,start:byId('quiet-start').value,end:byId('quiet-end').value};value.streak=streakDraft();return value;}
function streakDraft(){return {start:Number(byId('streak-start').value),repeat:byId('streak-repeat').value,interval:Number(byId('streak-interval').value),side:byId('streak-side').value};}
function fillStreak(value){for(const key of ['start','repeat','interval','side'])byId('streak-'+key).value=String(value[key]);byId('streak-preview').textContent='';updateStreakSummary();}
function updateStreakSummary(){const cfg=streakDraft();byId('streak-interval-label').hidden=cfg.repeat!=='interval';const step=cfg.repeat==='interval'?cfg.interval:1;const counts=cfg.repeat==='once'?String(cfg.start):Array.from({length:4},(_,i)=>cfg.start+i*step).join(', ')+'…';byId('streak-summary').textContent=byId('policy-types-streak').checked?`${cfg.side==='both'?'BIG + SMALL':cfg.side} · Alert at ${counts} consecutive rounds`:'Streak alerts disabled';byId('streak-preview').textContent='';}
for(const id of ['policy-types-streak','streak-start','streak-repeat','streak-interval','streak-side'])byId(id).addEventListener('input',updateStreakSummary);
byId('preview-streak').addEventListener('click',()=>run(async()=>{const data=await api('/api/admin/telegram/streak/preview','POST',{streak:streakDraft()});byId('streak-preview').textContent=data.text;},'Streak preview ready. No message sent.'));
byId('save-policy').addEventListener('click',()=>run(async()=>{const data=await api('/api/admin/telegram','PUT',{revision:policyData.revision,settings:policyDraft()});policyData=data;fillPolicy(data.settings);fillCredentials(data);await loadEvents();},'Telegram delivery policy saved.'));
byId('reload-policy').addEventListener('click',()=>run(loadPolicy,'Saved Telegram policy loaded.'));
byId('reset-policy').addEventListener('click',()=>{fillPolicy(policyData.defaults);byId('policy-state').textContent='Default policy draft · Save to apply';notice('Default delivery policy loaded into the draft. Save to apply.',false,{type:'info'});});
byId('save-credentials').addEventListener('click',()=>run(async()=>{await api('/api/admin/telegram/credentials','PUT',{token:byId('bot-token').value.trim(),chat:byId('bot-chat').value.trim()});byId('bot-token').value='';byId('bot-chat').value='';await loadCredentials();await loadEvents();},'Telegram credentials saved.'));
byId('clear-credentials').addEventListener('click',()=>run(async()=>{await api('/api/admin/telegram/credentials','DELETE',{});await loadCredentials();await loadEvents();},'Server Telegram configuration restored.'));
byId('check-bot').addEventListener('click',()=>run(async()=>{const result=await api('/api/admin/telegram/check','POST',{});byId('credential-state').textContent=`Verified @${result.username} · ${result.note}`;},'Bot connection verified. No message sent.'));
async function refreshDashboard(){
  logExpanded=false;
  const loads=[refreshLive(),loadReports()];
  if(!settings)loads.push(loadSettings());
  for(const name of ['l1','twelve'])if(!strategyData[name])loads.push(loadStrategy(name));
  if(!policyData)loads.push(loadPolicy());
  if(!messageData)loads.push(loadMessages());
  if(!feedData)loads.push(loadFeed());
  if(!trongridData)loads.push(loadTronGrid());
  if(!journalData)loads.push(loadJournal());
  const results=await Promise.allSettled(loads);
  const failed=results.find(result=>result.status==='rejected');
  if(failed)throw failed.reason;
}
byId('refresh-all').addEventListener('click',()=>run(async()=>{await refreshDashboard();},'Status and reports refreshed.'));
byId('reset-chart').addEventListener('click',()=>{byId('timeframe').value='1';byId('range').value='30';for(const key of Object.keys(names))byId(`indicator-${key}`).checked=['ema','rsi'].includes(key);updateDraftSummary();notice('Chart default draft loaded. Save to apply.',false,{type:'info'});});
let logSearchTimer;for(const id of ['audit-filter','delivery-filter'])byId(id).addEventListener('input',()=>{logExpanded=false;clearTimeout(logSearchTimer);logSearchTimer=setTimeout(()=>loadEvents().catch(e=>notice(e.message,true)),300);});


let messageData=null,messageDrafts=null;
function messageKey(){return byId('message-engine').value+'.'+byId('message-category').value;}
function editorValue(){return byId('message-mode').value==='simple'?{heading:byId('message-heading').value,before:byId('message-before').value,after:byId('message-after').value}:byId('message-template').value;}
let previewGeneration=0,previewTimer;
function schedulePreview(){const generation=++previewGeneration;clearTimeout(previewTimer);previewTimer=setTimeout(()=>previewMessage(generation).catch(e=>{if(generation===previewGeneration)byId('message-preview-note').textContent=e.message;}),350);}
async function previewMessage(generation=++previewGeneration){const data=await api('/api/admin/telegram/messages/preview','POST',{engine:byId('message-engine').value,category:byId('message-category').value,template:editorValue()});if(generation!==previewGeneration)return;byId('message-preview').textContent=data.text;byId('message-preview-note').textContent=(data.sample?'နမူနာ message':'မကြာသေးခင်က engine message')+' · Preview သာ ဖြစ်ပြီး Telegram ဆီ မပို့ပါ။'+(data.fallback?' စာရှည်လွန်းလို့ original message ကို သုံးပါမယ်။':'');}
function syncMessageDraft(){if(messageDrafts&&messageKey() in messageDrafts.templates)messageDrafts.templates[messageKey()]=editorValue();updateMessageState();schedulePreview();}
function updateMessageState(){if(!messageData)return;const dirty=!sameValue(messageDrafts,messageData.settings);const value=editorValue();const count=typeof value==='string'?value.length:Object.values(value).reduce((sum,v)=>sum+v.length,0);byId('message-state').textContent=(dirty?'Unsaved templates':'Saved · revision '+messageData.revision)+' · '+count+' / 1800 characters';updateDraftSummary();}
function selectMessage(){const value=messageDrafts.templates[messageKey()];const simple=typeof value==='object'||value==='{original}';byId('message-mode').value=simple?'simple':'advanced';byId('message-simple').hidden=!simple;byId('message-advanced').hidden=simple;for(const key of ['heading','before','after'])byId('message-'+key).value=typeof value==='object'?value[key]:'';byId('message-template').value=typeof value==='string'?value:'{original}';byId('message-preview').textContent='';updateMessageState();schedulePreview();}
async function loadMessages(){const data=await api('/api/admin/telegram/messages');messageData=data;messageDrafts=structuredClone(data.settings);if(!byId('message-engine').options.length){for(const [value,label] of Object.entries(data.engines)){const option=new Option(label,value);byId('message-engine').add(option);}for(const value of data.categories)byId('message-category').add(new Option(value.replaceAll('_',' '),value));for(const [key,description] of Object.entries(data.variables)){const button=document.createElement('button');button.type='button';button.className='secondary';button.textContent='{'+key+'}';button.title=description;button.addEventListener('click',()=>{const input=byId('message-template');input.setRangeText(button.textContent,input.selectionStart,input.selectionEnd,'end');input.focus();syncMessageDraft();});byId('message-variables').append(button);}}selectMessage();}
for(const id of ['message-engine','message-category'])byId(id).addEventListener('change',selectMessage);
for(const id of ['message-template','message-heading','message-before','message-after'])byId(id).addEventListener('input',syncMessageDraft);byId('message-mode').addEventListener('change',()=>{const simple=byId('message-mode').value==='simple';byId('message-simple').hidden=!simple;byId('message-advanced').hidden=simple;syncMessageDraft();});
byId('save-messages').addEventListener('click',()=>run(async()=>{syncMessageDraft();const data=await api('/api/admin/telegram/messages','PUT',{revision:messageData.revision,settings:messageDrafts});messageData=data;messageDrafts=structuredClone(data.settings);updateMessageState();await loadEvents();},'Message templates saved. Future deliveries use the new text.'));
byId('reload-messages').addEventListener('click',()=>run(loadMessages,'Saved message templates loaded.'));
byId('default-message').addEventListener('click',()=>{messageDrafts.templates[messageKey()]=structuredClone(messageData.defaults.templates[messageKey()]);selectMessage();notice('Default template loaded into the draft. Save to apply.',false,{type:'info'});});
byId('preview-message').addEventListener('click',()=>run(()=>previewMessage(),'Message preview ready. No message sent.'));
function updateDraftSummary(){const dirty=[];if(journalData&&!sameValue(journalLimits(),journalData.limits))dirty.push('Trade targets');if(byId('journal-json').value.trim()||byId('journal-file').files.length)dirty.push('History import');if(trongridData&&(byId('trongrid-key').value||byId('trongrid-mode').value!==trongridData.settings.mode))dirty.push('TronGrid');if(feedData&&(byId('feed-key').value||['url','auth','key_name'].some(k=>feedDraft()[k]!==feedData.settings[k])))dirty.push('Data API');if(byId('bot-token').value||byId('bot-chat').value)dirty.push('Telegram credentials');if(settings){if(Number(byId('timeframe').value)!==settings.timeframe||Number(byId('range').value)!==settings.range||Object.keys(names).some(k=>byId('indicator-'+k).checked!==settings.indicators[k]))dirty.push('Chart');if(byId('telegram').checked!==settings.telegram||byId('alerts').checked!==settings.alerts)dirty.push('Master switches');}for(const name of ['l1','twelve'])if(strategyData[name]&&byId(name+'-form')&&!sameValue(moneyDraft(name),strategyData[name].settings))dirty.push(name==='l1'?'L1':'12-Step');if(policyData&&!sameValue(policyDraft(),policyData.settings))dirty.push('Delivery policy');if(messageData&&!sameValue(messageDrafts,messageData.settings))dirty.push('Message templates');byId('draft-summary').textContent=dirty.length?'Unsaved changes: '+dirty.join(' · '):'';byId('draft-summary').classList.toggle('has-drafts',dirty.length>0);if(!dirty.length)draftNotified=false;return dirty.length>0;}
function draftFeedback(){if(updateDraftSummary()&&!busy&&!draftNotified){draftNotified=true;toast('Unsaved changes. Use the Save button in this section to apply them.','info');}}
document.addEventListener('input',draftFeedback);document.addEventListener('change',draftFeedback);window.addEventListener('beforeunload',e=>{if(!leavingAdmin&&updateDraftSummary()){e.preventDefault();e.returnValue='';}});
byId('export-reports').addEventListener('click',()=>{if(!reportData)return;const blob=new Blob([JSON.stringify({exported_at:new Date().toISOString(),...reportData},null,2)],{type:'application/json'});const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='trx-model-report.json';a.click();notice('Report download started.');setTimeout(()=>URL.revokeObjectURL(url),1000);});

let feedData=null;
function feedDraft(){return {url:byId('feed-url').value.trim(),auth:byId('feed-auth').value,key_name:byId('feed-key-name').value.trim(),key:byId('feed-key').value};}
function showFeedAuth(){const auth=byId('feed-auth').value;byId('feed-key-label').hidden=auth==='none';byId('feed-key-name-label').hidden=!['header','query'].includes(auth);}
function fillFeed(data){feedData=data;for(const key of ['url','auth','key_name'])byId('feed-'+key.replace('_','-')).value=data.settings[key];byId('feed-key').value='';showFeedAuth();byId('feed-state').textContent=data.error||`Saved · revision ${data.revision} · ${data.settings.key_set?'API key stored (hidden)':'No API key configured'}`;updateDraftSummary();}
async function loadFeed(){fillFeed(await api('/api/admin/feed'));}
byId('feed-auth').addEventListener('change',showFeedAuth);
byId('check-feed').addEventListener('click',()=>run(async()=>{const data=await api('/api/admin/feed/check','POST',feedDraft());byId('feed-state').textContent=`Connection verified · ${data.rows} rounds · ${data.matched_rounds} matching rounds · Latest ${data.latest_issue}`;},'API check passed. Connection settings have not changed.'));
byId('feed-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{if(!feedData)throw Error('API settings are still loading. Try again shortly.');fillFeed(await api('/api/admin/feed','PUT',{revision:feedData.revision,...feedDraft()}));await Promise.all([loadEvents(),loadApiRuntime()]);},'API connection verified and saved. Data refresh is queued.');});
byId('reload-feed').addEventListener('click',()=>run(loadFeed,'Saved API connection loaded.'));
byId('default-feed').addEventListener('click',()=>{for(const key of ['url','auth','key_name'])byId('feed-'+key.replace('_','-')).value=feedData.defaults[key];byId('feed-key').value='';showFeedAuth();updateDraftSummary();notice('TRXChart default loaded into the draft. Check & save to apply.',false,{type:'info'});});
let trongridData=null;
async function loadApiRuntime(){
  const data=await api('/api/admin/feed/status'),r=data.runtime||{},s=data.saved||{},tg=s.trongrid||{},primary=s.primary||{};
  const label=source=>source==='trongrid'?'TronGrid':source==='primary'?'Primary API':'Not confirmed';
  const badge=byId('api-runtime-badge');badge.textContent=({active:'Active',pending:'Switch pending',waiting:'Waiting for live fetch',error:'Fetch failed',stale:'Stale'})[data.state]||'Unknown';badge.className='badge '+(data.state==='active'?'good':'bad');
  stats('api-runtime-cards',[['Last successful live source',label(r.source)],['Key used for that fetch',r.key_hint||'Not confirmed'],['Saved TronGrid mode',tg.mode||'Unavailable'],['Saved TronGrid key',tg.key_hint||'No API key']]);
  const target=byId('api-runtime-detail');target.replaceChildren();
  for(const [name,value] of [['Last successful fetch',date(r.last_success_at)],['Latest verified issue',r.latest_issue||'—'],['Live endpoint',r.endpoint||'Not confirmed'],['Saved primary endpoint',primary.endpoint||'Unavailable'],['Saved primary key',primary.auth==='none'?'No API key · Public API':primary.key_hint||'Unavailable'],['TronGrid saved revision',tg.revision??'—'],['Revision used for last fetch',r.revision??'—'],['Last failed attempt',r.last_error_at?date(r.last_error_at)+' · '+label(r.attempt_source):'None']]){const dt=document.createElement('dt'),dd=document.createElement('dd');dt.textContent=name;dd.textContent=value;target.append(dt,dd);}
  const note=data.state==='error'?r.error||'Live fetch failed.':data.state==='pending'?'Settings saved. Waiting for a successful live fetch using the new selection.':data.state==='stale'?'Last successful live fetch is old. This source is not confirmed active now.':data.state==='waiting'?'No successful live fetch recorded yet.':r.source==='primary'&&tg.mode==='backup'?'Primary API is active. TronGrid key is saved and on standby; it is used only if primary fails.':r.source==='trongrid'&&r.fallback?'TronGrid backup is serving live rounds. '+(r.note||''):'Current settings are serving live rounds.';
  byId('api-runtime-note').textContent=note+(tg.error?' '+tg.error:'')+(primary.error?' '+primary.error:'');
}
function trongridDraft(){return {mode:byId('trongrid-mode').value,key:byId('trongrid-key').value.trim()};}
function fillTronGrid(data){trongridData=data;byId('trongrid-mode').value=data.settings.mode;byId('trongrid-key').value='';byId('trongrid-state').textContent=data.error||`Saved · ${data.settings.mode} · ${data.settings.key_set?'Key stored (hidden)':'No API key'} · Last data source: ${data.active_source||'primary'}`;updateDraftSummary();}
async function loadTronGrid(){fillTronGrid(await api('/api/admin/trongrid'));}
byId('check-trongrid').addEventListener('click',()=>run(async()=>{const result=await api('/api/admin/trongrid/check','POST',trongridDraft());byId('trongrid-state').textContent=`Verified · ${result.matched_rounds} matching rounds · Latest ${result.latest_issue}`;},'TronGrid verified. No settings changed.'));
byId('trongrid-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{if(!trongridData)throw Error('TronGrid settings are still loading.');fillTronGrid(await api('/api/admin/trongrid','PUT',{revision:trongridData.revision,...trongridDraft()}));await Promise.all([loadEvents(),loadApiRuntime()]);},'TronGrid settings saved. Strategy rules unchanged.');});
byId('reload-trongrid').addEventListener('click',()=>run(loadTronGrid,'Saved TronGrid settings loaded.'));
byId('clear-trongrid').addEventListener('click',()=>run(async()=>{if(!trongridData)throw Error('TronGrid settings are still loading.');fillTronGrid(await api('/api/admin/trongrid','DELETE',{revision:trongridData.revision}));await Promise.all([loadEvents(),loadApiRuntime()]);},'TronGrid disabled and API key removed.'));

byId('password-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{const current=byId('current-password').value,newPassword=byId('new-password').value,confirm=byId('confirm-password').value;if(newPassword!==confirm)throw Error('New password and confirmation do not match.');await api('/api/admin/password','POST',{current,new:newPassword,confirm});for(const id of ['current-password','new-password','confirm-password'])byId(id).value='';window.onbeforeunload=null;leavingAdmin=true;location.href='/admin/login';},'Password changed. Sign in with your new password.');});



function journalLimits(){return {tp:Number(byId('journal-tp').value),sl:Number(byId('journal-sl').value),timezone:byId('journal-zone').value};}
function journalURL(){const q=new URLSearchParams({mode:byId('journal-mode').value});if(byId('journal-date').value)q.set('date',byId('journal-date').value);return '/api/admin/trade-journal?'+q;}
function renderJournalSync(data){
  const sync=data.synced_at||{};
  stats('journal-sync-cards',['real','demo'].map(mode=>{
    const at=sync[mode],ms=at?Date.parse(/^\d{4}-\d{2}-\d{2} /.test(at)?at.replace(' ','T')+'Z':at):NaN,age=Date.now()-ms;
    const state=!Number.isFinite(ms)?'Not synced yet · မချိတ်ရသေး':age>150000?'Updates paused / delayed · ပြန်ချိတ်ရန်':'Results received recently · ရလဒ်ဝင်နေသည်';
    return [mode.toUpperCase()+' sync',state+(Number.isFinite(ms)?' · '+date(at):'')];
  }));
}
// Trade-only display metrics use verified REAL journal summaries. Never infer provider cutoff.
function tradeTerminalSummary(data){
  if(!data||data.mode!=='real'||data.date!==data.today)return;
  const v=data.summary||{},money=n=>Number(n||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
  byId('trade-today-pnl').textContent=(Number(v.pnl)>0?'+':'')+money(v.pnl)+' MMK';
  byId('trade-today-staked').textContent=money(v.staked)+' MMK';
  byId('trade-today-count').textContent=String(v.trades||0)+' recorded orders';
  const finished=Number(v.wins||0)+Number(v.losses||0);
  byId('trade-today-winrate').textContent=finished?(100*Number(v.wins||0)/finished).toFixed(1)+'%':'—';
  byId('trade-today-wins').textContent=String(v.wins||0)+' wins / '+String(v.losses||0)+' losses';
}
let tradeSummaryBusy=false,tradeSummaryAt=0;
async function loadTradeTerminalSummary(){
  if(tradeSummaryBusy||Date.now()-tradeSummaryAt<5000)return;
  tradeSummaryBusy=true;tradeSummaryAt=Date.now();
  try{tradeTerminalSummary(await api('/api/admin/trade-journal?mode=real'));}catch(_){/* Unavailable stays unavailable. */}
  finally{tradeSummaryBusy=false;}
}
byId('trade-open-account').addEventListener('click',()=>{
  const details=byId('trade-account-disclosure');
  details.open=true;details.scrollIntoView({block:'nearest',behavior:'smooth'});
});
function renderJournal(data,fill=false){journalData=data;renderJournalSync(data);byId('journal-date').value=data.date;if(fill){byId('journal-tp').value=data.limits.tp;byId('journal-sl').value=data.limits.sl;byId('journal-zone').value=data.limits.timezone;}const s=data.summary;const cash=v=>Number(v).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});stats('journal-stats',[[data.date===data.today?'Today net P/L · MMK':'Day net P/L · MMK',cash(s.pnl)],['Win rate',s.wins+s.losses?(100*s.wins/(s.wins+s.losses)).toFixed(1)+'%':'—'],['Wins / losses',s.wins+' / '+s.losses],['WAIT',String(s.pending)],['Orders',String(s.trades)],['Total staked · MMK',cash(s.staked)]]);const status={tp_reached:'TP reached',sl_reached:'SL reached',within_limits:'Within daily targets',limits_disabled:'Daily targets disabled'}[s.status];byId('journal-status').textContent=status+' · '+data.mode.toUpperCase()+' · '+data.date+' ('+data.limits.timezone+') · Last import: '+date(data.imported_at);byId('journal-coverage').textContent=data.coverage+(data.display_truncated?' Table limited to latest 500 rows.':'');renderJournalRows();updateDraftSummary();}
const tradeCash=value=>Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2});
const resultLabel=state=>state===1?'WIN':state===0?'LOSS':'PENDING';
const resultClass=state=>state===1?'win':state===0?'loss':'pending';
function renderJournalRows(){
  if(!journalData)return;
  const filter=byId('journal-result-filter').value;
  const search=byId('journal-search').value.trim().toUpperCase();
  const rows=journalData.rows.filter(row=>(filter==='all'||String(row.state)===filter)&&(!search||(row.issue+' '+row.side).toUpperCase().includes(search)));
  byId('journal-visible-count').textContent=rows.length+' of '+journalData.rows.length+' displayed records';
  table('journal-rows',rows,row=>[new Date(row.at).toLocaleString('en-GB',{timeZone:journalData.limits.timezone}),row.issue,row.side,tradeCash(row.stake),resultLabel(row.state),row.pnl===null?'—':tradeCash(row.pnl)]);
  if(!rows.length){byId('journal-rows').querySelector('td').textContent=journalData.rows.length?'No matching records. Clear filters or choose another date.':'No records yet for this date / mode.';return;}
  for(const [index,tr] of Array.from(byId('journal-rows').children).entries()){
    const row=rows[index],pill=document.createElement('span');pill.className='result-pill '+resultClass(row.state);pill.textContent=resultLabel(row.state);tr.children[4].replaceChildren(pill);
    if(row.pnl!==null)tr.children[5].className=row.pnl<0?'negative':row.pnl>0?'positive':'';
    tr.children[2].className='side-'+row.side.toLowerCase();
  }
}
byId('journal-result-filter').addEventListener('change',renderJournalRows);
async function loadJournal(){renderJournal(await api(journalURL()),true);await loadJournalAccount();}
byId('journal-search').addEventListener('input',renderJournalRows);
byId('journal-clear-search').addEventListener('click',()=>{byId('journal-search').value='';byId('journal-result-filter').value='all';renderJournalRows();});
byId('journal-today').addEventListener('click',()=>run(async()=>{byId('journal-date').value='';await loadJournal();},'Today journal loaded.'));
for(const id of ['journal-mode','journal-date'])byId(id).addEventListener('change',()=>{updateOrderControls();run(loadJournal,'Selected history loaded. Saved targets loaded.');});
byId('journal-limits-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{if(!journalData)throw Error('Refresh journal first.');renderJournal(await api(journalURL(),'PUT',{revision:journalData.revision,limits:journalLimits()}),true);},'Daily targets saved. Strategy rules unchanged.');});
byId('journal-import').addEventListener('click',()=>run(async()=>{if(!journalData)throw Error('Refresh journal first.');const file=byId('journal-file').files[0],text=byId('journal-json').value.trim();if(file&&text)throw Error('Choose a file or paste JSON, not both.');if(file&&file.size>8*1024*1024)throw Error('JSON file must be smaller than 8 MB.');const raw=file?await file.text():text;if(!raw)throw Error('Choose a JSON file or paste history first.');if(new Blob([raw]).size>8*1024*1024)throw Error('History must be smaller than 8 MB.');let history;try{history=JSON.parse(raw);}catch(_){throw Error('History is not valid JSON.');}const data=await api('/api/admin/trade-journal/import','POST',{revision:journalData.revision,mode:byId('journal-mode').value,source_timezone:byId('journal-source-zone').value,date:byId('journal-date').value,history});const c=data.import_result;renderJournal(data,false);byId('journal-json').value='';byId('journal-file').value='';updateDraftSummary();toast('Import: '+c.added+' added, '+c.updated+' settled/updated, '+c.unchanged+' unchanged.');},'History imported. Selected report date preserved.'));
byId('journal-export').addEventListener('click',()=>run(async()=>{const data=await api('/api/admin/trade-journal/export?mode='+byId('journal-mode').value);const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='trx-history-'+byId('journal-mode').value+'.json';document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);},'Private history exported. Keep the file somewhere safe.'));

run(async()=>{await loadSettings();const results=await Promise.allSettled([refreshLive(),loadReports(),loadStrategy('l1'),loadStrategy('twelve'),loadPolicy(),loadMessages(),loadFeed(),loadTronGrid(),loadJournal(),loadTradeFeed()]);const failed=results.find(result=>result.status==='rejected');if(failed)throw failed.reason;},'Connected. System status updates automatically.');

function restoreReady(){return settings&&strategyData.l1&&strategyData.twelve&&policyData&&messageData;}
function updateMaintenanceControls(){for(const btn of document.querySelectorAll('[data-action]'))btn.disabled=busy||maintenanceBusy;}
function updateReadyControls(){updateMaintenanceControls();updateOrderControls();for(const id of ['trade-refresh','journal-refresh'])byId(id).disabled=busy||workspaceRefreshing;for(const id of ['journal-server-refresh','journal-disconnect'])byId(id).disabled=!journalAccount?.active;for(const id of ['journal-save','journal-import','journal-export'])byId(id).disabled=!journalData;byId('restore-backup').disabled=!restoreReady();byId('export-reports').disabled=!reportData;for(const [id,ready] of [['check-trongrid',trongridData],['save-trongrid',trongridData],['clear-trongrid',trongridData],['reload-trongrid',trongridData],['default-feed',feedData],['check-feed',feedData],['reset-policy',policyData],['save-policy',policyData],['preview-streak',policyData],['save-messages',messageData],['default-message',messageData],['message-mode',messageData],['message-engine',messageData],['message-category',messageData]])byId(id).disabled=!ready;byId('feed-form').querySelector('button[type="submit"]').disabled=!feedData;}

byId('journal-copy-sync').addEventListener('click',()=>run(async()=>{
  const response=await fetch('/static/js/trxchart-history-bridge.js',{credentials:'same-origin'});
  if(!response.ok)throw Error('Connection bookmark could not be loaded.');
  const source=await response.text();
  const code='javascript:'+encodeURIComponent('(()=>{'+source+';trxHistoryBridge('+JSON.stringify(location.origin)+');})();');
  byId('journal-bookmark').value=code;byId('journal-bookmark').hidden=false;const link=byId('journal-drag-sync');link.href=code;link.hidden=false;
  try{await navigator.clipboard.writeText(code);byId('journal-sync-setup').textContent='Ready · TRX Results Sync ကို bookmarks bar ထဲ ဆွဲထည့်ပါ။ TRXChart မှာ bookmark ဖွင့် → Accept browser sync → Terminal → History. Mobile အတွက် URL လည်း copy ပြီးပါပြီ။';}
  catch(_){byId('journal-sync-setup').textContent='Ready · TRX Results Sync ကို bookmarks bar ထဲ ဆွဲထည့်ပါ။ Mobile တွင် Mobile / copy URL ကိုဖွင့်ပြီး URL ကို ကူးသိမ်းပါ။';}
},'Connection bookmark ready. Keep both tabs open for automatic history sync.'));
byId('journal-drag-sync').addEventListener('click',e=>{e.preventDefault();toast('Drag this link to your bookmarks bar, then run the saved bookmark on TRXChart.','info');});
let journalPolling=false;
setInterval(async()=>{
  if(busy||journalPolling||document.hidden||leavingAdmin||(byId('journal').hidden&&byId('trade').hidden)||!journalData)return;
  const url=journalURL();journalPolling=true;
  try{const data=await api(url);if(!busy&&url===journalURL()){renderJournal(data,false);await loadJournalAccount();}}
  catch(error){byId('journal-status').textContent='History refresh failed: '+error.message;}
  finally{journalPolling=false;}
},10000);

let reconnectFormOpen=false;
function renderJournalAccount(data){
  if(!data||typeof data.active!=='boolean'){
    journalAccount=null;renderAccountBalance(null);byId('trade-account').classList.remove('account-connected');
    byId('journal-connect-form').hidden=false;
    byId('trade-connection-badge').textContent='CONNECTION UNKNOWN';
    byId('trade-connection-badge').className='result-pill pending';
    byId('trade-account-help').textContent='Connection ကို အတည်မပြုနိုင်သေးပါ။ Check connection ကိုနှိပ်ပြီး ပြန်စစ်ပါ။';
    byId('journal-server-refresh').disabled=true;byId('journal-disconnect').disabled=true;updateOrderControls();return;
  }
  journalAccount=data;
  renderAccountBalance(data);
  if(!data.active||data.status==='expired')byId('trade-account-disclosure').open=true;
  const label={connected:'Connected · server sync ချိတ်ဆက်ပြီး',disconnected:'Not connected · မချိတ်ရသေး',expired:'Login expired · ပြန်ချိတ်ရန်',unavailable:'Sync delayed · ပြန်စမ်းနေသည်',invalid_data:'History format error · ပြန်စမ်းနေသည်',storage:'Session storage error · ပြန်ချိတ်ရန်'}[data.status]||'Connection status unknown';
  byId('journal-account-state').textContent=label+' · Last sync: '+date(data.last_sync)+(data.error?' · '+data.error:'')+(data.active&&!data.worker_alive?' · Sync worker is not running.':'');
  const healthy=data.active&&data.status==='connected'&&data.worker_alive;
  byId('trade-account').classList.toggle('account-connected',Boolean(healthy&&!reconnectFormOpen));
  byId('journal-connect-form').hidden=Boolean(healthy&&!reconnectFormOpen);
  byId('trade-account-help').textContent=healthy?'အကောင့် ချိတ်ထားပါသည်။ Email / password ပြန်ထည့်လိုပါက Connect / reconnect account ကိုနှိပ်ပါ။':data.active?'အကောင့် session ရှိသေးပေမယ့် result sync နောက်ကျနေသည်။ Status ကိုစစ်ပါ၊ လိုအပ်လျှင် အောက်က form ဖြင့် ပြန်ချိတ်ပါ။':'အကောင့် မချိတ်ထားပါ။ အောက်တွင် TRXChart Phone / Email နှင့် Password ထည့်ပြီး Connect TRXChart ကိုနှိပ်ပါ။';
  byId('journal-server-refresh').disabled=!data.active;
  byId('journal-disconnect').disabled=!data.active;
  byId('trade-connection-badge').textContent=healthy?'CONNECTED · REAL':data.active?'SYNC DELAYED':'CONNECT ACCOUNT';
  byId('trade-connection-badge').className='result-pill '+(healthy?'win':'pending');
  updateOrderControls();
}
async function loadJournalAccount(){try{renderJournalAccount(await api('/api/admin/trxchart-account'));}catch(error){renderJournalAccount(null);byId('journal-account-state').textContent='Connection status could not be refreshed: '+error.message;}await loadOrders();}
byId('trade-reconnect').addEventListener('click',()=>{reconnectFormOpen=!reconnectFormOpen;renderJournalAccount(journalAccount);if(reconnectFormOpen||!journalAccount?.active)byId('journal-account-phone').focus();});
byId('trade-check-connection').addEventListener('click',()=>run(loadJournalAccount,'Connection status refreshed.'));
byId('journal-connect-form').addEventListener('submit',e=>{e.preventDefault();run(async()=>{
  if(!journalAccount)throw Error('Connection status is still loading.');
  if(!byId('journal-account-consent').checked)throw Error('Approve encrypted session storage and history access first.');
  try{const data=await api('/api/admin/trxchart-account','POST',{revision:journalAccount.revision,consent:true,phone:byId('journal-account-phone').value.trim(),password:byId('journal-account-password').value,twofa:byId('journal-account-twofa').value.trim()});reconnectFormOpen=false;renderJournalAccount(data);renderJournal(await api(journalURL()),false);await loadTradeFeed();}
  finally{byId('journal-account-phone').value='';byId('journal-account-password').value='';byId('journal-account-twofa').value='';byId('journal-account-consent').checked=false;}
},'TRXChart connected. REAL results use fast sync while Trade is open.');});
byId('journal-server-refresh').addEventListener('click',()=>run(async()=>{renderJournalAccount(await api('/api/admin/trxchart-account/refresh','POST',{}));},'History refresh queued. Results update automatically.'));
byId('journal-disconnect').addEventListener('click',()=>run(async()=>{renderJournalAccount(await api('/api/admin/trxchart-account','DELETE',{}));},'Server session removed. Imported results are preserved.'));


// Account balance comes from the authenticated provider, never from journal P/L.
function renderAccountBalance(data){
  const value=data?.balance;
  const available=typeof value==='string'&&/^\d+\.\d{2}$/.test(value);
  stats('journal-balance-cards',[['Total Amount · REAL account balance · MMK',available?Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—']]);
  byId('trade-balance').textContent=available?Number(value).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2}):'—';
  byId('journal-balance-note').textContent=available?(data.balance_current?'Provider balance':'Last known balance · refresh pending')+' · Updated: '+date(data.balance_at):data?.active?'Waiting for TRXChart to report the account balance.':'Connect TRXChart to show your account balance.';
  byId('trade-balance-note').textContent=byId('journal-balance-note').textContent;
}

// Manual REAL orders. Demo history selection never enables this endpoint.
let orderData=null, orderReadyAt=0;
(function installOrderControls(){
  const box=document.createElement('div');
  box.innerHTML='<label class="order-amount-label">Real order amount · MMK<input id="order-amount" type="number" min="1" step="1" value="100" inputmode="numeric"></label><div class="amount-presets" aria-label="Amount presets"><button type="button" class="secondary" data-amount="100">100</button><button type="button" class="secondary" data-amount="200">200</button><button type="button" class="secondary" data-amount="500">500</button><button type="button" class="secondary" data-amount="1000">1,000</button></div><div class="order-directions"><button id="order-big" type="button" disabled>BIG · REAL</button><button id="order-small" type="button" disabled>SMALL · REAL</button></div><p id="order-result" class="order-receipt" role="status">Choose an amount, then BIG or SMALL.</p><p class="muted">REAL balance အသုံးပြုမည်။ Order တစ်ခုချင်းစီ အတည်ပြုရန် လိုသည်။</p><details class="order-settings"><summary>Order permissions &amp; status</summary><p id="order-status" role="status">Order status loading…</p><div class="actions"><button id="order-enable-all" type="button" class="secondary">Enable all manual orders</button><button id="order-disable" type="button" class="secondary">Disable manual orders</button></div></details>';
  byId('trade-order-slot').append(box);
  for(const preset of box.querySelectorAll('[data-amount]'))preset.addEventListener('click',()=>{byId('order-amount').value=preset.dataset.amount;updateOrderControls();});
})();
function updateOrderControls(){
  if(!byId('order-big'))return;
  const amount=Number(byId('order-amount').value),wait=Math.max(0,Math.ceil((orderReadyAt-Date.now())/1000));
  const valid=Number.isSafeInteger(amount)&&amount>=1;
  const capped=orderData&&((orderData.max_amount>0&&amount>orderData.max_amount)||(orderData.daily_max_count>0&&orderData.today_count>=orderData.daily_max_count)||(orderData.daily_max_total>0&&orderData.today_total+amount>orderData.daily_max_total));
  const ready=!busy&&orderData?.enabled&&journalAccount?.active&&valid&&!capped&&!wait;
  for(const id of ['order-big','order-small'])byId(id).disabled=!ready;
  for(const id of ['order-enable-all','order-disable'])byId(id).disabled=busy||!orderData;
  if(orderData){
    let reason=!journalAccount?.active?'Connect TRXChart above to activate B / S.':!orderData.enabled?'Use Enable all manual orders to activate B / S.':!valid?'Enter a positive whole-number amount.':wait?'Wait '+wait+'s before the next order.':capped?'A configured order limit was reached. Use Enable all manual orders to remove local limits.':'B / S ready · confirmation required.';
    const limits=orderData.unrestricted?'No local amount, count, daily total or spacing limits.':(orderData.max_amount>0?'Max '+orderData.max_amount+' MMK. ':'')+(orderData.daily_max_count>0?'Daily count '+orderData.daily_max_count+'. ':'')+(orderData.daily_max_total>0?'Daily total '+orderData.daily_max_total+' MMK. ':'');
    byId('order-status').textContent=(orderData.enabled?'Real orders enabled':'Real orders disabled')+' · '+reason+' '+limits+' Today: '+orderData.today_count+' attempts · '+Number(orderData.today_total).toLocaleString('en-US')+' MMK submitted.';
  }
}
async function loadOrders(){
  try{orderData=await api('/api/admin/trxchart-order');orderReadyAt=Date.now()+(orderData.retry_after_sec||0)*1000;if(orderData.max_amount>0)byId('order-amount').max=String(orderData.max_amount);else byId('order-amount').removeAttribute('max');}
  catch(error){orderData=null;byId('order-status').textContent='Order status unavailable: '+error.message;}
  updateOrderControls();
}
byId('order-amount').addEventListener('input',updateOrderControls);
setInterval(updateOrderControls,1000);
for(const [id,enabled] of [['order-enable-all',true],['order-disable',false]])byId(id).addEventListener('click',()=>run(async()=>{
  if(!orderData)throw Error('Refresh order status first.');
  orderData=await api('/api/admin/trxchart-order/settings','PUT',{revision:orderData.settings_revision,enabled,unrestricted:true});
  orderReadyAt=Date.now()+(orderData.retry_after_sec||0)*1000;
  await loadOrders();
},enabled?'All manual order permissions enabled. Local limits removed.':'Manual orders disabled.'));
for(const [id,side] of [['order-big','BIG'],['order-small','SMALL']])byId(id).addEventListener('click',()=>run(async()=>{
  const amount=Number(byId('order-amount').value);
  if(!journalAccount?.active)throw Error('Connect TRXChart above before placing an order.');
  if(!Number.isSafeInteger(amount)||amount<1||!orderData||(orderData.max_amount>0&&amount>orderData.max_amount))throw Error('Enter a positive whole-number amount within any configured limit.');
  if(!confirm('Place REAL '+side+' order for '+amount+' MMK? This uses your real balance.'))throw Error('Order cancelled.');
  const requestId=crypto.randomUUID();
  const orderDraft={id:requestId,at:new Date().toISOString(),side,stake:amount,outcome:'pending',state:-1,pnl:null};
  optimisticOrders.set(requestId,orderDraft);
  renderManualOrders(manualOrders);
  byId('order-result').textContent='WAIT · Sending one REAL order…';
  try{
    const data=await api('/api/admin/trxchart-order','POST',{direction:side,amount,mode:'real',confirm:true,request_id:requestId});
    optimisticOrders.set(requestId,{...orderDraft,outcome:data.outcome,http_status:data.http_status,reason_code:data.reason_code,message:data.message});renderManualOrders(manualOrders);
    byId('order-result').textContent=data.message+(data.ok?' Following REAL results for WIN / LOSS…':'');
    if(!data.ok)throw Error(data.message);
    notice(side+' · '+amount+' MMK · '+data.message);
  }catch(error){const row=optimisticOrders.get(requestId);if(row&&row.outcome==='pending')optimisticOrders.set(requestId,{...row,outcome:[400,401,403,409,429].includes(error.status)?'not_sent':'unknown'});renderManualOrders(manualOrders);byId('order-result').textContent=error.message;throw error;}
  finally{await loadTradeFeed();await loadOrders();await loadJournalAccount();}
},'Real order request completed. Check REAL history for settlement.'));

// This feed reads committed account history, independent of report mode/date.
// It never places or retries an order and stores only an opaque stream/cursor locally.
let tradeFeedBusy=false,tradeFeedStream=null,tradeFeedCursor=null;
let manualOrders=[],tradeSync=null,tradeFeedError=null;
let journalFeedBusy=false,workspaceRefreshing=false;
async function refreshJournalFromFeed(){if(journalFeedBusy)return;journalFeedBusy=true;const url=journalURL();try{const data=await api(url);if(!busy&&url===journalURL())renderJournal(data,false);}catch(error){byId('journal-refresh-state').textContent='Results update delayed: '+error.message;}finally{journalFeedBusy=false;}}
async function refreshWorkspace(view){
  if(busy||workspaceRefreshing||leavingAdmin)return;
  workspaceRefreshing=true;const mode=view==='trade'?'real':byId('journal-mode').value,url=journalURL(),target=byId(view==='trade'?'trade-refresh-state':'journal-refresh-state');
  const before=journalData?.synced_at?.[mode],balanceBefore=journalAccount?.balance_at;let historyUpdated=false;
  for(const id of ['trade-refresh','journal-refresh']){byId(id).disabled=true;byId(id).setAttribute('aria-busy','true');}
  target.textContent='Refreshing '+mode.toUpperCase()+' history'+(view==='trade'?' and balance':'')+'…';
  try{
    const connected=Boolean(journalAccount?.active);
    if(connected)await api('/api/admin/trxchart-account/refresh','POST',{mode});
    const until=Date.now()+12000;
    do{
      const data=await api(url);if(!busy&&url===journalURL())renderJournal(data,false);
      historyUpdated=Boolean(data.synced_at?.[mode]&&data.synced_at[mode]!==before);
      await loadTradeFeed();await loadJournalAccount();
      const balanceUpdated=view!=='trade'||(journalAccount?.balance_current&&journalAccount.balance_at!==balanceBefore);
      if(!connected||(historyUpdated&&balanceUpdated))break;
      if(Date.now()>=until)break;await new Promise(resolve=>setTimeout(resolve,750));
    }while(!leavingAdmin);
    target.textContent=!connected?'Saved history refreshed. Connect TRXChart for provider updates.':historyUpdated?mode.toUpperCase()+' history updated'+(view==='trade'&&!journalAccount?.balance_current?' · balance is last known':'')+'. Checked '+new Date().toLocaleTimeString():'Saved history reloaded; provider update still pending. '+(journalAccount?.error||'Watch the sync status.');
  }catch(error){target.textContent='Refresh failed: '+error.message;}
  finally{workspaceRefreshing=false;for(const id of ['trade-refresh','journal-refresh']){byId(id).disabled=busy;byId(id).removeAttribute('aria-busy');}}
}
byId('trade-refresh').addEventListener('click',()=>refreshWorkspace('trade'));
byId('journal-refresh').addEventListener('click',()=>refreshWorkspace('journal'));
const optimisticOrders=new Map();
function renderManualOrders(rows){
  manualOrders=rows;
  for(const row of rows)optimisticOrders.delete(row.id);
  const all=[...optimisticOrders.values(),...rows].sort((a,b)=>new Date(b.at)-new Date(a.at));
  const list=byId('trade-orders');list.replaceChildren();
  const ageOf=row=>Math.max(0,(Date.now()-new Date(row.at).valueOf())/1000);
  const waiting=all.filter(row=>row.state===-1&&['accepted','pending'].includes(row.outcome)&&ageOf(row)<=180);
  const review=all.filter(row=>row.state===-1&&['accepted','pending'].includes(row.outcome)&&ageOf(row)>180);
  byId('trade-submissions').hidden=!all.length;
  byId('trade-wait-count').textContent=waiting.length+' WAIT'+(review.length?' · '+review.length+' CHECK HISTORY':'');
  if(!all.length){const li=document.createElement('li');li.className='activity-empty';li.textContent='Your next order will appear here immediately as WAIT.';list.append(li);return;}
  for(const row of all){
    const li=document.createElement('li'),info=document.createElement('div'),title=document.createElement('strong'),detail=document.createElement('small'),result=document.createElement('div'),pill=document.createElement('span'),note=document.createElement('small');
    li.dataset.requestId=row.id;title.textContent=row.side+' · '+tradeCash(row.stake)+' MMK';detail.textContent=date(row.at)+(row.issue?' · '+row.issue:' · Round awaiting confirmation');info.append(title,detail);
    const elapsed=Math.max(0,Math.floor((Date.now()-new Date(row.at).valueOf())/1000));
    const label=row.state===1?'WIN':row.state===0?'LOSS':row.outcome==='rejected'?'REJECTED':row.outcome==='not_sent'?'NOT SENT':row.outcome==='unknown'?'UNCERTAIN':elapsed>180?'CHECK HISTORY':'WAIT';
    pill.className='result-pill '+(row.state===1?'win':row.state===0||row.outcome==='rejected'?'loss':'pending');pill.textContent=label;
    note.textContent=row.state!==-1?(row.pnl!==null?(row.pnl>0?'+':'')+tradeCash(row.pnl)+' MMK': 'Confirmed round result'):row.outcome==='pending'?'Sending · never retried':row.outcome==='accepted'?'Submitted · awaiting provider result':row.outcome==='rejected'?(row.message||('Provider rejected this order'+(Number.isInteger(row.http_status)?' (HTTP '+row.http_status+')':''))):row.outcome==='not_sent'?'Order was not submitted':'Check REAL history before another order';
    if(label==='CHECK HISTORY')note.textContent='Result not linked yet. Check verified account activity below.';
    result.className='activity-result';result.append(pill,note);if(label==='CHECK HISTORY'||row.outcome==='rejected'||row.outcome==='unknown'){const link=document.createElement('a');link.href='#journal';link.textContent=label==='CHECK HISTORY'?'Find in Results ↗':'Check REAL history ↗';link.addEventListener('click',()=>{const parts=Object.fromEntries(new Intl.DateTimeFormat('en-CA',{timeZone:journalData?.limits.timezone||'Asia/Bangkok',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(new Date(row.at)).map(p=>[p.type,p.value]));byId('journal-mode').value='real';byId('journal-date').value=parts.year+'-'+parts.month+'-'+parts.day;byId('journal-result-filter').value='all';byId('journal-search').value=row.issue||row.side;run(async()=>{const url=journalURL(),data=await api(url);if(url===journalURL())renderJournal(data,false);},'REAL history loaded. A rejected request is not a settled loss.');});result.append(link);}li.append(info,result);list.append(li);
  }
}
function renderTradeSync(){
  if(tradeFeedError){quietStatus('trade-live-state','DELAYED');byId('trade-live-state').classList.add('sync-delayed');byId('trade-feed-status').textContent='Result updates delayed: '+tradeFeedError;return;}
  if(!tradeSync){byId('trade-feed-status').textContent='Provider-confirmed results · waiting for sync status';return;}
  const age=tradeSync.last_sync?Math.max(0,Math.floor((Date.now()-new Date(tradeSync.last_sync).valueOf())/1000)):null;
  const fresh=tradeSync.active&&tradeSync.worker_alive&&tradeSync.status==='connected'&&age!==null&&age<15;
  quietStatus('trade-live-state',!tradeSync.active?'OFFLINE':fresh?'LIVE':'DELAYED');
  byId('trade-live-state').classList.toggle('sync-delayed',!fresh);
  byId('trade-feed-status').textContent=!tradeSync.active?'Connect your account to receive REAL results.':'Provider sync: '+(age===null?'not received':age+'s ago')+' · '+(fresh?'up to date':'updates delayed')+(tradeSync.provider_fetch_ms!==null&&tradeSync.provider_fetch_ms!==undefined?' · fetch '+tradeSync.provider_fetch_ms+' ms':'')+(tradeSync.error?' · '+tradeSync.error:'');
}
function savedTradeCursor(stream){try{const raw=localStorage.getItem('trx-settlement:'+stream);const n=Number(raw);return raw!==null&&Number.isSafeInteger(n)&&n>=0?n:null;}catch(_){return null;}}
function saveTradeCursor(stream,cursor){try{localStorage.setItem('trx-settlement:'+stream,String(cursor));}catch(_){} }
function settlementMessage(row){return row.side+' · '+tradeCash(row.stake)+' MMK · P/L '+(row.pnl===null?'—':tradeCash(row.pnl))+' MMK · Issue '+row.issue;}
function updateTradeTerminalActivity(rows){
  const pending=rows.filter(row=>row.state===-1);
  const amount=pending.reduce((sum,row)=>sum+Number(row.stake||0),0);
  byId('trade-open-exposure').textContent=tradeCash(amount)+' MMK';
  byId('trade-open-count').textContent=pending.length+' unsettled account orders';
  const latest=rows.find(row=>row.issue);
  byId('trade-round-issue').textContent=latest?.issue||'—';
  byId('trade-round-state').textContent='CUTOFF NOT VERIFIED';
}
function renderTradeActivity(rows){
  updateTradeTerminalActivity(rows);
  const list=byId('trade-activity');list.replaceChildren();
  if(!rows.length){const li=document.createElement('li');li.className='activity-empty';li.textContent='No REAL trades yet. Your next results will appear here.';list.append(li);quietStatus('trade-latest','No settled REAL results yet.');byId('trade-latest').className='latest-outcome';return;}
  const latest=rows.find(row=>row.state===0||row.state===1);
  quietStatus('trade-latest',latest?'Last settled: '+resultLabel(latest.state)+' · '+latest.side+' · '+(latest.pnl===null?'—':tradeCash(latest.pnl))+' MMK':'Waiting for pending orders to settle…');
  byId('trade-latest').className='latest-outcome '+(latest?resultClass(latest.state):'pending');
  for(const row of rows.slice(0,12)){
    const li=document.createElement('li'),info=document.createElement('div'),title=document.createElement('strong'),detail=document.createElement('small'),result=document.createElement('div'),pill=document.createElement('span'),pnl=document.createElement('small');
    title.textContent=row.side+' · '+tradeCash(row.stake)+' MMK';detail.textContent=row.issue+' · '+date(row.at);info.append(title,detail);
    pill.className='result-pill '+resultClass(row.state);pill.textContent=row.state===-1?'WAIT':resultLabel(row.state);pnl.textContent=row.pnl===null?'Awaiting settlement':(row.pnl>0?'+':'')+tradeCash(row.pnl)+' MMK';pnl.className=row.pnl<0?'negative':row.pnl>0?'positive':'';result.className='activity-result';result.append(pill,pnl);li.append(info,result);list.append(li);
  }
}
async function loadTradeFeed(){
  if(tradeFeedBusy||leavingAdmin)return;
  tradeFeedBusy=true;
  try{
    const params=new URLSearchParams();if(tradeFeedStream&&tradeFeedCursor!==null){params.set('stream',tradeFeedStream);params.set('after',String(tradeFeedCursor));}if(!byId('trade').hidden||(!byId('journal').hidden&&byId('journal-mode').value==='real'))params.set('watch','1');const query=params.size?'?'+params:'';
    const data=await api('/api/admin/trade-feed'+query);
    if(!Array.isArray(data.recent)||!Array.isArray(data.events)||!Number.isSafeInteger(data.cursor))throw Error('Invalid settlement feed.');
    renderTradeActivity(data.recent);
    if(!byId('trade').hidden)loadTradeTerminalSummary();
    renderManualOrders(Array.isArray(data.orders)?data.orders:[]);
    tradeFeedError=null;tradeSync=data.sync||null;renderTradeSync();
    if(!busy&&!byId('journal').hidden&&journalData&&Number.isSafeInteger(data.journal_revision)&&data.journal_revision!==journalData.revision)refreshJournalFromFeed();
    if(data.stream!==tradeFeedStream){
      tradeFeedStream=data.stream;tradeFeedCursor=data.stream?savedTradeCursor(data.stream):null;
      if(tradeFeedCursor===null||tradeFeedCursor>data.cursor)tradeFeedCursor=data.cursor;
    }else{
      const saved=data.stream?savedTradeCursor(data.stream):null;
      if(saved!==null&&saved<=data.cursor)tradeFeedCursor=Math.max(tradeFeedCursor??0,saved);
      for(const event of data.events){
        if(event.sequence<=(tradeFeedCursor??0))continue;
        const row=event.trade;if(row.state!==0&&row.state!==1)continue;
        const message=settlementMessage(row);toast(message,resultClass(row.state));
        if(document.hidden&&'Notification' in window&&Notification.permission==='granted'){
          try{const notification=new Notification(resultLabel(row.state)+' · TRXChart',{body:message,tag:data.stream+':'+event.sequence});notification.onclick=()=>{window.focus();location.hash='trade';notification.close();};}catch(_){}
        }
        tradeFeedCursor=event.sequence;
      }
      tradeFeedCursor=data.cursor;
    }
    if(data.stream)saveTradeCursor(data.stream,tradeFeedCursor);
    if(data.gap)byId('trade-feed-status').textContent+=' · Some older alerts expired. Check Trade Results.';
  }catch(error){tradeFeedError=error.message;renderTradeSync();}
  finally{tradeFeedBusy=false;}
}
setInterval(()=>{if(!leavingAdmin)loadTradeFeed();renderTradeSync();},1000);
document.addEventListener('visibilitychange',()=>{if(!document.hidden)loadTradeFeed();});
function renderTradeNotificationPermission(){
  const supported='Notification' in window;
  byId('trade-notifications').disabled=!supported||Notification.permission==='denied';
  byId('trade-notifications').textContent=supported&&Notification.permission==='granted'?'Desktop notifications enabled':'Enable desktop notifications';
  byId('trade-notification-state').textContent=!supported?'Dashboard WIN / LOSS alerts are active. Desktop notifications are unavailable in this browser.':Notification.permission==='denied'?'Dashboard alerts are active. Allow notifications in browser settings for desktop alerts.':Notification.permission==='granted'?'Dashboard alerts are active. Desktop alerts appear when this tab is in the background.':'WIN / LOSS alerts appear in this dashboard automatically.';
}
byId('trade-notifications').addEventListener('click',async()=>{if(!('Notification' in window))return;try{if(Notification.permission==='default')await Notification.requestPermission();}catch(_){}renderTradeNotificationPermission();});
renderTradeNotificationPermission();
