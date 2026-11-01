(function(root){
'use strict';
const $=id=>document.getElementById(id);
const number=value=>String(Number(value.toFixed(4)));
const movement=value=>value>0?'↑ တက် '+number(value):value<0?'↓ ကျ '+number(Math.abs(value)):'↔ မပြောင်း 0';
const time=value=>new Date(value).toLocaleString('en-GB',{timeZone:'Asia/Bangkok',day:'2-digit',month:'2-digit',hour:'2-digit',minute:'2-digit',hour12:false});
function describe(row,replay=false){
 const forecast=movement(row.prediction);
 if(replay)return {forecast,actual:'ပြန်ကြည့်မုဒ်မှာ ဖုံးထားသည်',error:'မပြထားပါ',label:'ရလဒ်ဖုံးထားသည်',tone:'waiting'};
 if(row.status==='excluded')return {forecast,actual:'ရလဒ်ထဲ မထည့်ပါ',error:'မတွက်ပါ',label:'ထုတ်ချိန်မှာ စနေပြီးသား target',tone:'muted'};
 if(row.status==='unavailable')return {forecast,actual:'data မပြည့်စုံပါ',error:'မတွက်နိုင်ပါ',label:'data ပြတ်နေ၍ မဆုံးဖြတ်ပါ',tone:'muted'};
 if(row.status!=='completed')return {forecast,actual:'ရလဒ်စောင့်နေဆဲ',error:'မစစ်ရသေးပါ',label:'အချိန်မပြည့်သေး / data စောင့်နေဆဲ',tone:'waiting'};
 const error=Math.abs(row.prediction-row.actual);
 const exact=error<1e-8;
 const same=Math.sign(row.prediction)===Math.sign(row.actual);
 const opposite=row.prediction!==0&&row.actual!==0&&!same;
 return {forecast,actual:movement(row.actual),error:number(error)+' steps',
         label:exact?'တန်ဖိုး အတိအကျကိုက်သည်':same?'တက်/ကျ ဦးတည်ချက်ကိုက်၊ တန်ဖိုးကွာသည်':opposite?'တက်/ကျ ဦးတည်ချက် မကိုက်ပါ':'ခန့်မှန်းတန်ဖိုးနဲ့ တကယ်ဖြစ်လာတာ ကွာသည်',
         tone:exact?'exact':opposite?'different':'partial'};
}
function reset(tf,message='ခန့်မှန်းချက်နဲ့ round data ကို ရယူနေပါတယ်။'){
 $('easyTitle').textContent=tf+'m · ခန့်မှန်းချက်နှင့် ရလဒ်';
 $('easyState').textContent=message;
 $('easyTarget').textContent='Forecast ရွေးပြီးမှ သက်ဆိုင်ရာ target ကို ပြပါမယ်။';
 $('easyUpcoming').textContent='စောင့်နေသော target မသိရသေးပါ။';
 for(const id of ['easyPrediction','easyActual','easyVerdict','easyCount','easyAverage'])$(id).textContent='—';
 $('easyVerdict').className='result-verdict';
 $('easyRows').replaceChildren();
 $('easyGenerated').textContent='';
}
function render({tf,generated,status,rows,replay}){
 const completed=rows.filter(row=>row.status==='completed');
 const waiting=rows.filter(row=>row.status==='pending');
 const excluded=rows.filter(row=>row.status==='excluded').length;
 const unavailable=rows.filter(row=>row.status==='unavailable').length;
 $('easyTitle').textContent=tf+'m · ခန့်မှန်းချက်နှင့် ရလဒ်';
 $('easyState').textContent=replay?'မူလအချိန်ကို ပြန်ကြည့်နေပါတယ်။ နောက်မှထွက်တဲ့ ရလဒ်တွေကို ဖုံးထားပါတယ်။':/Feed/.test(status)?'Round data နောက်ကျနေပါတယ်။ လတ်တလောရလဒ်အဖြစ် မယူသေးပါနှင့်။':/Historical|Stale/.test(status)?'ဒီ forecast ရဲ့ ခန့်မှန်းကာလ ကုန်သွားပါပြီ။ အဟောင်းရလဒ်ကို ကြည့်နေတာပါ။':waiting.length?'ခန့်မှန်းချက် ရှိပါတယ်။ မပြည့်သေးတဲ့ target တွေရဲ့ ရလဒ်ကို စောင့်နေပါတယ်။':completed.length?'စစ်နိုင်တဲ့ ရလဒ်တွေ ပြည့်လာပါပြီ။':'စစ်နိုင်တဲ့ target မရှိပါ။ စနေပြီးသား target နဲ့ data မပြည့်တဲ့ target ကို မတွက်ပါ။';
 $('easyUpcoming').textContent=replay?'ပြန်ကြည့်မုဒ် — နောက်မှထွက်တဲ့ ရလဒ်များကို မပြထားပါ။':waiting.length?'စောင့်နေသော target · '+time(waiting[0].endMs)+' Bangkok အထိ · မူလမှ နောက် '+waiting[0].horizon+' candle · ခန့်မှန်း '+movement(waiting[0].prediction)+' · တကယ့်ရလဒ်ကို စောင့်နေဆဲပါ။':'ဒီ forecast မှာ စောင့်နေသော target မကျန်တော့ပါ။ Forecast အသစ်ကို စောင့်ပါ။';
 const selected=completed.at(-1)||waiting[0]||rows[0];
 if(selected){
  const detail=describe(selected,replay);
  $('easyTarget').textContent=(completed.length&&!replay?'နောက်ဆုံး စစ်ပြီးသော target':'ကြည့်နေသော target')+' · မူလမှ နောက် '+selected.horizon+' candle ('+(selected.horizon*tf)+' မိနစ်) · '+time(selected.startMs)+'–'+time(selected.endMs)+' Bangkok';
  $('easyPrediction').textContent=detail.forecast;
  $('easyActual').textContent=detail.actual;
  $('easyVerdict').textContent=detail.label+' · ကွာဟချက် '+detail.error;
  $('easyVerdict').className='result-verdict '+detail.tone;
 }
 $('easyCount').textContent=replay?'ပြန်ကြည့်မုဒ် — actual ရလဒ်တွေကို ဖုံးထားပါတယ်။':`စစ်ပြီး ${completed.length} ခု · စောင့်နေဆဲ ${waiting.length} ခု · စနေပြီးသားမို့ မပါဝင် ${excluded} ခု · data မပြည့် ${unavailable} ခု`;
 const mae=completed.reduce((sum,row)=>sum+Math.abs(row.prediction-row.actual),0)/completed.length;
 $('easyAverage').textContent=replay?'ပြန်ကြည့်မုဒ်မှာ ပျမ်းမျှရလဒ် မပြထားပါ။':completed.length?'ဒီ forecast ရဲ့ ပျမ်းမျှလွဲချက် '+number(mae)+' steps ပါ။ 0 ဆိုရင် အတိအကျကိုက်ပြီး၊ နည်းလေ ပိုနီးစပ်လေပါ။':'စစ်ပြီးသော target မရှိသေးလို့ ပျမ်းမျှလွဲချက် မတွက်ရသေးပါ။';
 $('easyGenerated').textContent='ခန့်မှန်းထုတ်ချိန် '+time(Date.parse(generated))+' Bangkok · အောက်က report သည် ရွေးထားသော ကာလအတွင်း forecast အများကြီးကို စုထားတာပါ။';
 $('easyRows').replaceChildren();
 for(const row of rows){
  const detail=describe(row,replay);
  const item=document.createElement('li');item.className='result-row '+detail.tone;
  for(const [label,value] of [
   ['Target','နောက် '+row.horizon+' candle · '+time(row.endMs)+' Bangkok အထိ'],
   ['ခန့်မှန်း',detail.forecast],['တကယ်ဖြစ်လာ',detail.actual],
   ['ကွာဟချက်',detail.error],['စစ်ဆေးချက်',detail.label]]){
   const cell=document.createElement('div'),title=document.createElement('small'),text=document.createElement('span');
   title.textContent=label;text.textContent=value;cell.append(title,text);item.append(cell);
  }
  $('easyRows').append(item);
 }
}
root.KronosExplain={render,reset,describe};
})(window);
