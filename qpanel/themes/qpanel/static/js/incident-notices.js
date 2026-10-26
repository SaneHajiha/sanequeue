/* Explicitly scoped inbound notices; saving is not route activation. */
(()=>{'use strict';
 const form=document.getElementById('incident-form');if(!form)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b,$=id=>document.getElementById(id),f=form.elements;
 const csrf=JSON.parse($('ops-config').textContent).csrf;let data=null,audio='';
 async function api(path='',options={}){const r=await fetch('/api/pbx/incidents'+path,{credentials:'same-origin',...options,headers:{'X-CSRF-Token':csrf,...options.headers}});if(r.redirected||!r.headers.get('content-type')?.includes('application/json'))throw Error('login_required');const v=await r.json();if(!r.ok)throw Error(v.error||'request_failed');return v;}
 const localDate=value=>{const d=new Date(value*1000);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};
 const date=value=>new Date(value*1000).toLocaleString(fa?'fa-IR':'en-GB',{timeZone:'Asia/Tehran'});
 function preview(){const a=$('incident-audio');a.hidden=!audio;if(audio)a.src='/api/pbx/incidents/audio/'+audio;else a.removeAttribute('src');}
 function fill(){const row=data?.notices.find(r=>r.binding===f.binding.value);audio=row?.audio||'';f.title.value=row?.title||'';f.enabled.checked=row?.enabled||false;f.starts_at.value=localDate(row?.starts_at||Date.now()/1000);f.expires_at.value=localDate(row?.expires_at||Date.now()/1000+3600);f.audio_file.value='';preview();}
 function cell(row,value){const td=document.createElement('td');td.textContent=value;row.append(td);}
 function render(v){data=v;const selected=f.binding.value;f.binding.replaceChildren();for(const [id,b] of Object.entries(v.bindings)){const o=new Option(b.label+' · '+b.queue,id);f.binding.add(o);}if(v.bindings[selected])f.binding.value=selected;
  const ready=Object.keys(v.bindings).length>0;form.querySelectorAll('input,select,button').forEach(e=>e.disabled=!ready);
  $('incident-integration').textContent=ready?t('نقطهٔ مجاز ثبت شده؛ نصب و آزمون hook باید توسط مدیر فنی تأیید شود. ذخیره به معنی پخش زنده نیست.','Approved points are registered; hook installation and test calls still require technical verification. Saved does not mean live.'):t('هنوز نقطهٔ اتصال مجاز نصب نشده است؛ مسیر تماس دست‌نخورده است.','No approved integration point is installed; call routing is unchanged.');fill();
  const wrap=$('incident-current');wrap.replaceChildren();if(!v.notices.length){wrap.textContent=t('پیامی ثبت نشده است.','No notices saved.');return;}
  const table=document.createElement('table'),head=document.createElement('tr'),thead=document.createElement('thead'),body=document.createElement('tbody');for(const label of [t('عنوان','Title'),t('صف','Queue'),t('نسخه','Revision'),t('اعتبار','Validity'),t('وضعیت تنظیم','Configured state')]){const th=document.createElement('th');th.textContent=label;head.append(th);}thead.append(head);table.append(thead,body);
  for(const n of v.notices){const row=document.createElement('tr');cell(row,n.title);cell(row,v.bindings[n.binding]?.queue||t('نقطه حذف شده','Binding removed'));cell(row,n.revision);cell(row,date(n.starts_at)+' — '+date(n.expires_at));const now=Date.now()/1000;cell(row,!n.enabled?t('غیرفعال','Disabled'):now<n.starts_at?t('زمان آینده','Scheduled'):now>=n.expires_at?t('منقضی','Expired'):t('مجاز در این بازه؛ پخش نیازمند hook','Eligible now; playback requires hook'));body.append(row);}wrap.append(table);
 }
 async function load(){try{render(await api());}catch(e){$('incident-feedback').textContent=t('دریافت ناموفق: ','Load failed: ')+e.message;}}
 f.binding.onchange=fill;$('incident-refresh').onclick=load;
 $('incident-timezone').textContent=t('منطقهٔ زمانی ورودی: ','Input timezone: ')+Intl.DateTimeFormat().resolvedOptions().timeZone;
 form.onsubmit=async event=>{event.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
  try{const file=f.audio_file.files[0];if(file){if(file.size>8*1024*1024)throw Error(t('حداکثر ۸ مگابایت','Maximum 8 MB'));const body=new FormData();body.set('audio',file);audio=(await api('/audio',{method:'POST',body})).audio;preview();}
   const current=data.notices.find(n=>n.binding===f.binding.value);const value={binding:f.binding.value,title:f.title.value,enabled:f.enabled.checked,starts_at:new Date(f.starts_at.value).getTime()/1000,expires_at:new Date(f.expires_at.value).getTime()/1000,audio,expected_revision:current?.revision||0};
   render(await api('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)}));$('incident-feedback').textContent=t('نسخه ثبت شد. نتیجهٔ تماس واقعی، نصب hook را تأیید می‌کند؛ ذخیره به معنی پخش نیست.','Version saved. Verify integration with a real test call; saving is not proof of playback.');
  }catch(e){$('incident-feedback').textContent=t('ثبت ناموفق: ','Save failed: ')+e.message;}finally{button.disabled=!data||!Object.keys(data.bindings).length;}
 };
 document.addEventListener('click',event=>{if(event.target.closest('button[data-view="telephony"]'))load();});
})();
