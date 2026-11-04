/* Human-entered labels are scoped to an observed CDR segment. */
(()=>{'use strict';
 const $=id=>document.getElementById(id),host=$('history-cdr-table'),editor=$('cdr-reason-editor'),form=$('cdr-reason-form'),dates=$('history-filters'),filters=$('history-cdr-filters');
 if(!host||!editor||!form||!dates||!filters)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b,feedback=$('cdr-reason-feedback');let active=null,serial=0;
 function clear(){serial++;active=null;form.reset();editor.hidden=true;feedback.textContent='';}
 function datesQuery(){return new URLSearchParams({from:dates.elements.from.value,to:dates.elements.to.value});}
 function attach(){for(const row of host.querySelectorAll('tr[data-cdr-id]')){if(host.dataset.classification!=='true'||row.querySelector('[data-cdr-classify]'))continue;
  const detail=row.querySelector('details');if(!detail)continue;const button=document.createElement('button');button.type='button';button.dataset.cdrClassify='1';button.textContent=t('دلیل تماس','Call reason');detail.append(button);}}
 new MutationObserver(attach).observe(host,{childList:true,subtree:true});attach();
 for(const element of [dates,filters])for(const event of ['input','change','reset'])element.addEventListener(event,clear);
 $('cdr-reason-close').addEventListener('click',clear);
 host.addEventListener('click',async event=>{const button=event.target.closest('[data-cdr-classify]');if(!button)return;const row=button.closest('tr[data-cdr-id]');if(!row||!dates.reportValidity())return;
  active=row.dataset.cdrId;const id=active,generation=++serial;editor.hidden=false;feedback.textContent=t('در حال دریافت…','Loading…');form.reset();
  try{const response=await fetch('/api/history/cdr/'+encodeURIComponent(id)+'/classification?'+datesQuery(),{credentials:'same-origin'});if(!response.ok||response.redirected)throw Error('unavailable');const data=await response.json();if(generation!==serial||active!==id)return;
   for(const key of ['reason','subreason','outcome'])form.elements[key].value=data.classification[key]||'';feedback.textContent='';form.elements.reason.focus();
  }catch{if(generation===serial)feedback.textContent=t('دلیل تماس در دسترس نیست؛ مجوز و بازه را بررسی کنید.','Classification unavailable; check permission and period.');}});
 form.addEventListener('submit',async event=>{event.preventDefault();if(!active||!form.reportValidity())return;let cfg={};try{cfg=JSON.parse($('ops-config').textContent);}catch{}if(!cfg.csrf){feedback.textContent=t('نشست معتبر لازم است.','A valid session is required.');return;}
  const id=active,generation=serial,button=form.querySelector('button[type=submit]');button.disabled=true;feedback.textContent=t('در حال ثبت…','Saving…');
  try{const payload=Object.fromEntries(['reason','subreason','outcome'].map(key=>[key,form.elements[key].value]));const response=await fetch('/api/history/cdr/'+encodeURIComponent(id)+'/classification?'+datesQuery(),{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify(payload)});if(!response.ok||response.redirected)throw Error('unavailable');if(generation===serial)feedback.textContent=t('ثبت شد.','Saved.');
  }catch{if(generation===serial)feedback.textContent=t('ثبت انجام نشد؛ دلیل، مجوز و بازه را بررسی کنید.','Could not save; check reason, permission and period.');}finally{button.disabled=false;}});
 const section=$('history-cdr-section');if(section)new MutationObserver(()=>{if(section.hidden||document.body.dataset.view!=='reports')clear();}).observe(section,{attributes:true,attributeFilter:['hidden']});
 new MutationObserver(()=>{if(document.body.dataset.view!=='reports')clear();}).observe(document.body,{attributes:true,attributeFilter:['data-view']});
})();
