'use strict';
(() => {
 const cfg=JSON.parse(document.getElementById('ops-config').textContent), fa=document.documentElement.lang==='fa';
 const $=id=>document.getElementById(id), t=(a,b)=>fa?a:b, n=v=>Number.isFinite(Number(v))?Number(v):0;
 const fmt=v=>v==null?'—':new Intl.NumberFormat(fa?'fa-IR':'en-US',{maximumFractionDigits:1}).format(v);
 const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const duration=v=>{v=Math.max(0,Math.floor(n(v)));return [Math.floor(v/60),v%60].map(x=>String(x).padStart(2,'0')).join(':');};
 const queueMean=(q,key)=>q&&q[key]!==undefined&&q[key]!==null&&String(q[key]).trim()!==''&&n(q.Completed)>0?duration(q[key]):'—';
 const bool=v=>v===true||v===1||v==='1'||v==='true';
 const status=m=>bool(m.Paused)?'paused':(bool(m.InCall)||[2,3,6,7,8,10].includes(n(m.Status)))?'busy':n(m.Status)===1?'ready':'offline';
 const labels={ready:t('آماده دریافت تماس','Ready for calls'),busy:t('مشغول','Busy'),paused:t('توقف موقت','Paused'),offline:t('خارج از دسترس','Unavailable')};
 const memberDetail=m=>{if(bool(m.Paused))return {key:'paused',label:(m.PausedReason? t('توقف موقت: ','Paused: ')+m.PausedReason:t('توقف موقت','Paused'))};const code=n(m.Status);
  if(code===6||code===7)return {key:'ringing',label:t('در حال زنگ‌خوردن','Ringing')};
  if(code===8)return {key:'held',label:t('تماس روی انتظار','On hold')};
  if(bool(m.InCall)||code===10)return {key:'talking',label:t('در حال مکالمه','In conversation')};
  if(code===2||code===3)return {key:'busy',label:t('مشغول','Busy')};
  if(code===1)return {key:'ready',label:t('آماده پاسخ‌گویی','Ready')};
  return {key:'offline',label:t('خارج از دسترس','Unavailable')};};
 const stateChip=m=>{const d=memberDetail(m);return `<span class="sq-state sq-state--${d.key}"><i></i>${esc(d.label)}</span>`;};

 let samples=[], sampledSource='', currentDataSource='sample-data', livePolicyAlerts=[];
 let queues={}, lastSuccess=0, pending=false, timer, sound=false, audioContext=null, lastSound=0, minimumReady=0, minimumPercent=0;
 let journeyFeed={connected:false,records:[],complete_history:false};
 const supervisor=['admin','supervisor'].includes(cfg.role);
 let armedQueue='';
 const ownPhone=cfg.assigned_phone||'';
 let showFullNumbers=false;
 const masked=(value)=>{const str=String(value??'');return showFullNumbers||str.length<6?str:str.slice(0,3)+'•••'+str.slice(-3);};
 const trunkLabel=c=>String(c.SourceTrunk||'—');
 const storage={get(k){try{return localStorage.getItem('sanequeue.'+k);}catch{return null;}},set(k,v){try{localStorage.setItem('sanequeue.'+k,v);}catch{}}};
 document.body.classList.toggle('dark',storage.get('theme')!=='light');
 $('theme-toggle').onclick=()=>{document.body.classList.toggle('dark');storage.set('theme',document.body.classList.contains('dark')?'dark':'light');};
 $('language-toggle').onclick=()=>location.assign(cfg.language_url.replace('__LANG__',fa?'en':'fa'));
 $('wallboard').onclick=()=>{const button=document.querySelector('[data-view=wallboard]');if(button)button.click();$('wallboard-fullscreen').click();};
 document.addEventListener('keydown',e=>{if(e.key==='Escape')document.body.classList.remove('wallboard');});
 const saved=n(storage.get('threshold'));if(saved>=5&&saved<=3600)$('threshold').value=saved;
 $('threshold').onchange=()=>{const value=Math.min(3600,Math.max(5,n($('threshold').value)));$('threshold').value=value;storage.set('threshold',value);render();};
 const defaultPauseReasons=[
   {id:'break',label:t('استراحت','Break')},{id:'lunch',label:t('ناهار','Lunch')},
   {id:'training',label:t('آموزش','Training')},{id:'meeting',label:t('جلسه','Meeting')},
   {id:'after_call',label:t('کار پس از تماس','After-call work')},
   {id:'follow_up',label:t('پیگیری تلفنی مشتری','Customer follow-up')},
   {id:'manual_calls',label:t('تماس خروجی با فهرست مشتریان','Manual outbound calling')},
   {id:'technical',label:t('مشکل فنی','Technical issue')}
 ];
 let policyState=null,policyAvailable=[],baleConfigured=false;
 const defaultPolicy=()=>({label:'',alerts:{waiting_above:5,wait_seconds_above:300,min_ready:0,cooldown_seconds:300,bale_enabled:false},staffing:{roster_size:0,max_absent_percent:50,max_absent_count:5,min_on_duty:0},pause_reasons:defaultPauseReasons.map(x=>({...x}))});
 const names={shifts:t('برنامه شیفت','Shift planning'),directory:t('دفترچه تلفن','Directory'),live:t('داشبورد','Dashboard'),queues:t('صف‌ها','Queues'),calls:t('تماس‌های جاری','Active calls'),waiting:t('تماس‌های منتظر','Waiting calls'),agents:t('کارشناسان','Agents'),presence:t('داخلی‌ها و حضور','Extensions & presence'),control:t('کنترل تماس','Call controls'),pbx:t('سلامت PBX','PBX health'),features:t('امکانات و توسعه','Capabilities'),wallboard:t('دیوار نمایش','Wallboard'),alerts:t('هشدارها','Alerts'),audit:t('ثبت عملیات','Audit trail'),settings:t('اتصال AMI و تنظیمات','AMI & settings'),users:t('کاربران و دسترسی‌ها','Users & access'),policies:t('قوانین و هشدارهای صف','Queue policies & alerts')};
 const viewHeadings={shifts:[names.shifts,t("برنامه‌ریزی بدون تغییر خودکار وضعیت PBX","Planning without automatic PBX changes")],directory:[names.directory,t("مخاطبان مشترک در صف‌های مجاز","Shared contacts in authorized queues")],users:[t('مدیریت کاربران و دسترسی‌ها','Users and access'),t('تعریف حساب، داخلی و صف‌ها با مجوز مستقل در یک صفحه','Manage accounts, phones and queue grants together')],pbx:[t('سلامت مرکز تلفن','PBX health'),t('کانال‌ها، وضعیت PJSIP و تماس‌های پارک‌شده؛ فقط خواندنی','Channel legs, endpoint availability and parked calls; read-only')],features:[t('امکانات و مسیر توسعه','Capability map'),t('عملکردهای آماده، آزمایشی و برنامه‌ریزی‌شده به تفکیک','Built, beta and planned features clearly distinguished')],live:[t('نبض مرکز تماس شما','Your contact center, live'),t('وضعیت پاسخ‌گویی و سلامت صف‌ها را همین لحظه دنبال کنید.','Follow your live queues and availability.')],queues:[t('سلامت و ظرفیت صف‌ها','Queue health & capacity'),t('شناسایی سریع صف‌های در فشار، انتظار و ظرفیت پاسخ‌گویی.','Identify overloaded queues and staffing risks.')],calls:[t('مدیریت تماس‌های زنده','Live call management'),t('تماس‌های در جریان و منتظر با زمان‌سنج و کنترل سرپرست.','Active and waiting calls, timers and supervisor controls.')],agents:[t('وضعیت کارشناسان','Agent presence'),t('آمادگی، مشغولی، توقف و عضویت در صف را در یک نگاه ببینید.','Availability, pauses and queue membership.')],audit:[t('ردپای کنترل‌های سرپرستان','Supervisor activity audit'),t('ثبت اقدامات کنترلی موفق و ناموفق؛ نه گزارش عملکرد تماس.','Accepted and rejected control actions; not call reporting.')],settings:[t('اتصال AMI و آماده‌سازی تست','AMI connectivity & test staging'),t('ابتدا تست AMI، سپس خواندن داده زنده؛ خطا فیلدها را پاک نمی‌کند.','First probe AMI, then enable the live parser; errors do not clear the form.')],waiting:[t('تماس‌های منتظر','Waiting calls'),t('زمان انتظار، جایگاه و اولویت در صف‌های مجاز','Wait time, position, and priority in authorized queues')],presence:[t('حضور کارشناسان صف','Queue member presence'),t('وضعیت آنلاین و تماس‌های جاری اعضای صف، نه همه داخلی‌های سیستم','Queue member presence, not all PBX extensions')],control:[t('مرکز کنترل تماس آزمایشی','Test call controls'),t('فقط تماس و عضو آزمایشی مجاز؛ هر عملیات نیاز به تأیید دارد','Authorized test calls and members only, with confirmation')],wallboard:[t('دیوار نمایش مرکز تماس','Call center wallboard'),t('نمای خوانای صف‌های مجاز روی مانیتور بزرگ','Large-screen visibility for authorized queues')],alerts:[t('هشدارهای لحظه‌ای','Live alerts'),t('هشدارهای مبتنی بر آستانه، بدون گزارش‌گیری تاریخی','Threshold-based alerts, no historical reports')],policies:[t('قوانین صف و دسترسی','Queue policies & access'),t('هشدارهای صف، سقف خروج، علت‌های توقف و دسترسی سرپرستان','Queue alerts, departure limits, pause reasons, supervisor permissions')]};
 document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{
  document.querySelectorAll('[data-view]').forEach(b=>{b.classList.toggle('active',b===button);b.setAttribute('aria-current',b===button?'page':'false');});
  Object.keys(names).forEach(key=>{const pane=$(key+'-view');if(pane)pane.hidden=key!==button.dataset.view;});$('view-title').textContent=names[button.dataset.view];const heading=viewHeadings[button.dataset.view];document.querySelector('.page-heading h1').textContent=heading[0];document.querySelector('.page-heading .muted').textContent=heading[1];if(button.dataset.view==='audit')loadAudit();if(button.dataset.view==='users')loadUsers();if(button.dataset.view==='wallboard')renderWallboard(selected(),[]);if(button.dataset.view==='policies'||(button.dataset.view==='agents'&&!policyState))loadPolicyEditor();
 });
 const empty=(message,columns)=>`<tr><td colspan="${columns}" class="empty">${esc(message)}</td></tr>`;
 const metric=(label,value,detail,icon='↗',kind='')=>`<article class="metric ${kind}"><span class="icon" aria-hidden="true">${icon}</span><p>${esc(label)}</p><b>${esc(value)}</b><small>${esc(detail)}</small></article>`;
 function selected(){const filter=$('queue-filter').value,search=$('search').value.trim().toLocaleLowerCase();return Object.entries(queues).filter(([name,q])=>(!filter||name===filter)&&(!search||name.toLocaleLowerCase().includes(search)||Object.entries(q.members||{}).some(([key,m])=>(key+' '+(m.Name||'')).toLocaleLowerCase().includes(search))));}

 function updateSamples(source){
  const items=selected();let waiting=0,ready=0,busy=0,paused=0,offline=0;
  for(const [,q] of items){waiting+=n(q.Calls);for(const m of Object.values(q.members||{})){const state=status(m);if(state==='ready')ready++;else if(state==='busy')busy++;else if(state==='paused')paused++;else offline++;}}
  if(source!==sampledSource){samples=[];sampledSource=source;}
  const now=Date.now(); if(!samples.length||now-samples[samples.length-1].ts>1500)samples.push({ts:now,waiting,ready,busy,paused,offline});
  samples=samples.slice(-60); updateCharts({waiting,ready,busy,paused,offline});
 }
 function drawTrend(container,key,color){
  if(!container)return;
  const values=samples.map(d=>Math.max(0,n(d[key])));const max=Math.max(1,...values);const w=500,h=115;
  const points=values.map((v,i)=>`${(i/(Math.max(1,values.length-1))*w).toFixed(1)},${(h-12-v/max*96).toFixed(1)}`);
  const poly=points.join(' ');const lastDot=points.length?points[points.length-1].split(','):['0',String(h-12)];const fill=points.length>1?`0,${h} ${poly} ${w},${h}`:`0,${h} ${poly} 0,${h}`;
  container.innerHTML=`<svg viewBox="0 0 ${w} ${h}" preserveAspectRatio="none" role="img" aria-label="${t('نمودار مقادیر دیده‌شده','Observed values')} ${values.length}"><defs><linearGradient id="grad-${key}" x1="0" x2="0" y1="0" y2="1"><stop offset="0" stop-color="${color}" stop-opacity=".25"/><stop offset="1" stop-color="${color}" stop-opacity="0"/></linearGradient></defs><path d="M0 25H${w} M0 65H${w} M0 104H${w}" stroke="#54708c" stroke-dasharray="4 8" opacity=".25"/><polygon points="${fill}" fill="url(#grad-${key})"/><polyline fill="none" stroke="${color}" stroke-width="3.5" stroke-linecap="round" stroke-linejoin="round" points="${poly}"/><circle cx="${lastDot[0]}" cy="${lastDot[1]}" r="5.5" fill="${color}" stroke="#092238" stroke-width="2"/></svg>`;
 }
 function updateCharts(counts){
  drawTrend($('trend-wait'),'waiting','#f6a91c');drawTrend($('trend-ready'),'ready','#20d4a0');
  $('trend-points').textContent=fmt(samples.length)+' '+t('نمونه','samples');
  $('trend-time-label').textContent=samples.length?new Date(samples[0].ts).toLocaleTimeString(fa?'fa-IR':'en-GB',{hour:'2-digit',minute:'2-digit'}):'—';
  const total=counts.ready+counts.busy+counts.paused+counts.offline;const donut=$('capacity-donut');
  const names=[['ready','#21c99b'],['busy','#388efa'],['paused','#f3b12d'],['offline','#c83d64']];let angle=0;
  donut.style.background=total?`conic-gradient(${names.map(([name,color])=>{const end=angle+counts[name]/total*360;const part=`${color} ${angle}deg ${end}deg`;angle=end;return part;}).join(',')})`:'conic-gradient(#1d3a55 0deg 360deg)';
  $('capacity-donut-label').textContent=fmt(counts.ready)+'/'+fmt(total);
  $('capacity-counts').innerHTML=names.map(([key,color])=>`<div><i style="background:${color}"></i>${labels[key]}<b>${fmt(counts[key])}</b></div>`).join('');
 }


 function updateDetailViews(entries, agents, calls, alerts){
  const sum=(arr,key)=>arr.reduce((a,x)=>a+n(x[1][key]),0);
  const waiting=sum(entries,'Calls'), resolved=sum(entries,'Completed'), abandoned=sum(entries,'Abandoned');
  const counts={ready:0,busy:0,paused:0,offline:0};agents.forEach(a=>counts[a.state]++);
  const queuesWithWaiting=entries.filter(([,q])=>n(q.Calls)>0).length;
  const noReady=entries.filter(([,q])=>(Object.keys(q.members||{}).length>0||n(q.Calls)>0)&&Object.values(q.members||{}).filter(m=>status(m)==='ready').length===0).length;
  const waitMax=Math.max(0,...calls.map(({c})=>n(c.Wait)));
  const waitAbove=calls.filter(({c})=>n(c.Wait)>=n($('threshold').value)).length;
  const congested=entries.filter(([,q])=>n(q.Calls)>=n($('waiting-threshold').value)).length;
  const roleLabel=supervisor?t('سرپرست تست','Test supervisor'):t('مشاهده‌گر','Viewer');
  const sourceText=currentDataSource==='ami-live'?t('AMI • داده زنده','AMI • LIVE'):t('DEMO • داده ساختگی','DEMO • SAMPLE');
  document.querySelectorAll('[data-source-label]').forEach(node=>{node.textContent=sourceText;node.classList.toggle('is-live',currentDataSource==='ami-live');});
  const model={
   queues:[fmt(entries.length),fmt(waiting),fmt(counts.ready),fmt(noReady)],
   calls:[fmt(counts.busy),fmt(agents.filter(a=>[6,7].includes(n(a.m.Status))).length),fmt(agents.filter(a=>!!a.m.LiveDuration).length),fmt(counts.ready)],
   waiting:[fmt(calls.length),duration(waitMax),fmt(queuesWithWaiting),fmt(waitAbove)],
   agents:[fmt(counts.ready),fmt(counts.busy),fmt(counts.paused),fmt(counts.offline)],
   presence:[fmt(agents.length),fmt(counts.ready),fmt(counts.paused),fmt(counts.offline)],
   pbx:[sourceText,fmt(entries.length),lastSuccess?new Date(lastSuccess).toLocaleTimeString(fa?'fa-IR':'en-GB'):'—',lastSuccess?t('تازه','Fresh'):t('نامشخص','Unknown')],
   control:[($('test-scope-queue')?.value||'—'),Object.keys(queues[$('test-scope-queue')?.value]?.members||{})[0]||'—',cfg.test_controls_enabled?t('فعال موقت','Temporarily armed'):t('قفل','Locked'),t('۳۰ دقیقه حداکثر','Max 30 min')],
   wallboard:[fmt(entries.length),fmt(waiting),fmt(counts.ready),fmt(alerts.length)],
   alerts:[fmt(alerts.length),fmt(congested),fmt(waitAbove),fmt(noReady)],
   audit:[roleLabel,cfg.test_controls_enabled?t('فعال موقت','Armed'):t('قفل','Locked'),armedQueue||'—',lastSuccess?new Date(lastSuccess).toLocaleTimeString(fa?'fa-IR':'en-GB'):'—'],
   settings:[sourceText, lastSuccess?t('در حال دریافت','Polling'):t('نامشخص','Unknown'),esc($('ami-queue').value||'8001'), cfg.test_controls_enabled?t('آزمایشی فعال','Test armed'):t('قفل','Locked')],
   features:[fmt(capabilitiesCount()),'1','4','7']
  };
  for(const [key,items] of Object.entries(model))items.forEach((value,i)=>{const el=$(key+'-score-'+i);if(el)el.textContent=value;});
  // Relative bars: never claim to show historical queue volume or extrapolated demand.
  const maxWaiting=Math.max(1,...entries.map(([,q])=>n(q.Calls)));
  $('queue-comparison').innerHTML=entries.map(([name,q])=>{
    const ready=Object.values(q.members||{}).filter(m=>status(m)==='ready').length;
    const percentage=Math.max(0,Math.min(100,100*n(q.Calls)/maxWaiting));
    return `<div class="queue-lane"><div class="lane-head"><b>${esc(name)}</b><span>${fmt(q.Calls)} ${t('منتظر','waiting')} · ${fmt(ready)} ${t('آماده','ready')}</span></div><div class="lane-track"><i style="width:${percentage}%"></i></div></div>`;
  }).join('')||`<div class="empty">${t('صفی برای نمایش پیدا نشد.','No queues available.')}</div>`;
  const spotlight=$('waiting-spotlight');
  if(spotlight){const oldest=[...calls].sort((a,b)=>n(b.c.Wait)-n(a.c.Wait))[0];
   spotlight.innerHTML=oldest?`<div class="spotlight-mark">◷</div><div><span>${t('طولانی‌ترین انتظار فعلی','Longest currently waiting')}</span><strong>${duration(oldest.c.Wait)}</strong><small>${t('صف','Queue')}: ${esc(oldest.name)} · ${t('موقعیت','Position')}: ${fmt(oldest.c.Position)}</small></div><button type="button" data-open="queues">${t('بررسی صف','Inspect queue')} ↗</button>`:
   `<div class="spotlight-mark safe">✓</div><div><strong>${t('هیچ تماس منتظری ثبت نشده','No waiting callers')}</strong><small>${t('این نتیجه مربوط به آخرین پاسخ AMI است.','As of the latest AMI snapshot.')}</small></div>`;}
  $('agent-presence-tiles').innerHTML=agents.map(a=>`<article class="agent-tile ${a.state}"><div class="agent-tile-top"><span class="agent-avatar">${esc((a.m.Name||a.key).slice(0,1))}</span>${stateChip(a.m)}</div><strong>${esc(a.m.Name||a.key)}</strong><small><bdi dir="ltr">${esc(a.key)}</bdi></small><small>${t('صف','Queue')}: ${esc(a.name)}</small><div class="agent-tile-bottom"><span>${t('پاسخ‌داده','Answered')}: <b>${fmt(a.m.CallsTaken)}</b></span><button type="button" data-open="agents" data-scroll="agent-rows">${t('مشاهده عملیات','View actions')} ↗</button></div></article>`).join('')||`<div class="empty">${t('عضوی وجود ندارد.','No agents available.')}</div>`;
  $('presence-summary').innerHTML=`<span class="legend-pill"><i class="dot ready"></i>${labels.ready}: <b>${fmt(counts.ready)}</b></span><span class="legend-pill"><i class="dot busy"></i>${labels.busy}: <b>${fmt(counts.busy)}</b></span><span class="legend-pill"><i class="dot paused"></i>${labels.paused}: <b>${fmt(counts.paused)}</b></span><span class="legend-pill"><i class="dot offline"></i>${labels.offline}: <b>${fmt(counts.offline)}</b></span>`;
  $('control-safety-summary').innerHTML=`<span class="safety-indicator ${cfg.test_controls_enabled?'armed':'locked'}">${cfg.test_controls_enabled?t('⚠ کنترل آزمایشی فعال است','⚠ TEST ACTIONS ARMED'):t('✓ فرمان‌های واقعی قفل هستند','✓ LIVE ACTIONS LOCKED')}</span><span>${t('فقط صف مجاز انتخاب‌شده · انتخاب عضو یا تماس ضروری است','Selected authorized queue only · choose an active call or member')}</span><button type="button" data-open="settings">${t('مدیریت مجوز','Manage access')} ↗</button>`;
  $('wallboard-summary').innerHTML=`<div><strong>${fmt(waiting)}</strong><span>${t('در انتظار','Waiting')}</span></div><div><strong>${fmt(counts.ready)}</strong><span>${t('آماده','Ready')}</span></div><div><strong>${fmt(counts.busy)}</strong><span>${t('مشغول','Busy')}</span></div><div><strong>${fmt(alerts.length)}</strong><span>${t('هشدار','Alerts')}</span></div>`;
  $('alert-severity-strip').innerHTML=`<span>${t('ازدحام صف','Congestion')} <b>${fmt(congested)}</b></span><span>${t('انتظار طولانی','Long wait')} <b>${fmt(waitAbove)}</b></span><span>${t('ظرفیت صفر','No capacity')} <b>${fmt(noReady)}</b></span>`;
 }
 let wallboardVisible=null;
 function wallboardQueues(){try{const stored=JSON.parse(storage.get('wallboard-queues')||'null');return Array.isArray(stored)?stored.filter(x=>typeof x==='string'):null;}catch{return null;}}
 function renderWallboard(data,alerts){
  const available=data.map(([name])=>name);if(wallboardVisible===null)wallboardVisible=wallboardQueues();
  const enabled=wallboardVisible===null?available:wallboardVisible.filter(x=>available.includes(x));
  const chosen=data.filter(([name])=>enabled.includes(name));
  const picker=$('wallboard-queue-picker');if(!picker)return;
  picker.innerHTML=data.map(([name])=>`<label class="wallboard-check"><input type="checkbox" data-wb-queue="${esc(name)}" ${enabled.includes(name)?'checked':''}><span>${esc(policyState?.queues?.[name]?.label||name)}</span><small>${esc(name)}</small></label>`).join('');
  let waiting=0,ready=0,talking=0,ringing=0,paused=0,responded=0,abandoned=0;
  $('wallboard-queues').innerHTML=chosen.map(([name,q])=>{
   const members=Object.entries(q.members||{}),calls=Object.values(q.entries||{}).sort((a,b)=>n(b.Wait)-n(a.Wait));
   const c={ready:0,talking:0,ringing:0,paused:0,held:0,busy:0,offline:0};
   for(const [,m] of members)c[memberDetail(m).key]=(c[memberDetail(m).key]||0)+1;
   waiting+=n(q.Calls);ready+=c.ready;talking+=c.talking;ringing+=c.ringing;paused+=c.paused;responded+=n(q.Completed);abandoned+=n(q.Abandoned);
   const longest=calls.length?Math.max(...calls.map(x=>n(x.Wait))):0;
   const queueName=policyState?.queues?.[name]?.label||name;
   const sl=n(q.Completed)>0&&String(q.ServicelevelPerf??'').trim()!==''?fmt(q.ServicelevelPerf)+'%':'—';
   const agents=members.map(([key,m])=>`<div class="wb-agent"><span class="wb-agent-title">${esc(m.Name||key)}<small dir="ltr">${esc(key)}</small></span>${stateChip(m)}</div>`).join('')||`<p class="wb-empty">${t('بدون کارشناس','No agents')}</p>`;
   const callerRows=calls.slice(0,8).map(x=>`<div class="wb-caller"><b>${t('نفر','Position')} ${fmt(x.Position)}</b><span class="wb-wait">${duration(x.Wait)}</span><small>${n(x.Wait)>=n($('threshold').value)?t('انتظار طولانی','Long wait'):t('در انتظار','Waiting')}</small></div>`).join('')||`<p class="wb-empty">${t('تماس منتظر وجود ندارد','No callers waiting')}</p>`;
   return `<article class="wallboard-v14-card ${n(q.Calls)>0&&c.ready===0?'urgent':''}"><div class="wb-card-header"><div><small>${t('صف تماس','CALL QUEUE')} <bdi dir="ltr">${esc(name)}</bdi></small><h3>${esc(queueName)}</h3></div><span class="wb-queue-status">${n(q.Calls)>0&&c.ready===0?t('نیازمند توجه','Attention'):t('آنلاین','Live')}</span></div><div class="wb-hero-numbers"><div class="wb-big-wait"><strong>${fmt(q.Calls)}</strong><span>${t('تماس منتظر','Waiting now')}</span></div><div class="wb-big-waittime"><strong>${duration(longest)}</strong><span>${t('بیشترین انتظار فعلی','Longest live wait')}</span></div></div><div class="wb-queue-stats"><div><small>${t('پاسخ‌داده','Answered')}</small><b>${fmt(q.Completed)}</b></div><div><small>${t('رهاشده','Abandoned')}</small><b>${fmt(q.Abandoned)}</b></div><div><small>${t('آماده','Ready')}</small><b>${fmt(c.ready)} / ${fmt(members.length)}</b></div><div><small>${t('سطح خدمت','Service level')}</small><b>${sl}</b></div><div><small>${t('میانگین انتظار','Avg hold')}</small><b dir="ltr">${queueMean(q,'Holdtime')}</b></div><div><small>${t('میانگین مکالمه','Avg talk')}</small><b dir="ltr">${queueMean(q,'TalkTime')}</b></div></div><div class="wb-two-cols"><div><h4>${t('کارشناسان','Agents')} <em>${members.length}</em></h4><div class="wb-agents">${agents}</div></div><div><h4>${t('تماس‌های منتظر','Waiting room')} <em>${calls.length}</em></h4><div class="wb-callers">${callerRows}</div></div></div></article>`;
  }).join('')||`<div class="wb-empty-state">${t('برای وال‌برد یک یا چند صف را انتخاب کنید.','Select queues for this wallboard.')}</div>`;
  $('wallboard-summary').innerHTML=[
    [t('صف‌های انتخابی','Selected queues'),fmt(chosen.length)],
    [t('تماس منتظر','Waiting callers'),fmt(waiting)],
    [t('آماده','Ready agents'),fmt(ready)],
    [t('در حال مکالمه','Talking'),fmt(talking)],
    [t('در حال زنگ‌خوردن','Ringing'),fmt(ringing)],
    [t('توقف موقت','Paused'),fmt(paused)],
    [t('پاسخ‌داده','Answered'),fmt(responded)],
    [t('رهاشده','Abandoned'),fmt(abandoned)]
   ].map(([name,value])=>`<div><strong>${value}</strong><span>${name}</span></div>`).join('');
  $('wb-updated').textContent=lastSuccess?new Date(lastSuccess).toLocaleTimeString(fa?'fa-IR':'en-GB'):'—';
  $('wb-connection').textContent=currentDataSource==='ami-live'?t('داده زنده','Live AMI'):currentDataSource==='stale'?t('داده قدیمی؛ اتصال قطع','STALE / OFFLINE'):t('نمای آزمایشی','DEMO');
  $('wb-clock').textContent=new Date().toLocaleTimeString(fa?'fa-IR':'en-GB');
 }


 const journeyLabels={
  observed:t('شروع مشاهده','Observation started'),ingress:t('ورود از ترانک','Ingress from trunk'),in_queue:t('ورود به صف','Entered queue'),
  ringing_agent:t('در حال زنگ‌خوردن کارشناس','Agent ringing'),
  answered:t('پاسخ کارشناس','Agent answered'),left_queue:t('خروج از صف','Left queue'),
  abandoned:t('انصراف تماس‌گیرنده','Caller abandoned'),transferred:t('انتقال انجام شد؛ پاسخ مقصد نامشخص','Transferred; target not yet verified'),
  transfer_failed:t('انتقال ناموفق','Transfer failed'),post_transfer_ringing:t('در حال زنگ‌خوردن مقصد','Transfer destination ringing'),
  post_transfer_connected:t('کانال مقصد متصل؛ Bridge نامشخص','Destination channel up; bridge unverified'),
  post_transfer_talking:t('در حال مکالمه پس از انتقال','Talking after transfer'),
  possible_end:t('احتمال پایان تماس','Possible call end'),ending:t('بررسی پایان تماس','Checking final hangup'),
  ended:t('پایان تماس مشاهده‌شده','Observed call ended')
 };
 const isCompletedJourney=r=>r.status==='ended'||r.status==='abandoned'&&!!r.ended_at;
 function renderJourneyViews(){
  const raw=(journeyFeed&&Array.isArray(journeyFeed.records)?journeyFeed.records:[]);
  const scope=new Set(selected().map(x=>x[0]));
  const matching=raw.filter(r=>(r.queues||[]).some(q=>scope.has(q)));
  const active=matching.filter(r=>!isCompletedJourney(r));
  const clockTime=ts=>ts?new Date(ts*1000).toLocaleTimeString(fa?'fa-IR':'en-GB',{hour:'2-digit',minute:'2-digit',second:'2-digit'}):'—';
  const statusMsg=journeyFeed.connected?t('شنودگر رویدادها متصل','AMI event listener online'):t('شنودگر رویدادها قطع یا در حال اتصال؛ تاریخچه ممکن است ناقص باشد','Event listener offline/connecting; history may be incomplete');
  const privacyText=t('ترانک تأییدنشده','Unverified trunk');
  const ingress=r=>r.trunk_verified&&r.trunk?`<bdi dir="ltr">${esc(r.trunk)}</bdi>`:
    (r.ingress_hint?`<span title="${esc(privacyText)}">${t('منشأ احتمالی: ','Candidate: ')}<bdi dir="ltr">${esc(r.ingress_hint)}</bdi> (${esc(privacyText)})</span>`:t('نامشخص؛ نگاشت ترانک لازم است','Unknown; configure trunk mapping'));
  const one=(r,compact=false,publicScreen=false)=>{
   const state=journeyLabels[r.status]||journeyLabels.observed;
   const entries=publicScreen?[]:(r.timeline||[]).slice(-9);
   const number=publicScreen?'':(r.caller?`<span class="journey-caller" dir="ltr">${esc(r.caller)}</span>`:'');
   const info=[r.destination?`${t('مقصد','Destination')}: <bdi dir="ltr">${esc(r.destination)}</bdi>`:'',
    r.last_agent?`${t('کارشناس','Agent')}: ${esc(r.last_agent)}`:''].filter(Boolean).join(' · ');
   return `<article class="sq-journey-card ${isCompletedJourney(r)?'completed':'active'}"><header><span class="sq-journey-stage">${esc(state)}</span><small>${(r.queues||[]).map(esc).join('، ')} · ${clockTime(r.started_at)}</small></header><div class="sq-journey-ident"><span>${t('ترانک ورودی','Ingress trunk')}: ${ingress(r)}</span>${number}</div>${info?`<p class="sq-journey-secondary">${info}</p>`:''}${!compact&&!publicScreen?`<div class="sq-timeline">${entries.map(e=>`<div><i></i><time>${clockTime(e.time)}</time><span>${esc(journeyLabels[e.state]||e.state)}${e.detail?' · '+esc(e.detail==='unknown'?t('نامشخص','Unknown'):e.detail):''}</span></div>`).join('')}</div>`:''}${r.ended_at?`<small>${t('پایان','End')}: ${clockTime(r.ended_at)}</small>`:''}</article>`;
  };
  const emptyMessage=journeyFeed.connected?t('در این نشست هنوز تماس مرتبطی برای ردیابی ثبت نشده است. تماس‌های قبل از اتصال شنودگر بازیابی تاریخی ندارند.','No queue call observed in this listener session; older history is not reconstructed.'):t('شنودگر رویدادهای تماس فعال نیست. وضعیت اتصال AMI و مجوز read=call,agent را بررسی کنید.','Call event listener is offline; check AMI and read=call,agent permissions.');
  const renderList=(target,items,publicScreen=false,compact=false)=>{const node=$(target);if(!node)return;node.innerHTML=items.length?items.map(r=>one(r,compact,publicScreen)).join(''):`<p class="sq-journey-empty">${emptyMessage}</p>`;};
  renderList('queue-journey-cards',matching.slice(0,16));
  renderList('call-journey-cards',matching.slice(0,25));
  renderList('dashboard-journey-cards',active.filter(r=>r.transfers).slice(0,4),false,true);
  const wbSelection=wallboardVisible===null?scope:new Set(wallboardVisible);
  renderList('wb-journey-rows',active.filter(r=>(r.queues||[]).some(q=>wbSelection.has(q))).slice(0,8),true,true);
  ['queue-journey-status','call-journey-status','wb-journey-status'].forEach(id=>{if($(id)){$(id).textContent=statusMsg;$(id).classList.toggle('journey-offline',!journeyFeed.connected);}});
 }

 function capabilitiesCount(){return capabilities.length;}
 function render(){
  const data=selected(), threshold=n($('threshold').value);let answered=0,abandoned=0,waiting=0,ready=0,total=0,busy=0,holdSum=0,holdWeight=0,slSum=0,slWeight=0,cards=[],agents=[],calls=[],alerts=[];
  for(const [name,q] of data){
   answered+=n(q.Completed);abandoned+=n(q.Abandoned);waiting+=n(q.Calls);
   if(q.Holdtime!==undefined&&String(q.Holdtime).trim()!==''&&Number.isFinite(Number(q.Holdtime))&&n(q.Completed)>0){holdSum+=n(q.Holdtime)*n(q.Completed);holdWeight+=n(q.Completed);}
   if(q.ServicelevelPerf!==undefined&&Number.isFinite(Number(q.ServicelevelPerf))&&n(q.Completed)>0){slSum+=n(q.ServicelevelPerf)*n(q.Completed);slWeight+=n(q.Completed);}
   const counts={ready:0,busy:0,paused:0,offline:0};
   for(const [key,m] of Object.entries(q.members||{})){const state=status(m);counts[state]++;agents.push({name,key,m,state});if(state==='paused'&&n(m.LastPause)>0&&(Date.now()/1000-n(m.LastPause))>n($('pause-threshold').value)*60)alerts.push({title:t('استراحت طولانی','Long pause'),text:(m.Name||key)+' · '+name});}
   ready+=counts.ready;busy+=counts.busy;const count=Object.keys(q.members||{}).length;total+=count;
   const entries=Object.values(q.entries||{});let longest=0;
   for(const c of entries){longest=Math.max(longest,n(c.Wait));calls.push({name,c});}
   if(!(policyState?.queues?.[name]&&currentDataSource==='ami-live')&&n(q.Calls)>=n($('waiting-threshold').value))alerts.push({title:t('تراکم تماس در صف','Queue congestion'),text:name+' · '+fmt(q.Calls)+' '+t('تماس منتظر','waiting calls')});
   if(!(policyState?.queues?.[name]&&currentDataSource==='ami-live')&&longest>=threshold)alerts.push({title:t('انتظار بیش از حد','Long wait'),text:`${name} · ${duration(longest)} ${t('دقیقه:ثانیه','min:sec')}`});
   if(!(policyState?.queues?.[name]&&currentDataSource==='ami-live')&&counts.ready===0&&(count>0||n(q.Calls)>0))alerts.push({title:t('کارشناس آماده ندارد','No ready agents'),text:name+(n(q.Calls)>0?` · ${fmt(q.Calls)} ${t('تماس منتظر','waiting calls')}`:'')});
   const pct=count?Math.round(100*counts.ready/count):null;
   const percentValue=pct===null?'—':fmt(pct)+'%';
   const queueColor=(cards.length%4);
   const capacityBar=count?Object.entries(counts).map(([state,v])=>`<span class="${state}" style="height:${v?(25+75*v/count).toFixed(0):2}%" title="${esc(labels[state])}: ${v}"></span>`).join(''):'<span class="empty-capacity"></span>';
   cards.push(`<article class="queue-card ref-queue-row queue-color-${queueColor}"><div class="ref-queue-identity"><button type="button" class="queue-focus-link" data-focus="${esc(name)}"><b>${esc(name)}</b><small>${esc(q.Strategy||'—')}</small></button><span class="queue-wait-badge">${fmt(q.Calls)} <small>${t('منتظر','waiting')}</small></span></div><button type="button" class="queue-summary-open" data-queue-summary="${esc(name)}" title="${t('خلاصه وضعیت صف','Queue summary')}">▦ ${t('خلاصه صف','Overview')}</button><div class="queue-readiness-ring" style="--ring-pct:${pct===null?0:pct}%;--ring-color:${count?'#19c99b':'#5c7286'}" aria-label="${esc(t('آمادگی','Readiness'))}: ${percentValue}"><b>${percentValue}</b></div><div class="queue-operational-metrics"><span><b>${fmt(counts.ready)}/${fmt(count)}</b><small>${t('آماده','Ready')}</small></span><span><b>${fmt(q.Calls)}</b><small>${t('انتظار','Waiting')}</small></span></div><div class="capacity-mini" role="img" aria-label="${esc(Object.entries(counts).map(([st,num])=>labels[st]+': '+num).join(', '))}">${capacityBar}</div><div class="queue-mini-summary"><span>${t('پاسخ','Answered')} <b>${fmt(q.Completed)}</b></span><span>${t('رهاشده','Abandoned')} <b>${fmt(q.Abandoned)}</b></span><span>${t('میانگین انتظار','Avg wait')} <b dir="ltr">${queueMean(q,'Holdtime')}</b></span><span>${t('میانگین مکالمه','Avg talk')} <b dir="ltr">${queueMean(q,'TalkTime')}</b></span><span>${t('سطح خدمت','SL')} <b>${n(q.Completed)>0&&String(q.ServicelevelPerf??'').trim()!==''?fmt(q.ServicelevelPerf)+'%':'—'}</b></span></div></article>`);
  }
  const avgHold=holdWeight?duration(holdSum/holdWeight):'—';
  const serviceLevel=slWeight?fmt(slSum/slWeight)+'%':'—';
  $('metrics').innerHTML=
    metric(t('تماس‌های جاری','Active calls'),fmt(busy),t('عضویت‌های مشغول در صف','Busy queue memberships'),'◉','active')+
    metric(t('تماس‌های منتظر','Waiting calls'),fmt(waiting),t('هم‌اکنون در صف','Currently in queue'),'◷','warning')+
    metric(t('کارشناسان آماده','Ready agents'),fmt(ready)+' / '+fmt(total),t('اعضای آماده / کل عضویت‌ها','Ready / all memberships'),'♙','ready')+
    metric(t('تماس‌های رهاشده','Abandoned calls'),fmt(abandoned),t('از آخرین بازنشانی صف','Since queue reset'),'↯','danger')+
    metric(t('میانگین انتظار ثبت‌شده','Queue average hold'),avgHold,t('تخمین Asterisk از آخرین بازنشانی','Asterisk average since queue reset'),'◴','wait')+
    metric(t('سطح خدمت (SL)','Service level'),serviceLevel,t('بر اساس شاخص ارسالی Asterisk','From Asterisk queue counters'),'◎','sla');

  $('queue-count').textContent=fmt(data.length)+' '+t('صف','queues');$('queue-cards').innerHTML=cards.join('')||`<div class="empty">${t('صفی با این فیلتر پیدا نشد.','No matching queues.')}</div>`;
  if(alerts.length&&sound&&Date.now()-lastSound>60000&&audioContext){const oscillator=audioContext.createOscillator(),gain=audioContext.createGain();oscillator.connect(gain);gain.connect(audioContext.destination);gain.gain.value=.08;oscillator.frequency.value=650;oscillator.start();oscillator.stop(audioContext.currentTime+.18);lastSound=Date.now();}
  for(const a of livePolicyAlerts){if(data.some(([name])=>name===a.queue))alerts.push({title:a.type==='waiting_count'?t('تعداد منتظر از آستانه گذشت','Queue backlog threshold'):a.type==='waiting_time'?t('مدت انتظار از آستانه گذشت','Wait-time threshold'):t('کمبود کارشناس آماده','Low ready staff'),text:a.label+' · '+a.value+' / '+a.threshold});}
  $('alerts').innerHTML=alerts.length?alerts.map(a=>`<div class="alert-row"><b>${esc(a.title)}</b><p>${esc(a.text)}</p></div>`).join(''):`<div class="empty"><strong>✓</strong>${t('هشداری برای صف‌های انتخابی وجود ندارد.','No alerts for the selected queues.')}</div>`;
  $('agent-count').textContent=fmt(total);$('waiting-count').textContent=fmt(calls.length)+' '+t('تماس','calls');
  $('waiting-nav-count').textContent=fmt(calls.length);
  $('alerts-nav-count').textContent=fmt(alerts.length);
  $('alerts-page-count').textContent=fmt(alerts.length);
  $('alerts-full').innerHTML=alerts.length?alerts.map(a=>`<div class="alert-row"><b>⚠ ${esc(a.title)}</b><p>${esc(a.text)}</p></div>`).join(''):`<div class="empty">✓ ${t('هیچ هشدار فعالی وجود ندارد.','No active alerts.')}</div>`;
  $('overview-agent-totals').innerHTML=`<span><i class="dot ready"></i>${t('آماده','Ready')} <b>${fmt(ready)}</b></span><span><i class="dot busy"></i>${t('مشغول','Busy')} <b>${fmt(busy)}</b></span><span>${t('کل اعضا','Members')} <b>${fmt(total)}</b></span>`;
  $('overview-agent-list').innerHTML=agents.slice(0,7).map(({name,key,m,state})=>`<div class="dashboard-agent"><span class="agent-avatar">${esc((m.Name||key).slice(0,1))}</span><div><strong>${esc(m.Name||key)}</strong><small><bdi dir="ltr">${esc(key)}</bdi> · ${esc(name)}</small></div>${stateChip(m)}</div>`).join('')||`<div class="empty">${t('هنوز عضوی پیدا نشد.','No queue members found.')}</div>`;
  const activeOnDashboard=agents.filter(a=>a.state==='busy');
  $('dashboard-active-count').textContent=fmt(activeOnDashboard.length)+' '+t('عضویت','memberships');
  $('dashboard-active-rows').innerHTML=activeOnDashboard.slice(0,8).map(a=>`<tr><td><b>${esc(a.m.Name||a.key)}</b></td><td><bdi dir="ltr">${esc(a.name)}</bdi></td><td><span class="status"><i class="dot busy"></i>${esc(memberDetail(a.m).label)}</span></td><td class="ltr timer">${esc(a.m.LiveDuration||'—')}</td></tr>`).join('')||empty(t('در این لحظه عضویت مشغولی گزارش نشده است.','No busy members reported.'),4);
  $('presence-cards').innerHTML=agents.map(({name,key,m,state})=>`<article class="presence-card"><div class="agent-avatar">${esc((m.Name||key).slice(0,1))}</div><div><h3>${esc(m.Name||key)}</h3><p>${esc(name)} · <bdi dir="ltr">${esc(key)}</bdi></p>${stateChip(m)}</div></article>`).join('')||`<div class="empty">${t('عضوی وجود ندارد.','No members available.')}</div>`;
  renderWallboard(data,alerts);
  calls.sort((a,b)=>n(b.c.Wait)-n(a.c.Wait));
  $('call-rows').innerHTML=calls.map(({name,c})=>`<tr><td><bdi>${esc(c.CallerIDName||masked(c.CallerIDNum)||'—')}</bdi>${c.CallerIDName?`<small> · <bdi>${esc(masked(c.CallerIDNum))}</bdi></small>`:''}</td><td>${esc(name)}</td><td><bdi dir="ltr">${esc(trunkLabel(c))}</bdi></td><td>${fmt(c.Position)}</td><td><span class="timer ltr ${n(c.Wait)>=threshold?'overdue':''}">${duration(c.Wait)}</span></td><td>${fmt(c.Priority)}${supervisor?`<div class="row-actions"><button data-action="first" data-queue="${esc(name)}" data-channel="${esc(c.Channel)}">${t('ابتدای صف','Move to front')}</button><button data-action="priority" data-queue="${esc(name)}" data-channel="${esc(c.Channel)}">${t('اولویت','Priority')}</button><button data-action="hangup" data-queue="${esc(name)}" data-channel="${esc(c.Channel)}">${t('قطع','Hang up')}</button></div>`:''}</td></tr>`).join('')||empty(t('در حال حاضر تماسی در انتظار نیست.','No calls waiting right now.'),6);
  const stateFilter=$('status-filter').value,search=$('search').value.trim().toLocaleLowerCase();
  const shown=agents.filter(a=>(!stateFilter||a.state===stateFilter)&&(!search||(a.name+' '+a.key+' '+(a.m.Name||'')).toLocaleLowerCase().includes(search)));
  // Removed survey-only feature. Ordinary, user-defined Pause reasons remain.

  $('agent-rows').innerHTML=shown.map(({name,key,m,state})=>`<tr class="agent-table-row"><td><div class="agent-name-cell"><span class="agent-avatar">${esc((m.Name||key).slice(0,1))}</span><div><b>${esc(m.Name||key)}</b><small class="ltr">${esc(key)}</small></div></div></td><td><span class="queue-name-chip">${esc(name)}</span></td><td><span class="status"><i class="dot ${state}"></i>${esc(state==='busy'?(bool(m.InCall)?t('در مکالمه','In call'):[6,7].includes(n(m.Status))?t('زنگ می‌خورد','Ringing'):labels[state]):labels[state])}</span>${state==='paused'&&m.PausedReason?`<small class="pause-reason-display">${esc((policyState?.queues?.[name]?.pause_reasons||defaultPauseReasons).find(r=>r.id===m.PausedReason)?.label||m.PausedReason)}</small>`:''}</td><td>${fmt(m.CallsTaken)}</td><td>${m.LiveDuration?`<span class="ltr timer">${esc(m.LiveDuration)}</span><small class="ltr"> ${esc(masked(m.LiveCaller||''))}</small>`:esc(m.LastCallAgo||'—')}</td><td class="agent-actions-cell">${(supervisor||(cfg.role==='agent'&&cfg.own_interfaces.includes(m.Location||key)))?`<div class="agent-actions-shell"><button class="pause-agent agent-primary-action" data-queue="${esc(name)}" data-agent="${esc(m.Location||key)}" data-paused="${state==='paused'?'false':'true'}"><span aria-hidden="true">${state==='paused'?'▶':'Ⅱ'}</span>${state==='paused'?t('ادامه کار','Resume'):t('توقف','Pause')}</button>${supervisor?`<div class="agent-action-grid">${['spy','whisper','barge','penalty','remove'].map(action=>`<button type="button" data-action="${action}" data-queue="${esc(name)}" data-agent="${esc(m.Location||key)}" class="agent-operation agent-operation--${action}" title="${esc(actionNames[action])}">${esc(actionNames[action])}</button>`).join('')}</div>`:''}</div>`:'—'}</td></tr>`).join('')||empty(t('کارشناسی با این فیلتر پیدا نشد.','No matching agents.'),6);

  renderQueueFocus(data,threshold);
  renderCallRoom(calls,agents,threshold);
  updateDetailViews(data, agents, calls, alerts);
  renderJourneyViews();
 }
 function renderQueueFocus(data,threshold){
  const cards=data.map(([name,q])=>{
   const members=Object.entries(q.members||{}),entries=Object.values(q.entries||{});
   const counts={ready:0,busy:0,paused:0,offline:0};members.forEach(([,m])=>counts[status(m)]++);
   const longest=Math.max(0,...entries.map(c=>n(c.Wait)));
   const health=(n(q.Calls)>0&&counts.ready===0)?'critical':(longest>=threshold||n(q.Calls)>=n($('waiting-threshold').value))?'warning':'healthy';
   const text=health==='critical'?t('نیازمند مداخله','Immediate attention'):health==='warning'?t('تحت فشار','Under pressure'):t('پایدار','Healthy');
   const healthNote=health==='critical'?t('تماس منتظر بدون کارشناس آماده','Waiting callers without ready agents'):health==='warning'?t('تأخیر یا ازدحام نزدیک آستانه','Wait or capacity alert'):t('ظرفیت پاسخ‌گویی در محدوده عادی','No live threshold breach');
   return `<article class="queue-focus-card ${health}"><div class="focus-top"><div><p class="focus-overline">${t('صف تماس','CALL QUEUE')}</p><h3>${esc(policyState?.queues?.[name]?.label||name)} <small dir="ltr">${esc(name)}</small></h3><span class="focus-strategy">${esc(q.Strategy||'—')}</span></div><span class="health-pill ${health}">${esc(text)}</span></div><div class="focus-meter"><span>${t('ظرفیت نیروها','Agent capacity')}</span><b>${fmt(counts.ready)} / ${fmt(members.length)}</b></div><div class="capacity" role="img" aria-label="${esc(Object.entries(counts).map(([key,val])=>labels[key]+': '+val).join(', '))}">${Object.entries(counts).map(([key,val])=>`<span class="${key}" style="width:${members.length?100*val/members.length:0}%"></span>`).join('')}</div><div class="focus-stat-grid"><div><small>${t('منتظر','Waiting')}</small><strong>${fmt(q.Calls)}</strong></div><div><small>${t('طولانی‌ترین انتظار','Longest wait')}</small><strong class="${longest>=threshold?'overdue':''}">${duration(longest)}</strong></div><div><small>${t('آماده','Ready')}</small><strong>${fmt(counts.ready)}</strong></div><div><small>${t('مشغول','Busy')}</small><strong>${fmt(counts.busy)}</strong></div></div><div class="queue-focus-performance"><div><small>${t('پاسخ‌داده','Answered')}</small><b>${fmt(q.Completed)}</b></div><div><small>${t('رهاشده','Abandoned')}</small><b>${fmt(q.Abandoned)}</b></div><div><small>${t('میانگین انتظار','Average wait')}</small><b dir="ltr">${queueMean(q,'Holdtime')}</b></div><div><small>${t('میانگین مکالمه','Talk time')}</small><b dir="ltr">${queueMean(q,'TalkTime')}</b></div><div><small>${t('سطح خدمت','Service level')}</small><b>${n(q.Completed)>0&&String(q.ServicelevelPerf??'').trim()!==''?fmt(q.ServicelevelPerf)+'%':'—'}</b></div></div><div class="queue-focus-roster"><strong>${t('اعضای این صف','Queue members')}</strong>${members.length?members.map(([key,m])=>`<div class="queue-member-line"><span class="member-name">${esc(m.Name||key)}</span>${stateChip(m)}</div>`).join(''):`<span class="muted">${t('بدون عضو','No members')}</span>`}</div><div class="focus-bottom"><small>${esc(healthNote)}</small><button type="button" data-focus="${esc(name)}">${t('نمایش جزئیات','Inspect queue')} ←</button></div></article>`;
  });
  $('queue-focus-cards').innerHTML=cards.join('')||`<div class="empty">${t('صفی یافت نشد.','No matching queues found.')}</div>`;
 }
 function renderCallRoom(calls,agents,threshold){
  const active=agents.filter(a=>a.state==='busy');$('active-count').textContent=fmt(active.length)+' '+t('عضویت مشغول','busy memberships');$('calls-count').textContent=fmt(active.length+calls.length);
  $('active-call-rows').innerHTML=active.map(({name,key,m})=>{const target=m.Location||key, live=Boolean(m.LiveDuration),state=memberDetail(m).label;return `<tr><td><b>${esc(m.Name||key)}</b><small class="ltr"> · ${esc(key)}</small></td><td>${esc(name)}</td><td>${stateChip(m)}</td><td><bdi dir="ltr">${esc(masked(m.LiveCaller||'—'))}</bdi></td><td><span class="timer ltr">${live?esc(m.LiveDuration):'—'}</span></td><td>${supervisor?`<div class="row-actions">${['spy','whisper','barge'].map(action=>`<button data-action="${action}" data-queue="${esc(name)}" data-agent="${esc(target)}">${esc(actionNames[action])}</button>`).join('')}</div>`:t('فقط مشاهده','View only')}</td></tr>`;}).join('')||empty(t('هیچ کارشناس مشغولی در صف‌های انتخابی نیست.','No busy queue members in scope.'),6);
  $('waiting-room-count').textContent=fmt(calls.length)+' '+t('تماس','calls');
  $('waiting-room-rows').innerHTML=calls.map(({name,c})=>`<tr><td><bdi dir="ltr">${esc(masked(c.CallerIDNum||c.CallerIDName||'—'))}</bdi></td><td>${esc(name)}</td><td><bdi dir="ltr">${esc(trunkLabel(c))}</bdi></td><td>${fmt(c.Position)}</td><td><span class="timer ltr ${n(c.Wait)>=threshold?'overdue':''}">${duration(c.Wait)}</span></td><td>${supervisor?`<div class="row-actions"><button data-action="first" data-queue="${esc(name)}" data-channel="${esc(c.Channel)}">${t('ابتدای صف','Move to front')}</button><button data-action="priority" data-queue="${esc(name)}" data-channel="${esc(c.Channel)}">${t('اولویت','Priority')}</button><button data-action="hangup" data-queue="${esc(name)}" data-channel="${esc(c.Channel)}">${t('قطع','Hang up')}</button></div>`:t('فقط مشاهده','View only')}</td></tr>`).join('')||empty(t('تماسی در انتظار نیست.','No waiting callers.'),6);
  $('waiting-page-count').textContent=fmt(calls.length)+' '+t('تماس','calls');
  $('waiting-only-rows').innerHTML=$('waiting-room-rows').innerHTML;
 }
 async function fetchJSON(url,options){const controller=new AbortController(),timeout=setTimeout(()=>controller.abort(),url.includes('/api/ami/')?30000:15000);let response;try{response=await fetch(url,{credentials:'same-origin',signal:controller.signal,...options});}finally{clearTimeout(timeout);}if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw new Error('login_required');const body=await response.json();if(!response.ok)throw new Error(body.error||'request_failed');return body;}
 async function refresh(){
  if(pending)return;pending=true;clearTimeout(timer);$('refresh').disabled=true;
  try{const result=await fetchJSON(cfg.data_url);queues=result.queues||{};currentDataSource=result.data_source||'sample-data';showFullNumbers=Boolean(result.caller_numbers_visible);document.body.dataset.connection='fresh';minimumReady=result.minimum_ready;minimumPercent=result.minimum_ready_percent;cfg.test_controls_enabled=Boolean(result.controls_enabled);updateControlBadge();$('staffing-info').textContent=t('حداقل آمادگی: ','Minimum staffing: ')+fmt(minimumReady)+' / '+fmt(minimumPercent)+'%';const current=$('queue-filter').value;const keys=Object.keys(queues).sort();$('queue-filter').innerHTML=`<option value="">${t('همه صف‌ها','All queues')}</option>`+keys.map(key=>`<option value="${esc(key)}">${esc(key)}</option>`).join('');if(keys.includes(current))$('queue-filter').value=current;
   const scopeSelect=$('test-scope-queue');if(scopeSelect){
     const prev=scopeSelect.value;
     scopeSelect.innerHTML=`<option value="">${t('انتخاب صف','Choose queue')}</option>`+keys.map(key=>`<option value="${esc(key)}">${esc(key)}</option>`).join('');
     if(keys.includes(prev))scopeSelect.value=prev;else if(armedQueue&&keys.includes(armedQueue))scopeSelect.value=armedQueue;else if(keys.length===1)scopeSelect.value=keys[0];
     const chosen=scopeSelect.value||'—';$('test-confirm-target').textContent='ENABLE '+chosen;
     if($('test-scope-label'))$('test-scope-label').textContent=chosen;
     if($('test-agent-label'))$('test-agent-label').textContent=Object.keys(queues[chosen]?.members||{})[0]||'—';
   }
   updateAmiQueueSelect();
   journeyFeed=result.call_journeys||{connected:false,records:[],complete_history:false};
   livePolicyAlerts=Array.isArray(result.policy_alerts)?result.policy_alerts:[];lastSuccess=(result.data_source==='ami-live'&&Number.isFinite(Number(result.observed_at))&&Number(result.observed_at)>0)?Math.round(Number(result.observed_at)*1000):Date.now();$('connection').className='badge';$('connection').textContent=result.data_source==='ami-live'?t('AMI زنده','Live AMI'):(cfg.demo_mode?t('پیش‌نمایش آفلاین · داده ساختگی','Offline demo · sample data'):t('متصل به مرکز تلفن','PBX connected'));$('error').hidden=true;$('updated').textContent=new Date(lastSuccess).toLocaleTimeString(fa?'fa-IR':'en-GB');updateSamples(currentDataSource);render();
  }catch(error){journeyFeed={...journeyFeed,connected:false};renderJourneyViews();currentDataSource='stale';cfg.test_controls_enabled=false;document.body.dataset.connection='stale';updateControlBadge();$('connection').className='badge offline';$('connection').textContent=t('ارتباط قطع است','Connection lost');$('error').hidden=false;$('error').textContent=error.message==='login_required'?t('نشست منقضی شده؛ دوباره وارد شوید.','Session expired. Sign in again.'):t('داده زنده در دسترس نیست؛ آخرین داده قابل اعتماد قدیمی است. تونل، مجوزها و مرحله Parser را بررسی کنید.','Live data unavailable; last known values are stale. Check tunnel, permissions and parser.');}
  finally{pending=false;$('refresh').disabled=false;timer=setTimeout(refresh,document.hidden?Math.max(cfg.interval,15000):cfg.interval);}
 }
 $('refresh').onclick=refresh;$('search').oninput=render;$('status-filter').onchange=render;
 $('queue-filter').onchange=()=>{updateSamples(currentDataSource+'|'+$('queue-filter').value);render();};
 document.addEventListener('visibilitychange',()=>{if(!document.hidden)refresh();});
 
 async function chooseAgentPauseReason(options){
  const modal=$('pause-reason-dialog'),select=$('pause-reason-select'),hint=$('pause-reason-description');
  const choices=options||[];
  select.innerHTML=choices.filter(o=>o.id!=='survey').map(o=>`<option value="${esc(o.id)}">${esc(o.label)}</option>`).join('');
  const describe=()=>{hint.textContent=t('این علت برای وضعیت همین عضویت صف ثبت می‌شود.','Reason is recorded for this queue membership.');};
  select.onchange=describe; describe();modal.showModal();
  return await new Promise(resolve=>{
    let settled=false;
    const done=value=>{if(settled)return;settled=true;modal.close();resolve(value);};
    $('pause-reason-form').onsubmit=e=>{e.preventDefault();done(select.value);};
    $('pause-reason-cancel').onclick=()=>done(null);
    modal.oncancel=e=>{e.preventDefault();done(null);};
  });
 }
 $('agent-rows').onclick=async event=>{
  const button=event.target.closest('.pause-agent');if(!button)return;
  if(currentDataSource!=='ami-live'||!cfg.test_controls_enabled){alert(t('ابتدا داده زنده AMI را متصل و کنترل‌های آزمایشی را فعال کن.','Connect live AMI and arm test controls first.'));return;}
  const pause=button.dataset.paused==='true';
  let reason='';
  if(pause){const options=policyState?.queues?.[button.dataset.queue]?.pause_reasons||defaultPauseReasons;
    reason=await chooseAgentPauseReason(options);
    if(reason===null)return;
  }else if(!confirm(t('کارشناس به دریافت تماس ورودی صف برگردد؟','Resume inbound queue calls for this agent?')))return;
  button.disabled=true;
  try{
    await fetchJSON(cfg.pause_url,{method:'POST',headers:{'X-CSRF-Token':cfg.csrf,'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({queue:button.dataset.queue,agent:button.dataset.agent,paused:button.dataset.paused,reason})});
    await refresh();
  }catch(error){alert(['minimum_ready','queue_exit_limit_reached','configure_roster_size_before_leaving'].includes(error.message)?t('سقف خروج یا حداقل نیروی فعال صف اجازه این عملیات را نمی‌دهد.','Staffing floor prevents this departure.'):t('Asterisk عملیات را تأیید نکرد؛ دسترسی AMI و وضعیت صف را بررسی کن.','AMI did not confirm operation; check permissions and queue status.'));}
  finally{button.disabled=false;}
 };
 const actionNames={first:t('انتقال به ابتدای صف','Move caller to front'),priority:t('تغییر اولویت تماس','Change caller priority'),hangup:t('قطع تماس','Hang up call'),spy:t('شنود','Listen'),whisper:t('نجوا','Whisper'),barge:t('ورود به مکالمه','Barge'),penalty:t('وزن توزیع','Agent penalty'),remove:t('حذف از صف','Remove from queue'),add:t('افزودن کارشناس','Add agent')};
 let actionTarget=null;
 $('sound-toggle').onclick=()=>{sound=!sound;if(sound){audioContext=audioContext||new (window.AudioContext||window.webkitAudioContext)();audioContext.resume();}$('sound-toggle').setAttribute('aria-pressed',String(sound));$('sound-toggle').textContent=sound?t('هشدار صوتی: روشن','Sound alerts: on'):t('هشدار صوتی: خاموش','Sound alerts: off');};
 ['waiting-threshold','pause-threshold'].forEach(id=>{const value=n(storage.get(id));if(value>0)$(id).value=value;$(id).onchange=()=>{$(id).value=Math.max(1,Math.min(n($(id).max),n($(id).value)));storage.set(id,$(id).value);render();};});
 document.addEventListener('click',event=>{const button=event.target.closest('[data-action]');if(!button)return;if(currentDataSource!=='ami-live'||!cfg.test_controls_enabled){alert(t('کنترل این نشست فعال نیست؛ ابتدا اتصال زنده و گیت صف را بررسی کن.','Live controls are locked in this session.'));return;}if(armedQueue&&button.dataset.queue&&armedQueue!==button.dataset.queue){alert(t('کنترل روی صف '+armedQueue+' فعال است؛ برای صف '+button.dataset.queue+' باید گیت همان صف را در تنظیمات فعال کنی.','Controls are armed for queue '+armedQueue+'; arm queue '+button.dataset.queue+' separately.'));return;}actionTarget={...button.dataset};$('action-title').textContent=actionNames[actionTarget.action];$('action-description').textContent=actionTarget.queue+' · '+(actionTarget.agent||actionTarget.channel||'');$('action-error').textContent='';let fields='';
  if(['spy','whisper','barge'].includes(actionTarget.action))fields=`<p>${t('تماس ابتدا به داخلی اختصاصی حساب شما برقرار می‌شود.','Your assigned phone rings first.')}: <strong dir="ltr">${esc(cfg.assigned_phone||'—')}</strong></p><p>${t('برای شروع باید به تماس پاسخ بدهی. فقط روی مکالمه آزمایشی دارای رضایت استفاده کن.','Answer your assigned phone to start. Use only a consenting test call.')}</p>`;
  if(actionTarget.action==='priority')fields=`<label>${t('اولویت جدید؛ عدد بالاتر زودتر پاسخ می‌گیرد','New priority; higher is served first')}<input type="number" name="priority" min="-1000000" max="1000000" value="1" required></label>`;
  if(actionTarget.action==='penalty'||actionTarget.action==='add')fields=`${actionTarget.action==='add'?`<label>${t('رابط کارشناس، مانند PJSIP/100','Agent interface, e.g. PJSIP/100')}<input name="agent" dir="ltr" placeholder="PJSIP/100" required maxlength="100"></label>`:''}<label>${t('وزن توزیع؛ عدد کمتر اولویت بیشتری دارد','Penalty; lower gets calls first')}<input name="penalty" type="number" min="0" max="100" value="0" required></label>`;
  if(actionTarget.action==='hangup')fields=`<p>${t('این عملیات تماس انتخاب‌شده را قطع می‌کند.','This disconnects the selected call.')}</p>`;
  if(actionTarget.action==='remove')fields=`<p>${t('عضویت پویا از صف حذف می‌شود؛ برای عضویت ثابت از تنظیمات ایزابل استفاده کنید.','Removes dynamic membership. Manage static members in Issabel.')}</p>`;
  $('action-fields').innerHTML=fields;$('action-dialog').showModal();
 });
 $('action-cancel').onclick=()=>$('action-dialog').close();
 $('action-form').onsubmit=async event=>{event.preventDefault();if(!actionTarget)return;const submit=event.submitter||$('action-form').querySelector('[type=submit]');submit.disabled=true;const fields=Object.fromEntries(new FormData(event.target));
  try{await fetchJSON(cfg.control_url,{method:'POST',headers:{'X-CSRF-Token':cfg.csrf,'Content-Type':'application/x-www-form-urlencoded'},body:new URLSearchParams({...actionTarget,...fields})});$('action-dialog').close();await refresh();}
  catch(error){const errors={
  control_queue_mismatch:t('گیت کنترل برای صف دیگری فعال است. ابتدا در تنظیمات، کنترل صف '+actionTarget.queue+' را جداگانه فعال کن.','Controls are armed for another queue; arm queue '+actionTarget.queue+' first.'),
  control_gate_not_armed_for_current_session:t('کنترل این کاربر/نشست فعال نیست یا منقضی شده. ابتدا صف موردنظر را در تنظیمات فعال کن.','Controls are not armed for this login/session.'),
  action_not_permitted_by_role_or_target:t('مجوز این عملیات یا هدف تماس برای حساب شما وجود ندارد.','Your account lacks permission for this action/target.'),
  assigned_supervisor_phone_required:t('داخلی تلفن کاربر در حساب تعریف نشده؛ مدیر باید PJSIP/100 یا داخلی واقعی شما را ثبت کند.','Assign your own phone to this account first.'),
  agent_not_in_active_call:t('کارشناس در مکالمه فعال نیست؛ شنود/نجوا فقط روی مکالمه برقرارشده کار می‌کند.','Agent has no established call to monitor.'),
  call_not_waiting_in_selected_queue:t('این تماس دیگر در صف انتخابی منتظر نیست؛ داده را تازه‌سازی کن.','Caller is no longer waiting in this queue; refresh.'),
  asterisk_action_rejected:t('Asterisk درخواست را رد کرد. وضعیت تماس و Action مجاز را بررسی کن.','Asterisk rejected the AMI action.'),
  asterisk_action_failed_or_disconnected:t('ارتباط کنترل AMI برقرار نشد یا عملیات خطا داد.','AMI control connection failed.'),
  destination_not_allowed:t('مقصد تلفن باید فقط داخلی همان کاربر واردشده باشد.','Target must be the logged-in user phone.')};
 $('action-error').textContent=errors[error.message]||(['minimum_ready','queue_exit_limit_reached','configure_roster_size_before_leaving','queue_roster_full'].includes(error.message)?t('حداقل ظرفیت صف اجازه این تغییر را نمی‌دهد.','Minimum queue staffing prevents this change.'):t('عملیات انجام نشد: ','Action failed: ')+error.message);}
  finally{submit.disabled=false;}
 };
 async function loadAudit(){try{const data=await fetchJSON(cfg.audit_url);$('audit-rows').innerHTML=data.events.map(row=>`<tr><td>${esc(new Date(row.timestamp*1000).toLocaleString(fa?'fa-IR':'en-GB'))}</td><td>${esc(row.user||'—')}</td><td>${esc(actionNames[row.action]||row.action)}</td><td>${esc(row.queue||'—')}</td><td>${row.status<400?t('پذیرش HTTP؛ اجرای PBX نامشخص','HTTP accepted; PBX unverified'):t('ناموفق','Failed')} (${row.status})</td></tr>`).join('')||empty(t('عملیاتی ثبت نشده است.','No recorded actions.'),5);}catch{$('audit-rows').innerHTML=empty(t('دریافت سوابق ممکن نیست.','Could not load audit events.'),5);}}
 $('audit-refresh').onclick=loadAudit;
 const showView=key=>{const button=document.querySelector(`[data-view="${key}"]`);if(button)button.click();};
 document.addEventListener('click',event=>{const b=event.target.closest('button[data-open]');if(!b)return;showView(b.dataset.open);if(b.dataset.scroll){setTimeout(()=>$(b.dataset.scroll)?.scrollIntoView({block:'center',behavior:'smooth'}),50);}});
 function exitWallboard(){if(document.fullscreenElement)document.exitFullscreen().catch(()=>{});document.body.classList.remove('wallboard');$('wallboard-fullscreen').textContent=t('⛶ تمام‌صفحه','⛶ Fullscreen');}
 $('wallboard-fullscreen').onclick=async()=>{showView('wallboard');const stage=$('wallboard-stage');try{if(!document.fullscreenElement){await stage.requestFullscreen();document.body.classList.add('wallboard');}else exitWallboard();}catch{document.body.classList.add('wallboard');}};
 $('wallboard-exit').onclick=()=>{exitWallboard();showView('live');};
 $('wallboard-queue-picker').onchange=event=>{const target=event.target.closest('[data-wb-queue]');if(!target)return;wallboardVisible=[...$('wallboard-queue-picker').querySelectorAll('input:checked')].map(x=>x.dataset.wbQueue);storage.set('wallboard-queues',JSON.stringify(wallboardVisible));renderWallboard(selected(),[]);renderJourneyViews();};
 $('wb-select-all').onclick=()=>{wallboardVisible=null;storage.set('wallboard-queues','null');renderWallboard(selected(),[]);};
 document.addEventListener('fullscreenchange',()=>{if(!document.fullscreenElement)document.body.classList.remove('wallboard');});

 $('queue-focus-cards').addEventListener('click',event=>{const button=event.target.closest('[data-focus]');if(!button)return;$('queue-filter').value=button.dataset.focus;render();showView('calls');});
 $('queue-cards').addEventListener('click',event=>{const button=event.target.closest('.queue-focus-link');if(!button)return;$('queue-filter').value=button.dataset.focus;render();showView('queues');});
 document.addEventListener('keydown',event=>{if(event.altKey||event.ctrlKey||event.metaKey||/INPUT|TEXTAREA|SELECT/.test(document.activeElement?.tagName)||$('action-dialog').open)return;if(event.key==='/'){event.preventDefault();$('search').focus();}if(event.key.toLowerCase()==='r'){event.preventDefault();refresh();}});

 document.querySelector('.brand')?.setAttribute('title','SaneQueue — ' + cfg.build_version);

 const amiState={settings:null,snapshot:null};
 const amiErrors={authentication_or_action_denied:t('نام کاربری، رمز یا مجوز QueueStatus رد شده است.','Username, password, or QueueStatus permission was rejected.'),connection_timeout:t('پاسخ AMI دیر رسید. تونل SSH را بررسی کن.','AMI request timed out. Check SSH tunnel.'),ssh_tunnel_refused:t('ارتباط به میزبان و پورت انتخابی رد شد؛ تونل SSH یا فایروال را بررسی کن.','Connection refused; check SSH tunnel, AMI listener and firewall.'),ssh_tunnel_or_network_error:t('ارتباط شبکه یا تونل SSH برقرار نیست.','Network or SSH tunnel is unavailable.'),live_adapter_failed:t('تست AMI موفق است، اما دریافت داده کامل صف با خطا مواجه شد.','AMI probe succeeded, but structured queue data could not be loaded.'),ami_or_parser_error:t('ارتباط یا دریافت رویداد AMI با خطا مواجه شد.','AMI connection or event reading failed.'),invalid_test_scope:t('آدرس خصوصی شبکه، پورت یا نام صف معتبر نیست.','Use a valid private LAN IP, port and queue.'),missing_credentials:t('نام کاربری و رمز AMI را وارد کن.','Enter AMI username and password.'),request_failed:t('درخواست ناموفق بود. لاگ سرور را بررسی کن.','Request failed. Check the local server log.')};
 function showAmiFeedback(ok,message){const box=$('ami-feedback');box.className='ami-feedback '+(ok?'success':'error');box.textContent=message;}
 function showAmiError(error,stage){showAmiFeedback(false,(stage==='parser'?t('اتصال زنده: ','Live parser: '):t('تست AMI: ','AMI probe: '))+(amiErrors[error.message]||error.message));}

 const amiPresets={lan:['192.168.2.2',5038],tunnel:['127.0.0.1',15038]};
 const amiPreset=$('ami-preset');
 function reflectAmiPreset(){const host=$('ami-host').value.trim(),port=Number($('ami-port').value);const matched=Object.entries(amiPresets).find(([,value])=>value[0]===host&&value[1]===port);amiPreset.value=matched?matched[0]:'custom';$('ami-manual').hidden=!!matched;}
 amiPreset.onchange=()=>{const pair=amiPresets[amiPreset.value];if(pair){$('ami-host').value=pair[0];$('ami-port').value=pair[1];}$('ami-manual').hidden=!!pair;};
 const formToPayload=()=>({host:$('ami-host').value.trim(),port:$('ami-port').value.trim(),user:$('ami-user').value.trim(),password:$('ami-password').value,queue:$('ami-queue').value.trim(),visible_queues:$('ami-visible-queues').value.trim()});
 function fillAmiForm(settings){if(!settings)return;$('ami-host').value=settings.host||'127.0.0.1';$('ami-port').value=settings.port||15038;$('ami-user').value=settings.user||'sq_readonly';/* AMI password is kept in the form across successful or failed tests; never serialized to disk. */$('ami-queue').value=settings.queue||'*';$('ami-visible-queues').value=settings.visible_queues||'!default';reflectAmiPreset();renderAmiStatus(settings, amiState.snapshot);}
 function renderAmiStatus(settings,snapshot){const live=settings&&settings.enabled; $('ami-mode-tag').textContent=live?t('داده زنده فعال','Live data enabled'):t('داده ساختگی','Sample data'); $('ami-status-pill').textContent=snapshot&&snapshot.connected?t('اتصال موفق','Connection ok'):(snapshot&&snapshot.connected===false?t('اتصال ناموفق','Connection failed'):t('آماده','Ready')); const summary=[]; summary.push((live?t('منبع فعلی: داده زنده AMI','Current source: live AMI data'):t('منبع فعلی: داده ساختگی','Current source: sample data'))); if(settings){summary.push((fa?'میزبان: ':'Host: ')+(settings.host||'127.0.0.1')+':'+(settings.port||15038)); summary.push((fa?'کاربر: ':'User: ')+(settings.user||'sq_readonly'));} if(snapshot){ if(snapshot.queue_requested) summary.push((fa?'صف تست: ':'Test queue: ')+snapshot.queue_requested); if(snapshot.connected===true) summary.push((fa?'اعضا / منتظر: ':'Members / waiting: ')+(snapshot.members??'—')+' / '+(snapshot.waiting_calls??'—')); if(snapshot.error) summary.push((fa?'خطا: ':'Error: ')+snapshot.error);} $('ami-connection-summary').textContent=summary.join(' • '); $('ami-snapshot-output').textContent=JSON.stringify(snapshot||{}, null, 2); }
 async function loadAmiSettings(){try{const result=await fetchJSON(cfg.ami_settings_url);amiState.settings=result.settings||{};amiState.snapshot=result.snapshot||null;fillAmiForm(amiState.settings);}catch(error){$('ami-connection-summary').textContent=t('دریافت تنظیمات AMI ممکن نیست.','Could not load AMI settings.');$('ami-snapshot-output').textContent=String(error.message||error);}}
 async function submitAmi(url,extra){const payload={...formToPayload(),...(extra||{})};const result=await fetchJSON(url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify(payload)});amiState.settings=result.settings||amiState.settings;amiState.snapshot=result.snapshot||amiState.snapshot;fillAmiForm(amiState.settings);if(result.snapshot)renderAmiStatus(amiState.settings,result.snapshot);return result;}
 $('ami-save').onclick=async()=>{try{const result=await submitAmi(cfg.ami_settings_url);showView('settings');showAmiFeedback(true,t('تنظیمات اتصال ذخیره شد؛ رمز فقط در حافظه برنامه نگهداری می‌شود.','Connection preferences saved; password remains in memory only.'));$('toast').hidden=false;$('toast').textContent=t('تنظیمات ذخیره شد.','Settings saved.');setTimeout(()=>{$('toast').hidden=true;},2500);}catch(error){showAmiError(error,'probe');}};
 const amiDiagNames={target:t('اعتبارسنجی آدرس و صف','Validate target'),tcp:t('اتصال شبکه/تونل','TCP/SSH tunnel'),login:t('احراز هویت AMI','AMI login'),queue_status:t('پاسخ QueueStatus','QueueStatus response'),live_parser:t('تبدیل داده Asterisk','Native Asterisk data parsing'),visibility:t('انطباق صف‌های قابل نمایش','Visible Issabel queues')};
 const amiDiagErrors={invalid_ami_target:t('آدرس خصوصی، پورت یا نام صف نامعتبر است.','Invalid private IP/port/queue.'),missing_credentials:t('رمز جدید را در همین صفحه وارد کن. رمز در ZIP جدید منتقل نمی‌شود.','Enter password in this instance; passwords never migrate between ZIPs.'),tcp_connection_refused:t('پورت AMI در دسترس نیست؛ سرویس، فایروال و مجوز IP را بررسی کن.','AMI port refused; check listener, firewall and host permit.'),ami_network_unreachable:t('مسیر شبکه به AMI برقرار نیست.','AMI network path unavailable.'),ami_authentication_rejected:t('حساب یا رمز یا permit رد شده است.','AMI username/password/host permit rejected.'),queue_status_permission_denied:t('ورود موفق بود، ولی Action QueueStatus رد شد؛ مجوز را بررسی کن.','Logged in, but QueueStatus was denied.'),ami_timeout:t('پاسخ دیر رسید یا صف کامل دریافت نشد.','AMI timed out/incomplete QueueStatus.'),no_visible_queues_match:t('QueueStatus موفق است ولی شناسه صف‌های Issabel در فیلتر نمایش با داده دریافتی یکی نیست؛ مقدار فیلتر را بررسی کن.','QueueStatus worked; Issabel display queue IDs do not match. Review visible queues.'),ami_connection_closed:t('سرور AMI ارتباط را بست.','AMI server closed connection.'),ami_unexpected_response:t('پاسخ دریافتی غیرمنتظره است.','Unexpected AMI reply.')};
 $('ami-diagnose').onclick=async()=>{
   const b=$('ami-diagnose'); b.disabled=true;
   $('ami-diagnose-status').textContent=t('در حال بررسی بدون تغییر تماس...','Running safe read-only diagnostics...');
   try{const result=await fetchJSON('/api/ami/diagnose',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify(formToPayload())});
       $('ami-diagnose-status').textContent=result.ready?t('تمام مراحل موفق شدند. اکنون «فعال‌سازی داده زنده» را بزن.','All stages passed; enable live data.'):amiDiagErrors[result.error_code]||result.error_code;
       $('ami-diagnostic-stages').innerHTML=(result.stages||[]).map(x=>`<div class="diag-stage ${x.ok?'passed':'failed'}"><span>${x.ok?'✓':'×'} ${esc(amiDiagNames[x.stage]||x.stage)}</span><b>${x.ok?t('موفق','Pass'):esc(amiDiagErrors[x.code]||x.code||t('ناموفق','Failed'))}</b></div>`).join('');
   }catch(e){$('ami-diagnose-status').textContent=t('ارتباط با سرویس محلی پنل قطع است.','Local panel API request failed.')+' '+e.message;}
   finally{b.disabled=false;}
 };
 $('ami-test').onclick=async()=>{try{const result=await submitAmi(cfg.ami_test_url);renderAmiStatus(amiState.settings,result.snapshot);showView('settings');showAmiFeedback(true,t('تست AMI و QueueStatus موفق شد. حالا فعال‌سازی داده زنده را بزن.','AMI login and QueueStatus succeeded. Now enable live data.'));}catch(error){showAmiError(error,'probe');}};
 $('ami-enable').onclick=async()=>{try{const result=await submitAmi(cfg.ami_connect_url,{action:'enable',enabled:true});renderAmiStatus(amiState.settings,result.snapshot);showView('settings');await refresh();showAmiFeedback(true,t('داده واقعی صف انتخابی وارد داشبورد شد.','Selected queue live data is enabled.'));}catch(error){showAmiError(error,'adapter');}};
 $('ami-disable').onclick=async()=>{try{const result=await submitAmi(cfg.ami_connect_url,{action:'disable',enabled:false});renderAmiStatus(amiState.settings,result.snapshot||amiState.snapshot);await refresh();showView('settings');}catch(error){showAmiError(error,'adapter');}};

async function updateControlBadge(){
 try {
   const state=await fetchJSON(cfg.controls_status_url);
   const enabled=!!state.enabled;
   armedQueue=enabled?String(state.queue||''):'';
   cfg.test_controls_enabled=enabled;
   $('test-controls-badge').className='badge '+(enabled?'':'pending');
   $('test-controls-badge').textContent=enabled?t('فعال','Enabled'):t('غیرفعال','Disabled');
   $('test-controls-info').textContent=enabled?t('صف مجاز: ','Authorized queue: ')+(state.queue||'—')+' · '+t('زمان باقی‌مانده: ','Remaining: ')+Math.ceil((state.remaining_seconds||0)/60)+' '+t('دقیقه','min')
     :t('کنترل‌های واقعی قفل هستند. ابتدا اتصال زنده AMI را فعال کن.','Live controls are locked. Enable live AMI first.');
 }catch(error){ $('test-controls-info').textContent=t('وضعیت کنترل‌ها قابل دریافت نیست.','Control status unavailable.'); }
}
$('test-scope-queue').onchange=()=>{$('test-confirm-target').textContent='ENABLE '+($('test-scope-queue').value||'—');};
$('test-controls-enable').onclick=async()=>{
 if(!confirm(t('این دکمه امکان تغییر وضعیت صف آزمایشی و قطع تماس تست را به مدت ۳۰ دقیقه فعال می‌کند. مطمئنی؟',
               'Enable test PBX call-changing actions for 30 minutes?')))return;
 try {
  const state=await fetchJSON(cfg.controls_toggle_url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},
    body:JSON.stringify({action:'enable',queue:$('test-scope-queue').value,confirmation:$('test-confirm-phrase').value.trim()})});
  cfg.test_controls_enabled=!!state.enabled;
  $('test-confirm-phrase').value='';
  await updateControlBadge();
  alert(t('کنترل‌های تست برای ۳۰ دقیقه فعال شدند.','Test controls enabled for 30 minutes.'));
 }catch(error){alert(t('اتصال زنده، انتخاب صف و عبارت ENABLE همان صف الزامی است.','Enable live AMI, choose a queue, and type its exact ENABLE phrase.')+'\n'+error.message);}
};
$('test-controls-disable').onclick=async()=>{
 try {await fetchJSON(cfg.controls_toggle_url,{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify({action:'disable'})});
  cfg.test_controls_enabled=false;await updateControlBadge();}
 catch(error){alert(error.message);}
};

 const capabilities=[
  ['monitor', t('مانیتورینگ لحظه‌ای صف','Live queue monitoring'),t('دریافت صف، اعضا، SLA و انتظار از AMI','Queue members, SLA and waiting via AMI'),'beta'],
  ['staff',t('Pause، Penalty و عضویت پویا','Pause, penalty and dynamic members'),t('آزمایشی؛ فقط با گیت کنترل و تماس تست','Staged: test queue and control gate only'),'beta'],
  ['supervision',t('شنود، نجوا و ورود به مکالمه','Listen, whisper, barge'),t('اتصال و دریافت صدای کارشناس آزموده شده؛ تأیید کامل مسیر صدا لازم است','Connection and agent audio tested; full audio acceptance still required'),'beta'],
  ['dashboard',t('داشبورد، هشدار، Wallboard و نمودار زنده','Dashboard, alerts, wallboard, live charts'),t('نمودار بر اساس نمونه‌های همین مرورگر','Charts from current browser samples only'),'ready'],
  ['pbx',t('کانال‌های فعال، PJSIP و ParkedCalls','Channels, PJSIP and parked calls'),t('فقط خواندنی؛ با مجوز AMI مناسب','Read-only, optional AMI privileges'),'beta'],
  ['transfer',t('انتقال Blind / Attended و Pickup','Blind/attended transfer and pickup'),t('نیازمند پیاده‌سازی و تست ARI/AMI','Requires new AMI/ARI implementation'),'planned'],
  ['park',t('پارک و بازگردانی تماس','Park and retrieve calls'),t('نمایش وضعیت اولیه آماده تست، اجرای فرمان برنامه‌ریزی‌شده','Read inventory beta, controls planned'),'planned'],
  ['trunks',t('سلامت ترانک‌های SIP و کیفیت RTP','SIP trunk and RTP quality'),t('نیازمند آداپتور جدا و RTCP/QoS','Dedicated registration/RTCP adapter needed'),'planned'],
  ['softphone',t('WebRTC Softphone و موبایل','WebRTC & mobile softphone'),t('نیازمند WSS/TLS، SIP.js و تنظیمات PBX','Requires WSS/TLS, SIP.js and PBX config'),'planned'],
  ['contacts',t('دفترچه تلفن صف','Queue directory'),t('ثبت مخاطب با دسترسی صف؛ CRM و کلیک‌توکال در برنامه توسعه','Queue-scoped contacts; CRM and click-to-call planned'),'beta'],
  ['shifts',t('برنامه شیفت','Shift planning'),t('ثبت شیفت و جلوگیری از تداخل؛ بدون تغییر وضعیت PBX','Schedules with overlap validation; no PBX state changes'),'beta'],
  ['roles',t('احراز هویت چندکاربره و تفکیک سازمانی','Multiuser RBAC and tenants'),t('ورود محلی و RBAC آزمایشی موجود؛ نیازمند سخت‌سازی تولیدی','Local login and scoped RBAC; production hardening pending'),'beta'],
  ['ai',t('AI Copilot فارسی، هشدار هوشمند و STT','Persian AI copilot and STT'),t('نیازمند مدل محلی و سیاست حریم خصوصی','Needs local model and privacy policy'),'planned']
 ];
 $('feature-catalog').innerHTML=capabilities.map(([id,label,desc,state])=>`<article class="cap-card"><span class="cap-icon">${id==='monitor'?'◉':id==='softphone'?'☎':id==='ai'?'✦':'◫'}</span><div><b>${esc(label)}</b><p>${esc(desc)}</p></div><span class="cap-pill ${state}">${state==='ready'?t('آماده آزمایش','Available'):state==='beta'?t('بتا','Beta'):t('برنامه توسعه','Planned')}</span></article>`).join('');
 document.querySelectorAll('[data-pbx-check]').forEach(button=>button.onclick=async()=>{
  const kind=button.dataset.pbxCheck;const resultBox=$('pbx-health-results');const info=$('pbx-health-status');
  info.textContent=t('در حال دریافت اطلاعات فقط خواندنی از AMI...','Requesting read-only AMI data...');button.disabled=true;
  try{
   const response=await fetchJSON('/api/pbx/health?kind='+encodeURIComponent(kind));
   if(!response.supported){
    const r=response.reason||response.error||'unknown';
    const reasons={action_permission_denied:t('فرمان AMI برای این حساب مجاز نیست. مجوز Action را روی سرور بررسی کن.','Action is not authorized for this AMI user.'),action_or_module_unavailable:t('Action ثبت نشده یا ماژول مربوط بارگذاری نشده است.','Action is unavailable or its module is not loaded.'),event_list_incomplete:t('فرمان پذیرفته شد ولی رویدادهای پاسخ کامل نرسیدند؛ کلاس read را بررسی کن.','Action accepted, but result events were not received; check read event class.'),timeout:t('مهلت دریافت پاسخ تمام شد.','AMI response timed out.'),connection_lost:t('ارتباط AMI قطع شد.','AMI connection lost.'),timeout_or_network:t('ارتباط AMI در دسترس نبود.','AMI network or tunnel problem.'),ami_action_rejected:t('AMI فرمان را رد کرد؛ جزئیات مجوزها را بررسی کن.','AMI rejected the action; inspect privileges.')};
    info.textContent=reasons[r]||t('نتیجه آزمایش AMI ناموفق است؛ قسمت مجوزها را بررسی کن.','AMI test failed; check permissions.');
    if((kind==='extensions'||kind==='contacts')&&(r==='action_permission_denied'||r==='action_or_module_unavailable')) info.textContent+=' '+t('روی سرور تست: manager show command PJSIPShowEndpoints / PJSIPShowContacts و module show like res_pjsip_manager را بررسی کن؛ مجوز system را بدون ارزیابی امنیتی اضافه نکن.','On test PBX check manager show command PJSIPShowEndpoints / PJSIPShowContacts and module show like res_pjsip_manager; do not grant system privilege without review.');
    resultBox.textContent=JSON.stringify({kind:response.kind,action:response.action,reason:r,supported:false},null,2);return;
   }
   info.textContent=t('نتیجه زنده و بدون شماره تماس‌گیرنده','Live data with no caller numbers');
   const data=response.data||{};
   const items=kind==='channels'?[[t('کانال‌ها (نه تماس یکتا)','Channel legs'),data.channel_legs],[t('کانال‌های Up','Up channels'),data.up],[t('زنگ‌خور','Ringing'),data.ringing]]:kind==='extensions'?[[t('نقاط پایانی SIP/PJSIP','SIP/PJSIP endpoints / peers'),data.total],[t('آزاد بر اساس state','Available by state'),data.available]]:kind==='parking'?[[t('تماس پارک شده','Parked calls'),data.parked_calls]]:kind==='contacts'?[[t('کانتکت‌های PJSIP','PJSIP contacts'),data.contacts],[t('در دسترس','Available'),data.available]]:kind==='registrations'?[[t('رجیستری خروجی','Outbound registrations'),data.registrations],[t('رجیستر','Registered'),data.registered],[t('ناموفق / بدون رجیستر','Not registered'),data.unregistered]]:[];
   if(kind==='permissions'){
     const actions=response.actions||{};
     const flags=Object.entries(actions).map(([name,available])=>`<div class="permission-row"><span dir="ltr">${esc(name)}</span><span class="permission-flag ${available?'granted':'denied'}">${available?t('مجاز','Allowed'):t('غیرمجاز یا فاقد ماژول','Not allowed/unavailable')}</span></div>`).join('');
     resultBox.innerHTML=`<section class="permissions-list">${flags}</section>`;
     info.textContent=t('مجوزهای Action براساس ListCommands؛ مجوز رویداد (read) و سلامت ماژول جداست.','Action access from ListCommands; event read permission and module health are separate.');
     return;
   }
   resultBox.innerHTML=items.map(([title,count])=>`<div class="pbx-live-tile"><small>${esc(title)}</small><strong>${fmt(count)}</strong></div>`).join('');
  }catch(error){info.textContent=t('امکان دریافت وجود ندارد: ','Could not read: ')+(amiErrors[error.message]||error.message);resultBox.textContent='';}
  finally{button.disabled=false;}
 });



 let accountsCache={}; let phoneInventory=[];
 const pickedQueues=()=>[...document.querySelectorAll('#user-queues input[type=checkbox]:checked')].map(n=>n.value);
 function renderQueueChoices(selection){
  const holder=$('user-queues');if(!holder)return;
  const chosen=new Set(selection||pickedQueues());
  holder.innerHTML=policyAvailable.map(id=>`<label class="sq-choice"><input type="checkbox" value="${esc(id)}" ${chosen.has(id)?'checked':''}><span>صف <bdi dir="ltr">${esc(id)}</bdi>${queues[id]?.Name&&queues[id].Name!==id?` · ${esc(queues[id].Name)}`:''}</span></label>`).join('')||`<span class="muted">${t('هیچ صف مجازی از AMI دریافت نشد. اتصال را بررسی کن.','No authorized queues loaded from AMI.')}</span>`;
 }
 const normalizePhone=s=>String(s||'').trim();
 const phoneFromMember=s=>{const raw=String(s||'');const found=raw.match(/(?:PJSIP|SIP)\/([A-Za-z0-9_.-]+)/i)||raw.match(/(?:Local|hint:)\/?([A-Za-z0-9_.-]+)@/i);return found?'PJSIP/'+found[1]:'';};
 function knownPhones(){const found=new Set();for(const q of Object.values(queues||{}))for(const m of Object.values(q.members||{}))for(const candidate of [m.StateInterface,m.Location,m.Interface,m.Name]){const p=phoneFromMember(candidate);if(p)found.add(p);}return [...found].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));}
 function renderPhoneOptions(phones,selected){const select=$('account-phone');if(!select)return;const chosen=normalizePhone(selected??select.value);const list=[...new Set((phones||[]).map(normalizePhone).filter(x=>/^(PJSIP|SIP)\/[A-Za-z0-9_.-]+$/.test(x)))].sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  select.innerHTML=`<option value="">${t('بدون داخلی (فقط مدیر/مشاهده‌گر)','No extension (admin/viewer only)')}</option>`+list.map(v=>`<option value="${esc(v)}">${esc(v)}</option>`).join('');
  if(chosen&&!list.includes(chosen)){select.add(new Option(chosen+' '+t('(قبلاً ثبت‌شده)','(previously assigned)'),chosen));}
  select.value=chosen||'';
 }
 async function refreshUserCatalog(){if(!$('users-view'))return;
  const previous=$('account-phone').value;
  const fromQueue=knownPhones();
  renderQueueChoices();renderPhoneOptions(fromQueue,previous);
  const status=$('account-phone-status'),info=$('user-catalog-info');
  status.textContent=t('در حال خواندن داخلی‌های PJSIP از AMI...','Reading PJSIP endpoints from AMI...');
  try{const result=await fetchJSON('/api/pbx/health?kind=extensions');
    if(!result.supported)throw Error(result.reason||'pjsip_inventory_unavailable');
    const live=(result.data?.endpoints||[]).map(x=>'PJSIP/'+String(x.endpoint||'')).filter(x=>/^PJSIP\/\d{2,8}$/.test(x));
    const all=[...new Set([...live,...fromQueue])];phoneInventory=all;renderPhoneOptions(all,previous);
    status.textContent=t('داخلی‌های خوانده‌شده از PBX: ','PBX endpoints: ')+fmt(live.length);
    if(info)info.textContent=t('صف‌های قابل انتخاب: ','Selectable queues: ')+fmt(policyAvailable.length)+' · '+t('داخلی‌ها: ','Extensions: ')+fmt(all.length);
  }catch(error){status.textContent=t('لیست کامل PJSIP دردسترس نیست؛ داخلی‌های شناسایی‌شده از اعضای صف نمایش داده شدند.','Full PJSIP inventory unavailable; using queue member extensions.');if(info)info.textContent=t('دریافت لیست کامل نیازمند مجوز PJSIPShowEndpoints است.','Full list needs PJSIPShowEndpoints permission.')+' ('+esc(error.message)+')';}
 }
 function renderAccountList(){const list=$('account-list');if(!list)return;const grants=policyState?.supervisors||{};
  const entries=Object.entries(accountsCache);
  list.innerHTML=entries.map(([id,u])=>{const g=grants[id]||{};return `<div class="user-row-v14"><div class="user-identity"><span class="user-avatar">${esc(id[0]?.toUpperCase()||'?')}</span><div><strong>${esc(id)}</strong><small>${esc(u.role||'viewer')} · <bdi dir="ltr">${esc(u.phone||t('بدون داخلی','No phone'))}</bdi></small></div></div><div><small>${t('صف‌های مجاز','Queues')}</small><strong>${u.role==='admin'?t('تمام صف‌ها','All queues'):esc((g.queues||[]).join('، ')||'—')}</strong></div><div><small>${t('عملیات','Permissions')}</small><span class="user-grant-tags">${u.role==='admin'?t('دسترسی مدیر','Administrator'):esc((g.actions||[]).join(' · ')||'—')}</span></div><div class="user-row-actions"><button type="button" data-edit-user="${esc(id)}">${t('ویرایش','Edit')}</button><button type="button" data-delete-user="${esc(id)}" ${id===cfg.logged_in_user?'disabled':''}>${t('حذف','Delete')}</button></div></div>`;}).join('')||`<p class="empty">${t('حسابی ثبت نشده','No accounts')}</p>`;
  const count=$('user-account-count');if(count)count.textContent=fmt(entries.length);
 }
 function clearUserEditor(){ $('account-create-form').reset();$('account-user').readOnly=false;$('account-feedback').textContent='';renderQueueChoices([]);renderPhoneOptions([...phoneInventory,...knownPhones()],'');$('user-permission-select').querySelectorAll('input').forEach(x=>x.checked=x.value==='view'); }
 async function loadUsers(){if(!$('users-view'))return;
  try{if(!policyState)await loadPolicyEditor();const result=await fetchJSON('/api/accounts');accountsCache=result.accounts||{};renderAccountList();renderQueueChoices();await refreshUserCatalog();}catch(error){$('account-feedback').textContent=t('دریافت کاربران انجام نشد: ','Could not load users: ')+error.message;}}
 if($('users-view')){
 $('user-clear').onclick=clearUserEditor;
 $('refresh-user-catalog').onclick=()=>refreshUserCatalog();
 $('account-list').onclick=async e=>{const edit=e.target.closest('[data-edit-user]'),del=e.target.closest('[data-delete-user]');if(edit){const id=edit.dataset.editUser,u=accountsCache[id];if(!u)return;$('account-user').value=id;$('account-user').readOnly=true;$('account-role').value=u.role||'viewer';$('account-phone').value=u.phone||'';$('account-password').value='';const g=policyState?.supervisors?.[id]||{};renderQueueChoices(g.queues||[]);renderPhoneOptions([...phoneInventory,...knownPhones(),u.phone||''],u.phone||'');$('user-permission-select').querySelectorAll('input').forEach(x=>x.checked=(g.actions||['view']).includes(x.value));$('account-feedback').textContent=t('در حال ویرایش حساب ','Editing account ')+id;window.scrollTo({top:0,behavior:'smooth'});return;}
   if(del){const id=del.dataset.deleteUser;if(!confirm(t('حساب '+id+' حذف شود؟','Delete '+id+'?')))return;try{const result=await fetchJSON('/api/accounts',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify({action:'delete',username:id})});accountsCache=result.accounts||{};if(policyState?.supervisors?.[id]){delete policyState.supervisors[id];await savePolicyState();}clearUserEditor();renderAccountList();}catch(error){$('account-feedback').textContent=t('حذف ناموفق: ','Delete failed: ')+error.message;}}};
 $('account-create-form').onsubmit=async e=>{e.preventDefault();const save=$('account-create-form').querySelector('[type=submit]');save.disabled=true;
  const id=$('account-user').value.trim(),qids=pickedQueues(),actions=[...$('user-permission-select').querySelectorAll('input:checked')].map(x=>x.value);
  try{if(!id)throw Error('username_required');if(!policyState)await loadPolicyEditor();if(qids.some(q=>!policyAvailable.includes(q)))throw Error(t('شماره صف باید در فهرست صف‌های موجود باشد.','Queue must exist in AMI scope.'));if(qids.length&&!actions.length)throw Error(t('حداقل یک مجوز انتخاب کن.','Choose at least one grant.'));
   const result=await fetchJSON('/api/accounts/with-grants',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify({username:id,role:$('account-role').value,phone:$('account-phone').value,password:$('account-password').value,queues:qids,actions:actions})});
   accountsCache=result.accounts||{};
   policyState=result.policies||policyState;
   $('account-feedback').textContent=t('حساب، داخلی و دسترسی‌ها یکجا ذخیره شدند.','Account, extension and permissions saved together.');
   renderAccountList();$('account-password').value='';$('account-user').readOnly=true;
  }catch(error){$('account-feedback').textContent=t('ثبت ناموفق: ','Save failed: ')+error.message;}finally{save.disabled=false;}
 };

 } // admin-only account editor
 function policyQueueForm(name){
   const policy=policyState?.queues?.[name]||defaultPolicy();
   const a=policy.alerts||defaultPolicy().alerts,st=policy.staffing||defaultPolicy().staffing;
   $('pq-label').value=policy.label||'';
   $('pq-waiting').value=a.waiting_above;
   $('pq-seconds').value=a.wait_seconds_above;
   $('pq-ready').value=a.min_ready;
   $('pq-cooldown').value=a.cooldown_seconds;
   $('pq-bale').checked=!!a.bale_enabled;
   $('pq-roster').value=st.roster_size;
   $('pq-percent').value=st.max_absent_percent;
   $('pq-count').value=st.max_absent_count;
   $('pq-min').value=st.min_on_duty;
   $('pq-reasons').value=(policy.pause_reasons||defaultPauseReasons).map(x=>x.id+' | '+x.label).join('\n');
   previewPolicyCapacity();
 }
 function previewPolicyCapacity(){
   const count=n($('pq-roster').value),percent=n($('pq-percent').value),absolute=n($('pq-count').value),min=n($('pq-min').value);
   const cap=Math.max(0,Math.min(absolute,Math.floor(count*percent/100),Math.max(0,count-min)));
   $('pq-capacity-preview').textContent=t('حداکثر خروج هم‌زمان: ','Maximum concurrent departures: ')+fmt(cap)+' · '+t('حداقل حاضر: ','Minimum on duty: ')+fmt(Math.max(min,count-cap));
 }
 ['pq-roster','pq-percent','pq-count','pq-min'].forEach(id=>$(id).addEventListener('input',previewPolicyCapacity));
 function updateAmiQueueSelect(){
  const el=$('ami-queue');if(!el)return;const prior=el.value||'*';
  const all=[...new Set([...policyAvailable,...Object.keys(queues||{})])].filter(x=>x!=='default').sort((a,b)=>a.localeCompare(b,undefined,{numeric:true}));
  el.innerHTML=`<option value="*">${t('همه صف‌ها','All queues')}</option>`+all.map(q=>`<option value="${esc(q)}">${esc(q)}</option>`).join('');
  if(prior!=='*'&&!all.includes(prior))el.add(new Option(prior,prior));el.value=prior;
 }
 async function loadPolicyEditor(){
  try{
   const result=await fetchJSON('/api/policies');
   policyState=result.policies||{version:1,queues:{},supervisors:{}};
   policyAvailable=Array.isArray(result.available_queues)?result.available_queues:[];
   renderQueueChoices(); updateAmiQueueSelect();
   baleConfigured=!!result.bale_configured;
   const previous=$('policy-queue').value;
   $('policy-queue').innerHTML=policyAvailable.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join('')||'<option value="">—</option>';
   $('policy-queue').value=policyAvailable.includes(previous)?previous:policyAvailable[0]||'';
   if($('policy-queue').value)policyQueueForm($('policy-queue').value);
   $('policy-bale-status').textContent=baleConfigured?t('ربات بله برای اجرای آزمایشی فعال شده است.','Bale notifier enabled in test configuration.'):t('ارسال بله غیرفعال است؛ توکن در کد ذخیره نشده است.','Bale is disabled; no bot token in source.');
   renderSupervisorGrants();renderAccountList();
  }catch(error){$('policy-feedback').textContent=t('دریافت قوانین صف ناموفق بود: ','Could not load policies: ')+error.message;}
 }
 $('policy-queue').onchange=()=>policyQueueForm($('policy-queue').value);
 function capturePolicy(){
   const name=$('policy-queue').value;
   if(!name||!policyAvailable.includes(name))throw Error('choose_visible_queue');
   const lines=$('pq-reasons').value.split(/\r?\n/).map(x=>x.trim()).filter(Boolean);
   const reasons=lines.map(line=>{
      const pipe=line.indexOf('|');if(pipe<1)throw Error('invalid_pause_reason');
      return {id:line.slice(0,pipe).trim(),label:line.slice(pipe+1).trim()};
   });
   if(!reasons.length)throw Error('at_least_one_reason_required');
   return {name,policy:{label:$('pq-label').value.trim(),alerts:{waiting_above:Number($('pq-waiting').value),wait_seconds_above:Number($('pq-seconds').value),min_ready:Number($('pq-ready').value),cooldown_seconds:Number($('pq-cooldown').value),bale_enabled:$('pq-bale').checked},staffing:{roster_size:Number($('pq-roster').value),max_absent_percent:Number($('pq-percent').value),max_absent_count:Number($('pq-count').value),min_on_duty:Number($('pq-min').value)},pause_reasons:reasons}};
 }
 async function savePolicyState(){
  const response=await fetchJSON('/api/policies',{method:'POST',headers:{'Content-Type':'application/json','X-CSRF-Token':cfg.csrf},body:JSON.stringify(policyState)});
  policyState=response.policies;
  return response;
 }
 $('policy-queue-save').onclick=async()=>{
  try{const {name,policy}=capturePolicy();policyState.queues[name]=policy;
      await savePolicyState();$('policy-feedback').textContent=t('قوانین صف ذخیره شدند.','Queue policy saved.');render();}
  catch(error){$('policy-feedback').textContent=t('خطا در ذخیره قوانین: ','Save failed: ')+error.message;}
 };
 function renderSupervisorGrants(){
  if(!$('policy-grants'))return;
  $('policy-grants').innerHTML=Object.entries(policyState?.supervisors||{}).map(([user,g])=>`<div class="grant-row"><b>${esc(user)}</b><small>${esc((g.queues||[]).join(', '))}</small><small>${esc((g.actions||[]).join(', '))}</small></div>`).join('')||t('هنوز دسترسی خاصی تعریف نشده.','No supervisor grants yet.');
 }
 if($('pg-user')){
 $('policy-supervisor-save').onclick=async()=>{
  try{const user=$('pg-user').value.trim(),queues=$('pg-queues').value.split(',').map(x=>x.trim()).filter(Boolean),actions=[...$('pg-actions').selectedOptions].map(x=>x.value);
   if(!user||!queues.length||!actions.length)throw Error('missing_grant_fields');
   for(const q of policyAvailable)policyState.queues[q]??=defaultPolicy();
   policyState.supervisors[user]={queues,actions};await savePolicyState();renderSupervisorGrants();$('policy-feedback').textContent=t('دسترسی صف و عملیات برای کاربر ثبت شد.','Queue/action grants saved.');renderAccountList();
  }catch(error){$('policy-feedback').textContent=t('خطا: ','Error: ')+error.message;}
 };
 $('policy-supervisor-remove').onclick=async()=>{
  const user=$('pg-user').value.trim();if(!user||!policyState.supervisors[user])return;
  delete policyState.supervisors[user];try{await savePolicyState();renderSupervisorGrants();}catch(error){$('policy-feedback').textContent=error.message;}
 };
 } // admin-only grant editor
 function showQueueSummary(queueName){
  const q=queues[queueName];if(!q)return;
  const members=Object.values(q.members||{}),entries=Object.values(q.entries||{}),count={ready:0,busy:0,paused:0,offline:0};
  members.forEach(m=>count[status(m)]++);
  const metrics=[
   [t('تماس‌های منتظر','Waiting calls'),fmt(q.Calls)],
   [t('پاسخ‌داده‌شده','Answered'),fmt(q.Completed)],
   [t('رهاشده','Abandoned'),fmt(q.Abandoned)],
   [t('سطح خدمت','Service level'),n(q.Completed)>0&&String(q.ServicelevelPerf??'').trim()!==''?fmt(q.ServicelevelPerf)+'%':'—'],
   [t('میانگین انتظار','Average hold'),queueMean(q,'Holdtime')],
   [t('میانگین مکالمه','Average talk'),queueMean(q,'TalkTime')],
   [t('آماده / کل اعضا','Ready / memberships'),fmt(count.ready)+' / '+fmt(members.length)],
   [t('مشغول / Pause','Busy / paused'),fmt(count.busy)+' / '+fmt(count.paused)],
   [t('تعداد اعضای Pause','Paused members'),fmt(count.paused)],
   [t('طولانی‌ترین انتظار','Longest wait'),entries.length?duration(Math.max(...entries.map(e=>n(e.Wait)))):'—']
  ];
  $('qs-title').textContent=t('خلاصه صف ','Queue overview ')+queueName;
  $('qs-metrics').innerHTML=metrics.map(([k,v],idx)=>`<div class="summary-metric summary-metric--${idx}"><small>${esc(k)}</small><b>${esc(v)}</b>${idx===3&&v!=='—'?`<span class="summary-progress"><i style="width:${Math.max(0,Math.min(100,n(q.ServicelevelPerf)))}%"></i></span>`:''}</div>`).join('');
  $('qs-foot').textContent=t('میانگین انتظار از Holdtime برای تماس‌های پاسخ‌داده‌شده است، نه زمان انتظار لحظه‌ای. SL فقط درصد پاسخ‌گویی در آستانه تعیین‌شده در Asterisk است'+(q.ServiceLevelSeconds?' ('+q.ServiceLevelSeconds+' ثانیه)':'')+'. آخرین وضعیت AMI؛ گزارش تاریخی نیست.','Average hold is Asterisk Holdtime for answered calls, not live waiting. SL uses the PBX service-level target'+(q.ServiceLevelSeconds?' ('+q.ServiceLevelSeconds+'s)':'')+'.');
  $('queue-summary-dialog').showModal();
 }
 $('qs-close').onclick=()=>$('queue-summary-dialog').close();
 document.addEventListener('click',event=>{const b=event.target.closest('[data-queue-summary]');if(b)showQueueSummary(b.dataset.queueSummary);});
function clock(){$('clock').textContent=new Intl.DateTimeFormat(fa?'fa-IR-u-ca-persian':'en-GB',{dateStyle:'medium',timeStyle:'short'}).format(new Date());if(lastSuccess&&Date.now()-lastSuccess>Math.max(20000,cfg.interval*3)){$('connection').className='badge pending';$('connection').textContent=t('داده‌ها قدیمی است','Data is stale');currentDataSource='stale';cfg.test_controls_enabled=false;document.body.dataset.connection='stale';updateControlBadge();}}
 clock();setInterval(clock,10000);loadAmiSettings();loadPolicyEditor();updateControlBadge();setInterval(updateControlBadge,15000);refresh();
})();
