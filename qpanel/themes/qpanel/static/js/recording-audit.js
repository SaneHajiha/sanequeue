/* Access requests are auditable; they do not prove a human heard the audio. */
(()=>{'use strict';
 const root=document.getElementById('history-detail-content');if(!root)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b;
 root.addEventListener('click',async event=>{
  const button=event.target.closest('[data-audio-audit]');if(!button)return;
  button.disabled=true;
  let panel=button.parentElement.querySelector('.recording-access-history');
  if(!panel){panel=document.createElement('section');panel.className='recording-access-history';panel.setAttribute('role','status');button.after(panel);}
  panel.replaceChildren(document.createTextNode(t('در حال دریافت سابقه…','Loading access history…')));
  try{
   const response=await fetch(button.dataset.audioAudit,{credentials:'same-origin'});
   if(response.redirected||!response.ok||!response.headers.get('content-type')?.includes('application/json'))throw Error('audit_unavailable');
   const data=await response.json(),note=document.createElement('p');
   note.className='report-note';note.textContent=t('این سابقه، درخواست دسترسی به فایل را ثبت می‌کند؛ اثبات شنیدن کل مکالمه نیست.','This records file-access requests, not proof that the whole conversation was heard.');panel.replaceChildren(note);
   const list=document.createElement('ul');
   for(const row of data.rows){const item=document.createElement('li');item.textContent=row.user+' · '+new Date(row.timestamp*1000).toLocaleString(fa?'fa-IR':'en-GB',{timeZone:'Asia/Tehran'})+' · '+(row.action==='download_request'?t('درخواست دانلود','Download request'):t('درخواست پخش','Playback request'));list.append(item);}
   if(!data.rows.length){const empty=document.createElement('p');empty.textContent=t('سابقه‌ای از شروع ثبت موجود نیست.','No requests have been recorded since auditing began.');panel.append(empty);}else panel.append(list);
   if(data.next){const next=document.createElement('button');next.type='button';next.textContent=t('سوابق قدیمی‌تر','Older requests');const url=new URL(button.dataset.audioAudit,location.origin);url.searchParams.set('before',data.next);next.dataset.audioAudit=url.pathname+url.search;panel.append(next);}
  }catch(error){panel.textContent=t('سابقه در دسترس نیست یا مجوز دیدن آن را ندارید.','History is unavailable or access is denied.');}
  finally{button.disabled=false;}
 });
})();
