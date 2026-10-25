'use strict';
(() => {
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b,$=id=>document.getElementById(id);
 const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const num=value=>new Intl.NumberFormat(fa?'fa-IR':'en-US',{maximumFractionDigits:0}).format(value);
 const elapsed=value=>{const seconds=Math.max(0,Math.floor(Number(value)||0));return [Math.floor(seconds/3600),Math.floor(seconds/60)%60,seconds%60].map(x=>String(x).padStart(2,'0')).join(':');};
 const dateLabel=stamp=>new Date(stamp).toLocaleDateString(fa?'fa-IR-u-ca-persian':'en-GB-u-ca-gregory',{timeZone:'Asia/Tehran',year:'numeric',month:'long',day:'numeric',weekday:'short'});
 const timeLabel=stamp=>new Date(stamp*1000).toLocaleString(fa?'fa-IR-u-ca-persian':'en-GB-u-ca-gregory',{timeZone:'Asia/Tehran',dateStyle:'short',timeStyle:'medium'});
 const dayISO=date=>{const parts=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tehran',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(date);return ['year','month','day'].map(k=>parts.find(p=>p.type===k).value).join('-');};
 const states={available:t('آماده دریافت تماس','Ready'),on_call:t('مکالمه','On call'),ringing:t('زنگ‌خوردن','Ringing'),hold:t('انتظار حین تماس','Call on hold'),busy:t('مشغول','Busy'),wrap_up:t('کار پس از تماس','Wrap-up'),paused:t('توقف موقت','Paused'),removed:t('خارج از عضویت صف','Removed from queue'),offline:t('آفلاین','Offline'),unknown:t('نامشخص','Unknown')};
 let selfOnly=true,loading=false;
 const dialog=$('activity-dialog');if(!dialog)return;
 $('activity-day').innerHTML=Array.from({length:91},(_,i)=>{const date=new Date(Date.now()-i*86400000),iso=dayISO(date);return `<option value="${iso}">${esc(dateLabel(date))}</option>`;}).join('');
 async function load(){
  if(loading)return;loading=true;$('activity-results').setAttribute('aria-busy','true');$('activity-feedback').textContent=t('در حال دریافت کارکرد…','Loading activity…');
  try{
   const day=$('activity-day').value,queue=$('activity-queue').value;
   const response=await fetch((selfOnly?'/api/profile/activity':'/api/activity/daily')+'?'+new URLSearchParams({day,queue}),{credentials:'same-origin'});
   const result=await response.json();if(!response.ok)throw Error(result.error||'request_failed');
   if(!queue)$('activity-queue').innerHTML=`<option value="">${t('همه صف‌های مجاز','All permitted queues')}</option>`+result.queues.map(q=>`<option value="${esc(q)}">${esc(q)}</option>`).join('');
   const groups=new Map();for(const row of result.rows){const key=row.queue+'|'+row.agent;if(!groups.has(key))groups.set(key,{queue:row.queue,agent:row.agent,rows:[]});groups.get(key).rows.push(row);}
   $('activity-results').innerHTML=[...groups.values()].map(group=>{
    const duty=group.rows.reduce((sum,r)=>sum+(r.on_duty?r.seconds:0),0),observed=group.rows.reduce((sum,r)=>sum+r.seconds,0);
    const first=Math.min(...group.rows.map(r=>r.first)),last=Math.max(...group.rows.map(r=>r.last));
    return `<article class="activity-card"><header><h3><bdi dir="ltr">${esc(group.agent)}</bdi></h3><span class="activity-queue-chip">${t('صف','Queue')} ${esc(group.queue)}</span></header><div class="activity-totals"><div><small>${t('فعال در صف','On duty in queue')}</small><b dir="ltr">${elapsed(duty)}</b></div><div><small>${t('توقف / خارج / آفلاین','Paused / removed / offline')}</small><b dir="ltr">${elapsed(observed-duty)}</b></div></div><p class="muted">${esc(timeLabel(first))} — ${esc(timeLabel(last))}</p><div class="activity-breakdown">${group.rows.map(row=>`<div><span>${esc(states[row.state]||row.state)}${row.reason?' · '+esc(row.reason_label||row.reason):''}</span><b dir="ltr">${elapsed(row.seconds)}</b><meter min="0" max="${observed||1}" value="${row.seconds}">${num(row.seconds)}</meter></div>`).join('')}</div></article>`;
   }).join('')||`<div class="empty">${t('در این روز مشاهده‌ای برای این عضویت‌ها ثبت نشده است.','No membership observations recorded for this day.')}</div>`;
   $('activity-feedback').textContent=t('تاریخ انتخابی: ','Selected date: ')+dateLabel(day+'T12:00:00Z')+' · '+(result.observed_until?t('آخرین مشاهده: ','Last observation: ')+timeLabel(result.observed_until):t('ثبت کارکرد هنوز شروع نشده است.','Activity recording has not started.'));
  }catch(error){$('activity-feedback').textContent=t('دریافت کارکرد ناموفق: ','Activity unavailable: ')+error.message;}
  finally{loading=false;$('activity-results').removeAttribute('aria-busy');}
 }
 document.addEventListener('click',event=>{const button=event.target.closest('[data-activity-open]');if(!button)return;selfOnly=button.dataset.activityOpen==='self';$('profile-dialog')?.close();$('activity-queue').innerHTML=`<option value="">${t('همه صف‌های مجاز','All permitted queues')}</option>`;dialog.showModal();load();});
 $('activity-close').onclick=()=>dialog.close();$('activity-refresh').onclick=load;$('activity-day').onchange=load;$('activity-queue').onchange=load;
})();
