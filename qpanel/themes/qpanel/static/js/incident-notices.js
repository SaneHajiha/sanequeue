/* Explicitly scoped inbound notices; saving is not route activation. */
(()=>{'use strict';
 const form=document.getElementById('incident-form');if(!form)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b,$=id=>document.getElementById(id),f=form.elements;
 const csrf=JSON.parse($('ops-config').textContent).csrf;let data=null,audio='',generation=0,pending=null,saving=false,active=false;
 let mediaJob=null,mediaTimer=null,mediaEpoch=0,mediaAttempt=0,mediaDraft=null;
 try{const stored=JSON.parse(sessionStorage.getItem('sanequeue.incident-media'));if(stored&&/^[a-f0-9]{32}$/.test(stored.id)&&typeof stored.binding==='string')mediaJob=stored;}catch{}
 function rememberMedia(){try{if(mediaJob)sessionStorage.setItem('sanequeue.incident-media',JSON.stringify(mediaJob));else sessionStorage.removeItem('sanequeue.incident-media');}catch{}}
 function editable(ready){form.querySelectorAll('input,select,button').forEach(e=>e.disabled=!ready);if(ready&&mediaJob){f.binding.disabled=true;f.audio_file.disabled=true;form.querySelector('[type=submit]').disabled=true;}}
 function draft(){return Object.fromEntries(['binding','title','starts_at','expires_at'].map(k=>[k,f[k].value]).concat([['enabled',f.enabled.checked]]));}
 function stopMedia(){++mediaEpoch;if(mediaTimer!==null)clearTimeout(mediaTimer);mediaTimer=null;}
 function scheduleMedia(){if(!active||document.visibilityState==='hidden'||!mediaJob||mediaTimer!==null)return;const epoch=mediaEpoch;mediaTimer=setTimeout(()=>{mediaTimer=null;pollMedia(epoch);},Math.min(15000,2000*2**Math.min(mediaAttempt,3)));}
 async function pollMedia(epoch){if(!active||document.visibilityState==='hidden'||!mediaJob||epoch!==mediaEpoch)return;const id=mediaJob.id;
  try{const value=await api('/media/'+id);if(epoch!==mediaEpoch||!active||mediaJob?.id!==id)return;
   if(value.state==='completed'){audio=value.audio;f.audio_file.value='';preview();mediaJob=null;mediaAttempt=0;rememberMedia();editable(Boolean(data&&Object.keys(data.bindings).length));$('incident-feedback').textContent=t('تبدیل صوت کامل شد؛ پیش‌نمایش را بررسی و برای ثبت تنظیم، دوباره «ثبت نسخهٔ پیام» را بزنید.','Audio conversion completed. Check the preview, then Save notice version to publish the setting.');}
   else if(['failed','cancelled'].includes(value.state)){const error=Error(value.error||'media_conversion_failed');error.terminal=true;throw error;}
   else{mediaAttempt++;$('incident-feedback').textContent=value.state==='running'?t('صوت در کارگر محدود در حال تبدیل است؛ تنظیم هنوز ثبت نشده.','Audio is converting in the limited worker; the setting is not saved yet.'):t('تبدیل صوت در صف است؛ تبدیل یا ثبت هنوز کامل نشده.','Audio conversion is queued; neither conversion nor setting publication is complete.');scheduleMedia();}
  }catch(e){if(epoch!==mediaEpoch||!active)return;
   if(e.terminal||[401,403,404].includes(e.status)){mediaJob=null;rememberMedia();if(e.status===403)invalidate();else editable(Boolean(data&&Object.keys(data.bindings).length));$('incident-feedback').textContent=t('تبدیل صوت ناموفق یا دسترسی لغو شد: ','Audio conversion failed or access was revoked: ')+e.message;}
   else{mediaAttempt++;$('incident-feedback').textContent=t('وضعیت تبدیل دریافت نشد؛ نتیجه نامشخص است. در صورت ادامهٔ خطا بازخوانی کنید.','Conversion status is unavailable; outcome is unknown. Refresh if the error persists.');if(mediaAttempt<=5)scheduleMedia();}
  }
 }
 function invalidate(){data=null;audio='';editable(false);preview();}
 async function api(path='',options={}){const r=await fetch('/api/pbx/incidents'+path,{credentials:'same-origin',...options,headers:{'X-CSRF-Token':csrf,...options.headers}});if(r.redirected||!r.headers.get('content-type')?.includes('application/json')){const error=Error(r.redirected?'login_required':'request_failed');error.status=r.redirected?401:r.status>=400?r.status:502;throw error;}const v=await r.json();if(!r.ok){const error=Error(v.error||'request_failed');error.status=r.status;throw error;}return v;}
 const localDate=value=>{const d=new Date(value*1000);return new Date(d.getTime()-d.getTimezoneOffset()*60000).toISOString().slice(0,16);};
 const date=value=>new Date(value*1000).toLocaleString(fa?'fa-IR':'en-GB',{timeZone:'Asia/Tehran'});
 function preview(){const a=$('incident-audio');a.hidden=!audio;if(audio)a.src='/api/pbx/incidents/audio/'+audio;else a.removeAttribute('src');}
 function fill(){const row=data?.notices.find(r=>r.binding===f.binding.value);audio=row?.audio||'';f.title.value=row?.title||'';f.enabled.checked=row?.enabled||false;f.starts_at.value=localDate(row?.starts_at||Date.now()/1000);f.expires_at.value=localDate(row?.expires_at||Date.now()/1000+3600);f.audio_file.value='';preview();}
 function cell(row,value){const td=document.createElement('td');td.textContent=value;row.append(td);}
 function render(v){data=v;const selected=f.binding.value;f.binding.replaceChildren();for(const [id,b] of Object.entries(v.bindings)){const o=new Option(b.label+' · '+b.queue,id);f.binding.add(o);}if(v.bindings[selected])f.binding.value=selected;
  const ready=Object.keys(v.bindings).length>0;editable(ready);
  $('incident-integration').textContent=ready?t('نقطهٔ مجاز ثبت شده؛ نصب و آزمون hook باید توسط مدیر فنی تأیید شود. ذخیره به معنی پخش زنده نیست.','Approved points are registered; hook installation and test calls still require technical verification. Saved does not mean live.'):t('هنوز نقطهٔ اتصال مجاز نصب نشده است؛ مسیر تماس دست‌نخورده است.','No approved integration point is installed; call routing is unchanged.');fill();
  if(mediaJob&&v.bindings[mediaJob.binding]){f.binding.value=mediaJob.binding;if(mediaDraft){for(const key of ['title','starts_at','expires_at'])f[key].value=mediaDraft[key];f.enabled.checked=mediaDraft.enabled;}scheduleMedia();}
  else if(mediaJob){stopMedia();mediaJob=null;rememberMedia();editable(ready);}
  const wrap=$('incident-current');wrap.replaceChildren();if(!v.notices.length){wrap.textContent=t('پیامی ثبت نشده است.','No notices saved.');return;}
  const table=document.createElement('table'),head=document.createElement('tr'),thead=document.createElement('thead'),body=document.createElement('tbody');for(const label of [t('عنوان','Title'),t('صف','Queue'),t('نسخه','Revision'),t('اعتبار','Validity'),t('وضعیت تنظیم','Configured state')]){const th=document.createElement('th');th.textContent=label;head.append(th);}thead.append(head);table.append(thead,body);
  for(const n of v.notices){const row=document.createElement('tr');cell(row,n.title);cell(row,v.bindings[n.binding]?.queue||t('نقطه حذف شده','Binding removed'));cell(row,n.revision);cell(row,date(n.starts_at)+' — '+date(n.expires_at));const now=Date.now()/1000;cell(row,!n.enabled?t('غیرفعال','Disabled'):now<n.starts_at?t('زمان آینده','Scheduled'):now>=n.expires_at?t('منقضی','Expired'):t('مجاز در این بازه؛ پخش نیازمند hook','Eligible now; playback requires hook'));body.append(row);}wrap.append(table);
 }
 function load(force=false){
  if(!active||saving)return Promise.resolve();if(pending&&!force)return pending;
  const request=++generation;if(mediaJob)mediaDraft=draft();invalidate();
  $('incident-integration').textContent=t('بررسی نقاط اتصال مجاز…','Checking approved integration points…');
  const task=(async()=>{try{const value=await api();if(request!==generation)return;render(value);$('incident-feedback').textContent='';}
   catch(e){if(request!==generation)return;invalidate();f.binding.replaceChildren();$('incident-integration').textContent=t('فهرست مجاز قابل تأیید نیست؛ پیش از ثبت، بازخوانی کنید.','Approved bindings could not be verified; refresh before saving.');$('incident-feedback').textContent=t('دریافت ناموفق: ','Load failed: ')+e.message;}
   finally{if(request===generation)pending=null;}
  })();pending=task;return task;
 }
 f.binding.onchange=fill;$('incident-refresh').onclick=()=>load(true);
 $('incident-timezone').textContent=t('منطقهٔ زمانی ورودی: ','Input timezone: ')+Intl.DateTimeFormat().resolvedOptions().timeZone;
 form.onsubmit=async event=>{event.preventDefault();if(saving||pending||mediaJob||!active||!data||!Object.hasOwn(data.bindings,f.binding.value))return;
  const current=data.notices.find(n=>n.binding===f.binding.value),request=++generation,file=f.audio_file.files[0];
  const value={binding:f.binding.value,title:f.title.value,enabled:f.enabled.checked,starts_at:new Date(f.starts_at.value).getTime()/1000,expires_at:new Date(f.expires_at.value).getTime()/1000,audio,expected_revision:current?.revision||0};
  saving=true;editable(false);$('incident-refresh').disabled=true;
  try{if(file){if(file.size>8*1024*1024)throw Error(t('حداکثر ۸ مگابایت','Maximum 8 MB'));const body=new FormData();body.set('audio',file);body.set('binding',value.binding);const uploaded=await api('/audio',{method:'POST',body});
    if(!/^[a-f0-9]{32}$/.test(uploaded.id)||!['queued','running'].includes(uploaded.state))throw Error('invalid_media_job_response');mediaJob={id:uploaded.id,binding:value.binding};mediaDraft=draft();mediaAttempt=0;rememberMedia();
    if(request!==generation)return;$('incident-feedback').textContent=t('درخواست تبدیل ثبت شد؛ صوت هنوز تبدیل نشده و تنظیم پیام نیز ذخیره نشده است.','Conversion queued. Audio is not converted and the notice setting is not saved yet.');scheduleMedia();return;}
   if(request!==generation)return;const saved=await api('',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(value)});if(request!==generation)return;
   render(saved);$('incident-feedback').textContent=t('نسخه ثبت شد. نتیجهٔ تماس واقعی، نصب hook را تأیید می‌کند؛ ذخیره به معنی پخش نیست.','Version saved. Verify integration with a real test call; saving is not proof of playback.');
  }catch(e){if(request!==generation)return;invalidate();$('incident-integration').textContent=t('پیش از تلاش دوباره، فهرست مجاز را بازخوانی کنید.','Refresh approved bindings before trying again.');$('incident-feedback').textContent=t('ثبت ناموفق: ','Save failed: ')+e.message;}
  finally{saving=false;$('incident-refresh').disabled=false;if(request===generation)editable(Boolean(data&&Object.keys(data.bindings).length));else if(active)load();}
 };
 function syncView(){const visible=document.body.dataset.view==='telephony';if(visible===active)return;active=visible;
  if(active)load();else{if(mediaJob)mediaDraft=draft();stopMedia();++generation;pending=null;invalidate();}
 }
 editable(false);
 new MutationObserver(syncView).observe(document.body,{attributes:true,attributeFilter:['data-view']});
 document.addEventListener('visibilitychange',()=>{if(document.visibilityState==='hidden')stopMedia();else scheduleMedia();});
 if(typeof window!=='undefined')window.addEventListener('pagehide',stopMedia);
 syncView();
})();
