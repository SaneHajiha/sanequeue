/* Organizational reports: server scopes every request; never cache grants. */
(()=>{'use strict';
 const $=id=>document.getElementById(id),section=$('history-unit-section'),dates=$('history-filters');
 if(!section||!dates)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b,locale=fa?'fa-IR':'en-GB';
 const feedback=$('unit-report-feedback'),summary=$('unit-report-summary'),host=$('unit-report-table'),nextButton=$('unit-report-next'),filters=$('unit-report-filters');
 let cursor=null,serial=0,queueSerial=0,visitSerial=0,visitCursor=null,visitRows=[],rows=[];
 const datesParams=()=>new URLSearchParams({from:dates.elements.from.value,to:dates.elements.to.value});
 const params=()=>{const p=datesParams();for(const [key,value] of new FormData(filters))if(value)p.set(key,value);return p;};
 const cell=(tag,text)=>{const x=document.createElement(tag);x.textContent=text??'—';return x;};
 const number=v=>v==null?'—':Number(v).toLocaleString(locale,{maximumFractionDigits:1});
 async function api(url,options){const response=await fetch(url,{credentials:'same-origin',...options});if(!response.ok)throw Error(String(response.status));return response.json();}
 function showTable(){const table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');
  [t('زمان','Time'),t('مبدأ','Source'),t('مقصد','Destination'),t('جهت','Direction'),t('وضعیت','Status'),t('مدت ثانیه','Duration s'),t('ضبط','Recording')].forEach(x=>tr.append(cell('th',x)));head.append(tr);table.append(head);
  const body=document.createElement('tbody');for(const row of rows){const line=document.createElement('tr');
   const direction={inbound:t('ورودی','Inbound'),outbound:t('خروجی','Outbound'),internal:t('داخلی','Internal'),unknown:t('نامعلوم','Unknown')}[row.direction]||t('نامعلوم','Unknown');
   const disposition={ANSWERED:t('پاسخ‌داده','Answered'),BUSY:t('مشغول','Busy'),'NO ANSWER':t('بی‌پاسخ','No answer'),FAILED:t('ناموفق','Failed'),UNKNOWN:t('نامعلوم','Unknown')}[row.disposition]||row.disposition;
   [new Date(row.ts*1000).toLocaleString(locale,{timeZone:'Asia/Tehran'}),row.src,row.dst,direction,disposition,window.SaneQueueReportDuration(row.duration)].forEach(x=>line.append(cell('td',x)));const recording=cell('td','');const item=row.recording;if(item&&/^[A-Za-z0-9_-]{43}$/.test(item.ref)){const url='/api/organization/reports/recording/'+item.ref;if(item.play){const audio=document.createElement('audio');audio.controls=true;audio.preload='none';audio.src=url;audio.setAttribute('aria-label',t('پخش ضبط پس از بررسی مالکیت','Play recording after ownership verification'));recording.append(audio);}if(item.download){const link=cell('a',t('دانلود','Download'));link.href=url+'?download=1';recording.append(link);}}else recording.textContent='—';line.append(recording);body.append(line);}
  table.append(body);host.replaceChildren(table);}
 function reset(){serial++;queueSerial++;visitSerial++;visitCursor=null;visitRows=[];cursor=null;rows=[];summary.replaceChildren();host.replaceChildren();nextButton.hidden=true;feedback.textContent='';$('unit-ai-feedback').textContent='';$('unit-trend-table').replaceChildren();$('unit-trend-feedback').textContent='';$('unit-queue-table').replaceChildren();$('unit-queue-feedback').textContent='';$('unit-queue-visits-table').replaceChildren();$('unit-queue-visits-feedback').textContent='';$('unit-queue-visits-next').hidden=true;window.SaneQueueReportCharts?.clear($('unit-trend-chart'));}
 dates.addEventListener('change',reset);
 for(const event of ['input','change'])filters.addEventListener(event,reset);
 filters.addEventListener('submit',event=>{event.preventDefault();run();});
 $('unit-queue-run').addEventListener('click',async()=>{if(!dates.reportValidity())return;const generation=++queueSerial,host=$('unit-queue-table'),out=$('unit-queue-feedback');host.replaceChildren();out.textContent=t('در حال دریافت…','Loading…');try{const result=await api('/api/organization/reports/queues?'+datesParams());if(generation!==queueSerial||section.hidden)return;const table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');[t('صف','Queue'),t('مراجعهٔ پایان‌یافته','Closed visits'),t('پاسخ‌داده','Answered'),t('رهاشده','Abandoned'),t('میانگین انتظار، ثانیه','Average wait, s'),t('سطح خدمت، درصد','Service level, percent')].forEach(x=>tr.append(cell('th',x)));head.append(tr);table.append(head);const body=document.createElement('tbody');for(const row of result.queues){const line=document.createElement('tr');[row.queue,number(row.visits),number(row.answered),number(row.abandoned),number(row.average_wait_seconds),number(row.sla_percent)].forEach(x=>line.append(cell('td',x)));body.append(line);}table.append(body);host.append(table);out.textContent=result.queues.length?'':t('مراجعهٔ مجازی در این بازه یافت نشد.','No authorized completed visits in this period.');}catch{if(generation===queueSerial)out.textContent=t('گزارش صف در دسترس نیست یا مجوز خلاصه داده نشده است.','Queue summary unavailable or not permitted.');}});
 async function queueVisits(more=false){if(!dates.reportValidity()||more&&!visitCursor)return;const generation=++visitSerial,p=datesParams(),host=$('unit-queue-visits-table'),out=$('unit-queue-visits-feedback'),next=$('unit-queue-visits-next');if(more)p.set('cursor',visitCursor);else{visitRows=[];visitCursor=null;host.replaceChildren();}next.disabled=true;out.textContent=t('در حال دریافت…','Loading…');try{const result=await api('/api/organization/reports/queues/visits?'+p);if(generation!==visitSerial||section.hidden)return;visitRows.push(...result.rows);visitCursor=result.next;next.hidden=!visitCursor;const table=document.createElement('table'),head=document.createElement('thead'),header=document.createElement('tr');[t('زمان ورود','Entry time'),t('صف','Queue'),t('تماس‌گیرنده','Caller'),t('نتیجه','Outcome'),t('انتظار، ثانیه','Wait, s'),t('مکالمه، ثانیه','Talk, s')].forEach(x=>header.append(cell('th',x)));head.append(header);table.append(head);const body=document.createElement('tbody'),labels={answered:t('پاسخ‌داده','Answered'),abandoned:t('رهاشده','Abandoned'),transferred:t('منتقل‌شده','Transferred'),unknown:t('نامعلوم','Unknown')};for(const row of visitRows){const tr=document.createElement('tr');[new Date(row.entered*1000).toLocaleString(locale,{timeZone:'Asia/Tehran'}),row.queue,row.caller,labels[row.outcome]||row.outcome,window.SaneQueueReportDuration(row.wait_seconds),window.SaneQueueReportDuration(row.talk_seconds)].forEach(x=>tr.append(cell('td',x)));body.append(tr);}table.append(body);host.replaceChildren(table);out.textContent=visitRows.length?'':t('مراجعه‌ای یافت نشد.','No visits found.');}catch{if(generation===visitSerial){visitCursor=null;next.hidden=true;out.textContent=t('ریز صف در دسترس نیست یا مجوز آن داده نشده است.','Queue details unavailable or not permitted.');}}finally{next.disabled=false;}}
 $('unit-queue-visits-run').addEventListener('click',()=>queueVisits());$('unit-queue-visits-next').addEventListener('click',()=>queueVisits(true));
 $('unit-queue-visits-export')?.addEventListener('click',async event=>{
  if(!dates.reportValidity())return;
  const button=event.currentTarget,out=$('unit-queue-visits-feedback'),generation=visitSerial;
  button.disabled=true;out.textContent=t('در حال آماده‌سازی فایل…','Preparing export…');
  try{
   const config=JSON.parse($('ops-config').textContent);
   const response=await fetch('/api/organization/reports/queues/visits.csv?'+datesParams(),{
    method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':config.csrf||''}});
   if(!response.ok||!response.headers.get('content-type')?.startsWith('text/csv'))throw Error('export');
   const blob=await response.blob();
   if(generation!==visitSerial||section.hidden)return;
   const url=URL.createObjectURL(blob),link=document.createElement('a');
   link.href=url;link.download='unit-queue-visits.csv';document.body.append(link);link.click();link.remove();
   setTimeout(()=>URL.revokeObjectURL(url),1000);
   out.textContent=t('فایل آماده شد.','File is ready.');
  }catch{
   if(generation===visitSerial)out.textContent=t('دریافت فایل ممکن نیست. مجوز ریز مراجعه و خروجی لازم است. برای بیش از ۵۰۰۰ ردیف، بازه را کوتاه کنید.','Export unavailable. Visit details and export grants are required. Shorten the period for more than 5,000 rows.');
  }finally{button.disabled=false;}
 });
 async function run(more=false){if(!dates.reportValidity()||!filters.reportValidity())return;const generation=++serial,p=params();
  if(more&&cursor)p.set('cursor',cursor);if(!more){rows=[];summary.replaceChildren();host.replaceChildren();$('unit-trend-table').replaceChildren();window.SaneQueueReportCharts?.clear($('unit-trend-chart'));$('unit-trend-feedback').textContent=t('در حال محاسبهٔ روند…','Loading trend…');}
  feedback.textContent=t('در حال دریافت گزارش…','Loading report…');nextButton.disabled=true;
  const requests=[api('/api/organization/reports/cdr?'+p)];if(!more){requests.push(api('/api/organization/reports/cdr/summary?'+params()));const tp=params();tp.set('bucket',$('unit-trend-bucket').value);tp.set('calendar',fa?'persian':'gregorian');requests.push(api('/api/organization/reports/cdr/trend?'+tp));}
  const result=await Promise.allSettled(requests);if(generation!==serial||section.hidden)return;
  let messages=[];const details=result[0];if(details.status==='fulfilled'){rows.push(...details.value.rows);cursor=details.value.next;showTable();nextButton.hidden=!cursor;if(!rows.length)messages.push(t('ردیفی در این بازه یافت نشد.','No rows in this period.'));}
  else{cursor=null;nextButton.hidden=true;messages.push(t('ریز تماس در دسترس نیست یا مجوز آن داده نشده است.','Call details are unavailable or not permitted.'));}
  if(!more){const stats=result[1];if(stats.status==='fulfilled'){const totals=stats.value.totals;
   [[t('کل بخش‌ها','Segments'),totals.segments_started],[t('پاسخ داده','Answered'),totals.answered_segments],[t('بی‌پاسخ','Unanswered'),totals.unanswered_segments],[t('میانگین مدت، ثانیه','Average duration, seconds'),totals.average_duration_seconds]].forEach(([label,value])=>{const el=document.createElement('article');el.className='history-kpi';el.append(cell('span',label),cell('strong',number(value)));summary.append(el);});}
   else messages.push(t('خلاصه در دسترس نیست یا مجوز آن داده نشده است.','Summary is unavailable or not permitted.'));
   const trend=result[2],chart=$('unit-trend-chart'),tableHost=$('unit-trend-table');window.SaneQueueReportCharts?.clear(chart);tableHost.replaceChildren();
   if(trend.status==='fulfilled'){const entries=trend.value.rows,keys=['inbound','outbound','internal','unknown'],labels=[t('ورودی','Inbound'),t('خروجی','Outbound'),t('داخلی','Internal'),t('نامعلوم','Unknown')];
    const display=value=>value.length===10?(window.SaneQueueReportPeriods?.display(value)||value):value;
    window.SaneQueueReportCharts?.render(chart,{type:'column',title:t('بخش‌های تماس در بازهٔ انتخابی','Call segments in selected period'),unit:t('بخش تماس','Segments'),labels:entries.map(r=>display(r.period)),series:keys.map((key,i)=>({label:labels[i],values:entries.map(r=>r[key])}))});
    const table=document.createElement('table'),head=document.createElement('tr');[t('بازه','Period'),...labels].forEach(x=>head.append(cell('th',x)));table.append(head);for(const row of entries){const line=document.createElement('tr');[display(row.period),...keys.map(k=>number(row[k]))].forEach(x=>line.append(cell('td',x)));table.append(line);}tableHost.append(table);$('unit-trend-feedback').textContent=entries.length?'':t('داده‌ای در این بازه نیست.','No data in this period.');
   }else $('unit-trend-feedback').textContent=t('روند در دسترس نیست؛ مجوز یا بازه را بررسی کنید.','Trend unavailable; check permission and period.');}
  feedback.textContent=messages.join(' ');nextButton.disabled=false;}
 $('unit-report-run').addEventListener('click',()=>run(false));nextButton.addEventListener('click',()=>run(true));
 $('unit-trend-bucket').addEventListener('change',()=>run(false));
 async function tokenRequest(url,body){let config={};try{config=JSON.parse($('ops-config').textContent);}catch{}const options=body?{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf||''},body:JSON.stringify(body)}:{};return api(url,options);}
 async function listTokens(){const host=$('unit-token-list');host.replaceChildren();try{const data=await tokenRequest('/api/organization/tokens');for(const token of data.tokens){const line=document.createElement('p'),button=cell('button',t('ابطال','Revoke'));button.type='button';line.append(cell('span',t('انقضا: ','Expires: ')+new Date(token.expires*1000).toLocaleDateString(locale,{timeZone:'Asia/Tehran'})+' '),button);button.onclick=async()=>{try{await tokenRequest('/api/organization/tokens/revoke',{id:token.id});$('unit-token-secret').textContent='';await listTokens();}catch{$('unit-token-secret').textContent=t('ابطال انجام نشد.','Revocation failed.');}};host.append(line);}if(!data.tokens.length)host.append(cell('p',t('کلید فعالی وجود ندارد.','No active keys.')));}catch{$('unit-token-secret').textContent=t('دسترسی به فهرست کلیدها نیازمند HTTPS و نشست معتبر است.','Listing keys requires HTTPS and an authenticated session.');}}
 $('unit-token-refresh').addEventListener('click',listTokens);
 $('unit-token-form').addEventListener('submit',async event=>{event.preventDefault();const form=event.currentTarget,output=$('unit-token-secret');output.textContent='';try{const data=await tokenRequest('/api/organization/tokens',{days:Number(form.elements.days.value)});output.textContent=t('کلید فقط همین بار نمایش داده می‌شود: ','Copy this key now; it is shown once: ')+data.token;await listTokens();}catch{output.textContent=t('ساخت کلید انجام نشد؛ HTTPS و مجوز API لازم است.','Key creation failed; HTTPS and API permission are required.');}});
 section.querySelectorAll('details').forEach(details=>details.addEventListener('toggle',()=>{if(!details.open&&details.contains($('unit-token-form')))$('unit-token-secret').textContent='';}));
 const hideToken=()=>{if(section.hidden||document.body.dataset.view!=='reports'){$('unit-token-secret').textContent='';queueSerial++;visitSerial++;visitCursor=null;visitRows=[];$('unit-queue-table').replaceChildren();$('unit-queue-feedback').textContent='';$('unit-queue-visits-table').replaceChildren();$('unit-queue-visits-feedback').textContent='';$('unit-queue-visits-next').hidden=true;}};
 new MutationObserver(hideToken).observe(section,{attributes:true,attributeFilter:['hidden']});
 new MutationObserver(hideToken).observe(document.body,{attributes:true,attributeFilter:['data-view']});
 $('unit-report-export').addEventListener('click',async event=>{if(!dates.reportValidity()||!filters.reportValidity())return;const button=event.currentTarget,generation=serial;let config={};try{config=JSON.parse($('ops-config').textContent);}catch{}
  if(!config.csrf){feedback.textContent=t('نشست معتبر لازم است.','A valid session is required.');return;}button.disabled=true;
  try{const format=$('unit-report-format').value;if(!['csv','xlsx','pdf'].includes(format))throw Error('export');
   const response=await fetch('/api/organization/reports/cdr/export.'+format+'?'+params(),{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':config.csrf}});
   const mime={csv:'text/csv',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',pdf:'application/pdf'}[format];
   if(!response.ok||!response.headers.get('content-type')?.includes(mime))throw Error('export');const blob=await response.blob();if(generation!==serial||section.hidden)return;
   const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='unit-cdr.'+format;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
   feedback.textContent=t('فایل آماده شد.','File is ready.');
  }catch{if(generation===serial)feedback.textContent=t('خروجی در دسترس نیست؛ مجوز ریز تماس و خروجی لازم است. سقف PDF، ۱۵۰ و سایر قالب‌ها ۵۰۰۰ ردیف است.','Export unavailable; details and export permissions are required. The limit is 150 PDF rows or 5,000 for other formats.');}finally{button.disabled=false;}
 });
 $('unit-ai-form').addEventListener('submit',async event=>{event.preventDefault();if(!dates.reportValidity())return;
  const f=event.currentTarget,button=f.querySelector('button'),out=$('unit-ai-feedback'),generation=serial;let config={};try{config=JSON.parse($('ops-config').textContent);}catch{}
  if(!config.csrf){out.textContent=t('نشست معتبر لازم است.','A valid session is required.');return;}
  button.disabled=true;out.textContent=t('در حال بررسی پرسش…','Analyzing question…');
  try{const result=await api('/api/organization/reports/ai?'+datesParams(),{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':config.csrf},body:JSON.stringify({question:f.elements.question.value})});
   if(generation!==serial||section.hidden)return;
   if(result.state!=='available'){out.textContent=result.message||t('این پرسش پشتیبانی نمی‌شود.','This question is not supported.');return;}
   const metrics={count:t('تعداد بخش‌های تماس','Call segments'),answered:t('بخش‌های پاسخ‌داده','Answered segments'),unanswered:t('بخش‌های بی‌پاسخ','Unanswered segments'),average_duration:t('میانگین مدت، ثانیه','Average duration, seconds'),average_talk:t('میانگین مکالمهٔ ثبت‌شده، ثانیه','Average known talk, seconds'),average_answered_talk:t('میانگین مکالمهٔ پاسخ‌داده، ثانیه','Average answered talk, seconds'),total_talk:t('مجموع مکالمهٔ ثبت‌شده، ثانیه','Total known talk, seconds'),answer_rate:t('نرخ پاسخِ وضعیت‌های معلوم، درصد','Answer rate of known outcomes, percent')};
   const dirs={all:t('همه جهت‌ها','All directions'),inbound:t('ورودی','Inbound'),outbound:t('خروجی','Outbound'),internal:t('داخلی','Internal'),unknown:t('نامعلوم','Unknown')};
   out.textContent=(metrics[result.metric]||result.metric)+' · '+(dirs[result.direction]||result.direction)+' : '+number(result.value)+(result.denominator!=null?t('؛ تعداد وضعیت معلوم: ','; known outcomes: ')+number(result.denominator):'')+(result.known_samples!=null?t('؛ نمونهٔ دارای مدت معلوم: ','; known-duration samples: ')+number(result.known_samples):'')+t('؛ فقط برای واحدهای مجاز و بازهٔ انتخاب‌شده.','; authorized units and selected period only.');
   if(result.comparison){const c=result.comparison,fmt=v=>new Date(v*1000).toLocaleDateString(locale,{timeZone:'Asia/Tehran'});
    out.textContent+=t(' دورهٔ قبل از ',' Previous period from ')+fmt(c.start)+t(' تا پیش از ',' until before ')+fmt(c.end)+' : '+number(c.value)+t('؛ اختلاف: ','; difference: ')+number(c.difference)+(result.metric==='answer_rate'?t(' واحد درصد',' percentage points'):'')+(c.denominator!=null?t('؛ وضعیت معلوم دورهٔ قبل: ','; previous known outcomes: ')+number(c.denominator):'')+(c.known_samples!=null?t('؛ نمونهٔ معلوم دورهٔ قبل: ','; previous known samples: ')+number(c.known_samples):'');}
  }catch{if(generation===serial)out.textContent=t('گزارش هوشمند در دسترس نیست؛ مجوز و تنظیم سرویس را بررسی کنید.','AI report unavailable; check permission and provider configuration.');}finally{button.disabled=false;}
 });
})();
