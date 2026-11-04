/* Picker lists only extensions observed in the selected period and authorized by the server. */
(()=>{'use strict';
 const dates=document.getElementById('history-filters');if(!dates)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b;
 for(const id of ['history-cdr-filters','pbx-performance-filters','pbx-reason-filters']){
  const form=document.getElementById(id),input=form?.elements.endpoint;if(!input)continue;
  const details=document.createElement('details'),summary=document.createElement('summary'),status=document.createElement('p'),list=document.createElement('div');
  details.className='pbx-endpoint-picker';summary.textContent=t('انتخاب از داخلی‌های دارای تماس','Choose from extensions with calls');status.setAttribute('role','status');status.setAttribute('aria-live','polite');details.append(summary,status,list);input.parentElement.insertAdjacentElement('afterend',details);let serial=0;
  const selected=()=>new Set(input.value.split(',').map(x=>x.trim()).filter(Boolean));
  async function load(){const gen=++serial;if(!dates.reportValidity())return;list.replaceChildren();status.textContent=t('در حال دریافت داخلی‌ها…','Loading extensions…');
   try{const query=new URLSearchParams({from:dates.elements.from.value,to:dates.elements.to.value});const response=await fetch('/api/history/cdr/summary?'+query,{credentials:'same-origin'});if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw Error();const data=await response.json();if(gen!==serial||!details.open)return;
    if(!data.can_search_numbers){status.textContent=t('مجوز مشاهدهٔ داخلی‌ها لازم است.','Permission to view extensions is required.');return;}
    const endpoints=data.endpoints.map(x=>x.endpoint).filter(x=>typeof x==='string'&&/^(SIP|PJSIP)\/[A-Za-z0-9_.-]{1,48}$/.test(x));const chosen=selected();
    for(const endpoint of endpoints){const label=document.createElement('label'),box=document.createElement('input'),text=document.createElement('span');box.type='checkbox';box.checked=chosen.has(endpoint);text.textContent=endpoint;box.addEventListener('change',()=>{const current=selected();if(box.checked){if(current.size>=20){box.checked=false;status.textContent=t('حداکثر ۲۰ داخلی انتخاب کنید.','Select at most 20 extensions.');return;}current.add(endpoint);}else current.delete(endpoint);input.value=[...current].join(', ');input.dispatchEvent(new Event('input',{bubbles:true}));status.textContent='';});label.append(box,text);list.append(label);}
    status.textContent=endpoints.length?'':t('در بازهٔ انتخابی داخلی مشاهده‌شده‌ای وجود ندارد.','No observed extensions in this period.');
   }catch{if(gen===serial)status.textContent=t('فهرست داخلی‌ها در دسترس نیست.','Extension list unavailable.');}}
  details.addEventListener('toggle',()=>{if(details.open)load();else serial++;});for(const e of ['input','change'])dates.addEventListener(e,()=>{serial++;details.open=false;list.replaceChildren();status.textContent='';});
  form.addEventListener('reset',()=>{serial++;details.open=false;list.replaceChildren();status.textContent='';});
 }
})();
