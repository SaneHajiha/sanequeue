'use strict';
(() => {
 const cfg=JSON.parse(document.getElementById('ops-config').textContent),fa=document.documentElement.lang==='fa';
 const t=(a,b)=>fa?a:b,esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 async function load(kind){
  const root=document.getElementById(kind+'-content');if(!root)return;
  root.innerHTML=`<p class="report-note">${t('در حال دریافت…','Loading…')}</p>`;
  try{
   const response=await fetch('/api/planning/'+kind,{credentials:'same-origin'});if(!response.ok)throw Error();const data=await response.json();
   const selects=`<label>${t('صف','Queue')}<select name="queue" required>${data.queues.map(q=>`<option>${esc(q)}</option>`).join('')}</select></label>`;
   const fields=kind==='shifts'?`<label>${t('کارشناس / حساب','Agent / account')}<input name="agent" maxlength="100" required></label><label>${t('شروع (زمان محلی مرورگر)','Start (browser local time)')}<input name="starts" type="datetime-local" required></label><label>${t('پایان','End')}<input name="ends" type="datetime-local" required></label>`:`<label>${t('نام','Name')}<input name="name" maxlength="100" required></label><label>${t('شماره','Phone')}<input name="phone" dir="ltr" maxlength="40" required></label>`;
   root.innerHTML=(data.editable?`<form class="report-filters" data-planning-form="${kind}">${selects}${fields}<label>${t('یادداشت','Note')}<input name="note" maxlength="300"></label><button class="primary" type="submit">${t('افزودن','Add')}</button></form>`:'')+`<div class="table-wrap"><table><thead><tr><th>${t('صف','Queue')}</th><th>${kind==='shifts'?t('کارشناس','Agent'):t('نام','Name')}</th><th>${kind==='shifts'?t('زمان برنامه‌ریزی‌شده','Scheduled time'):t('شماره','Phone')}</th><th>${t('یادداشت','Note')}</th><th></th></tr></thead><tbody>${data.rows.map(row=>`<tr><td>${esc(row.queue)}</td><td>${esc(row.agent||row.name)}</td><td>${kind==='shifts'?esc(new Date(row.starts*1000).toLocaleString(fa?'fa-IR':'en-GB')+' — '+new Date(row.ends*1000).toLocaleString(fa?'fa-IR':'en-GB')):esc(row.phone)}</td><td>${esc(row.note)}</td><td>${data.editable?`<button data-planning-delete="${kind}" data-id="${row.id}" data-queue="${esc(row.queue)}">${t('حذف','Delete')}</button>`:''}</td></tr>`).join('')||`<tr><td colspan="5" class="empty">${t('موردی ثبت نشده است.','No records yet.')}</td></tr>`}</tbody></table></div><p class="report-note" role="status" id="${kind}-message"></p>`;
  }catch{root.innerHTML=`<p class="notice">${t('دریافت داده ممکن نیست؛ نشست و ارتباط مرکز تلفن را بررسی کنید.','Could not load records. Check your session and PBX connection.')}</p>`;}
 }
 async function save(kind,payload){const response=await fetch('/api/planning/'+kind,{method:'POST',credentials:'same-origin',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify(payload)});const result=await response.json();if(!response.ok)throw Error(result.error||'request_failed');await load(kind);}
 document.addEventListener('click',async event=>{
  const nav=event.target.closest('[data-view]');if(nav&&['shifts','directory'].includes(nav.dataset.view))load(nav.dataset.view);
  const refresh=event.target.closest('[data-planning-load]');if(refresh)load(refresh.dataset.planningLoad);
  const del=event.target.closest('[data-planning-delete]');if(del&&confirm(t('این مورد حذف شود؟','Delete this record?'))){try{await save(del.dataset.planningDelete,{id:Number(del.dataset.id),queue:del.dataset.queue,delete:true});}catch(error){alert(t('حذف انجام نشد.','Could not delete record.'));}}
 });
 document.addEventListener('submit',async event=>{const form=event.target.closest('[data-planning-form]');if(!form)return;event.preventDefault();const kind=form.dataset.planningForm,payload=Object.fromEntries(new FormData(form)),submit=form.querySelector('[type=submit]');submit.disabled=true;
  try{if(kind==='shifts'){payload.starts=new Date(payload.starts).toISOString();payload.ends=new Date(payload.ends).toISOString();}await save(kind,payload);}catch(error){document.getElementById(kind+'-message').textContent=error.message==='overlapping_shift'?t('این کارشناس در بازه انتخاب‌شده شیفت دیگری دارد.','This agent already has an overlapping shift.'):t('ذخیره انجام نشد؛ مقادیر و دسترسی را بررسی کنید.','Could not save. Check values and permissions.');}finally{submit.disabled=false;}
 });
})();
