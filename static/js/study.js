/* Manual practice only. Never sends orders or modifies signal engine state. */
window.TRXStudy = (() => {
  const KEY='trx_observation_journal_v1', LIMIT=500;
  const $=id=>document.getElementById(id);
  let entries=[],frame=0,lastRender='',choicesKey='',starting=false;
  const info=()=>window.TRXChart?.studyInfo();
  function load(){try{entries=validate(JSON.parse(localStorage.getItem(KEY)||'[]'));}catch(_e){entries=[];status('Journal data မဖတ်နိုင်ပါ။ သိမ်းထားသော export ကို Import လုပ်နိုင်သည်။');}}
  function validate(raw){
    if(!Array.isArray(raw)||raw.length>LIMIT)throw new Error('Invalid journal');
    const ids=new Set();return raw.map(e=>{
      if(!e||typeof e.id!=='string'||ids.has(e.id)||typeof e.issue!=='string'||!/^\d{1,30}$/.test(e.issue)||!['BIG','SMALL'].includes(e.expected)||!['live','replay'].includes(e.mode)||typeof e.note!=='string'||e.note.length>300||!Number.isFinite(e.close)||!Number.isInteger(e.timeframe)||e.timeframe<1||e.timeframe>60||typeof e.recordedAt!=='string'||!Number.isFinite(Date.parse(e.recordedAt)))throw new Error('Invalid observation');
      ids.add(e.id);return {id:e.id.slice(0,96),issue:e.issue,expected:e.expected,mode:e.mode,note:e.note,close:e.close,timeframe:e.timeframe,recordedAt:e.recordedAt,sourceTime:String(e.sourceTime||'').slice(0,40),archived:!!e.archived,provenance:e.provenance==='imported'?'imported':'recorded',actual:['BIG','SMALL'].includes(e.actual)?e.actual:null,resultIssue:e.resultIssue?String(e.resultIssue):null};
    });
  }
  function status(text){if($('journal-status'))$('journal-status').textContent=text;}
  function persist(next=entries){try{localStorage.setItem(KEY,JSON.stringify(next));entries=next;return true;}catch(_e){status('မသိမ်းနိုင်ပါ · browser storage ပြည့်နေခြင်း/ပိတ်ထားခြင်းကို စစ်ပါ။');return false;}}
  function consecutive(a,b){
    try{if(BigInt(b.issue)===BigInt(a.issue)+1n)return true;}catch(_e){}
    // Daily rollover is allowed only with exact minute cadence and the known round boundary.
    const dt=Date.parse(String(b.block_time).replace(' ','T'))-Date.parse(String(a.block_time).replace(' ','T'));
    return String(a.issue).endsWith('1440')&&String(b.issue).endsWith('0001')&&dt>=55000&&dt<=65000;
  }
  function outcome(e,s){
    const at=s.rows.findIndex(r=>String(r.issue)===e.issue);
    if(at<0)return e.actual&&e.resultIssue&&s.mode==='live'?{actual:e.actual,text:e.actual===e.expected?'MATCH':'MISS'}:{actual:null,text:'Outside loaded history'};
    const next=s.rows[at+1];
    if(!next)return {actual:null,text:'PENDING'};
    if(!consecutive(s.rows[at],next))return {actual:null,text:'Missing next round'};
    return {actual:next.type,issue:String(next.issue),text:next.type===e.expected?'MATCH':'MISS'};
  }
  function record(event){
    event.preventDefault();const s=info();if(!s?.issue||!Number.isFinite(s.close)){status('Chart data မရှိသေးပါ။');return;}
    if(entries.length>=LIMIT){status('Journal limit 500 · Export သိမ်းထားပါ။');return;}
    if(entries.some(e=>e.issue===s.issue&&e.mode===s.mode&&e.provenance==='recorded')){status('ဒီ issue အတွက် observation ရှိပြီးသားပါ။ မူလခန့်မှန်းချက်ကို ပြန်မပြောင်းနိုင်ပါ။');return;}
    const note=$('journal-note').value.trim();if(!note){status('Observation ကို အရင်ရေးပါ။');return;}
    const e={id:Date.now().toString(36)+Math.random().toString(36).slice(2,8),issue:s.issue,sourceTime:s.time,expected:$('journal-expect').value,note:note.slice(0,300),mode:s.mode,close:s.close,timeframe:s.timeframe,recordedAt:new Date().toISOString(),archived:false,provenance:'recorded',actual:null,resultIssue:null};
    if(persist([...entries,e])){$('journal-note').value='';status('Recorded · ခန့်မှန်းချက်ကို lock လုပ်ထားပါပြီ။');lastRender='';render();}
  }
  function exportJournal(){const blob=new Blob([JSON.stringify({schema:1,exportedAt:new Date().toISOString(),observations:entries},null,2)],{type:'application/json'});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='trx-observations-'+new Date().toISOString().slice(0,10)+'.json';a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);}
  function importJournal(){
    const input=document.createElement('input');input.type='file';input.accept='.json,application/json';input.onchange=()=>{
      const file=input.files?.[0];if(!file)return;if(file.size>1024*1024){status('File limit 1 MB');return;}
      const reader=new FileReader();reader.onload=()=>{try{const data=JSON.parse(String(reader.result));const incoming=validate(data.observations||data);const known=new Set(entries.map(e=>e.id));const additions=incoming.filter(e=>!known.has(e.id)).map(e=>({...e,provenance:'imported',actual:null,resultIssue:null}));if(entries.length+additions.length>LIMIT)throw new Error('Limit 500');if(persist([...entries,...additions])){status('Imported · imported records ကို live accuracy တွင် မတွက်ပါ။');lastRender='';render();}}catch(_e){status('Invalid journal file · မူလ journal မပြောင်းထားပါ။');}};reader.readAsText(file);
    };input.click();
  }
  function render(){
    const s=info();if(!s)return;
    $('replay-controls').hidden=s.mode!=='replay';$('replay-start').disabled=starting||s.mode==='replay'||!s.issue;
    if(s.mode==='replay'){
      const key=s.timeframe+':'+s.choices.length+':'+s.choices.at(-1)?.issue;
      if(key!==choicesKey){choicesKey=key;$('replay-position').replaceChildren();s.choices.forEach(c=>{const o=document.createElement('option');o.value=c.position;o.textContent=c.position+' · '+c.time;$('replay-position').append(o);});}
      $('replay-position').value=s.position;$('replay-play').textContent=s.playing?'Pause':'Play';$('replay-prev').disabled=s.position<=1;$('replay-next').disabled=s.position>=s.total;
    }else choicesKey='';
    $('journal-basis').textContent=`${s.mode.toUpperCase()} · ${s.timeframe}m · ${s.time} · issue ${s.issue} · chart ${Number(s.close).toFixed(1)} · နောက် 1-minute result ကို မှတ်တမ်းတင်သည်။`;
    $('journal-save').disabled=!s.issue||entries.some(e=>e.issue===s.issue&&e.mode===s.mode&&e.provenance==='recorded');
    const sig=s.mode+':'+s.issue+':'+entries.length+':'+$('journal-archived').checked;
    if(sig===lastRender)return;lastRender=sig;
    const outcomes=new Map(entries.map(e=>[e.id,outcome(e,s)]));
    // Keep observed live settlements when the rolling source buffer later evicts the anchor.
    let changed=false;const nextEntries=entries.map(e=>{const o=outcomes.get(e.id);if(e.mode==='live'&&e.provenance==='recorded'&&s.mode==='live'&&o.actual&&o.issue&&(e.actual!==o.actual||e.resultIssue!==o.issue)){changed=true;return {...e,actual:o.actual,resultIssue:o.issue};}return e;});if(changed)persist(nextEntries);
    const measured=entries.filter(e=>!e.archived&&e.mode==='live'&&e.provenance==='recorded'&&outcomes.get(e.id).actual);
    const matches=measured.filter(e=>outcomes.get(e.id).actual===e.expected).length;
    $('journal-summary').textContent=`Live observations: ${measured.length} settled · ${matches} matched${measured.length?' · '+(matches/measured.length*100).toFixed(1)+'%':''} · sample only`;
    const list=$('journal-list');list.replaceChildren();
    const visible=entries.filter(e=>e.archived===$('journal-archived').checked).slice().reverse();
    if(!visible.length){const p=document.createElement('p');p.textContent='Observation မရှိသေးပါ။ နောက်ရလဒ် မမြင်ခင် အပေါ်က form မှာ ကြိုမှတ်နိုင်သည်။';list.append(p);}
    visible.forEach(e=>{
      const item=document.createElement('article');item.className='journal-entry';item.dataset.observationId=e.id;
      const row=document.createElement('div');row.className='study-row';const head=document.createElement('strong');const o=outcomes.get(e.id);
      // Do not reveal saved live outcomes while browsing a replay point before their result.
      const result=e.mode!==s.mode?'Switch to '+e.mode.toUpperCase()+' to review':o.text;
      head.textContent=`${e.mode.toUpperCase()}${e.provenance==='imported'?' · IMPORTED':''} · ${e.expected} · ${result}`;
      const archive=document.createElement('button');archive.type='button';archive.textContent=e.archived?'Restore':'Archive';archive.addEventListener('click',()=>{persist(entries.map(x=>x.id===e.id?{...x,archived:!x.archived}:x));lastRender='';render();});row.append(head,archive);
      const meta=document.createElement('p');meta.textContent=`${e.sourceTime} · issue ${e.issue} · ${e.timeframe}m · chart ${e.close.toFixed(1)}${e.mode===s.mode&&o.actual?' · actual '+o.actual:''}`;
      const note=document.createElement('p');note.textContent=e.note;item.append(row,meta,note);list.append(item);
    });
  }
  function schedule(){if(frame)return;frame=requestAnimationFrame(()=>{frame=0;render();});}
  function init(){
    if(!$('study-tools'))return;load();
    $('study-toggle').addEventListener('click',()=>{const panel=$('study-tools');panel.hidden=!panel.hidden;$('study-toggle').setAttribute('aria-expanded',String(!panel.hidden));render();});
    $('journal-toggle').addEventListener('click',()=>{const panel=$('journal-panel');panel.hidden=!panel.hidden;$('journal-toggle').setAttribute('aria-expanded',String(!panel.hidden));render();});
    $('replay-start').addEventListener('click',async()=>{if(starting)return;starting=true;render();try{await TRXChart.startReplay();}catch(_e){status('Replay မစနိုင်ပါ။ Live chart ကို ပြန်စစ်ပါ။');}finally{starting=false;render();}});
    $('replay-position').addEventListener('change',()=>TRXChart.seekReplay($('replay-position').value));
    $('replay-prev').addEventListener('click',()=>TRXChart.seekReplay(info().position-1));
    $('replay-next').addEventListener('click',()=>TRXChart.stepReplay());
    $('replay-play').addEventListener('click',()=>info().playing?TRXChart.pauseReplay():TRXChart.playReplay($('replay-speed').value));
    $('replay-speed').addEventListener('change',()=>{if(info().playing)TRXChart.playReplay($('replay-speed').value);});
    $('replay-live').addEventListener('click',()=>TRXChart.stopReplay());
    $('journal-form').addEventListener('submit',record);$('journal-export').addEventListener('click',exportJournal);$('journal-import').addEventListener('click',importJournal);
    $('journal-archived').addEventListener('change',()=>{lastRender='';render();});document.addEventListener('trx-study-change',schedule);schedule();
  }
  document.addEventListener('DOMContentLoaded',init);if(document.readyState!=='loading')init();
  return {_qa:{validate,consecutive},exportJournal};
})();
