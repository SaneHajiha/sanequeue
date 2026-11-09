(()=>{'use strict';
 const $=id=>document.getElementById(id),panel=$('unit-access-panel');if(!panel)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b,out=$('unit-admin-feedback');let inventory=null,busy=false,updateWorkflow=()=>{};
 panel.querySelectorAll('input[type="date"]').forEach(input=>window.SaneQueueDates?.enhance(input));
 const text=(tag,value)=>{const e=document.createElement(tag);e.textContent=value??'—';return e;};
 const getConfig=()=>{try{return JSON.parse($('ops-config').textContent);}catch{return {};}};
 async function request(method,body){const options={method,credentials:'same-origin',headers:{}};if(body){options.headers['Content-Type']='application/json';options.headers['X-CSRF-Token']=getConfig().csrf||'';options.body=JSON.stringify(body);}
  const r=await fetch('/api/organization/access',options);if(!r.ok)throw Error(String(r.status));return r.json();}
 function render(data){inventory=data;const units=data.units||[],names=new Map(units.map(u=>[u.id,u.name]));
  panel.querySelectorAll('.unit-select,.unit-parent-select').forEach(select=>{const previous=select.value;select.replaceChildren();
   if(select.classList.contains('unit-parent-select'))select.append(new Option(t('بدون والد','No parent'),''));
   if(select.form?.id==='unit-access-workflow'&&select.name==='unit_id')select.append(new Option(t('انتخاب واحد','Choose a unit'),''));
   for(const u of units){const label=(u.parent?(names.get(u.parent)||'')+' / ':'')+u.name;const option=new Option(label,u.id);option.dataset.kind=u.kind;select.append(option);}if([...select.options].some(o=>o.value===previous))select.value=previous;});
  const host=$('unit-admin-list'),fragment=document.createDocumentFragment();fragment.append(text('h3',t('مجوزهای فعال','Active permissions')));
  const list=document.createElement('ul');for(const g of (data.grants||[]).filter(g=>g.active)){const li=document.createElement('li');
   li.append(text('span',`${g.username} · ${names.get(g.unit_id)||'—'} · ${g.capability}${g.descendants?' +':''} `));
   const button=text('button',t('لغو','Revoke'));button.type='button';button.addEventListener('click',()=>mutate({operation:'revoke',id:g.id}));li.append(button);list.append(li);}
  if(!list.children.length)list.append(text('li',t('مجوزی ثبت نشده است.','No grants configured.')));fragment.append(list);
  const open=$('unit-open-interval');open.replaceChildren();for(const [list,membership] of [[data.assignments||[],false],[data.members||[],true]])for(const item of list.filter(x=>x.ends==null)){const option=new Option((membership?t('عضویت','Membership'):t('داخلی','Extension'))+' · '+(item.username||item.endpoint)+' · '+(names.get(item.unit_id)||'—'),item.id);option.dataset.membership=String(membership);open.append(option);}
  const openQueue=$('unit-open-queue');openQueue.replaceChildren();for(const item of (data.queue_assignments||[]).filter(x=>x.ends==null))openQueue.append(new Option(item.queue+' · '+(names.get(item.unit_id)||'—'),item.id));
  fragment.append(text('h3',t('انتساب‌های داخلی','Extension assignments')));const assignments=document.createElement('ul');
  for(const a of data.assignments||[]){const li=text('li',`${names.get(a.unit_id)||'—'} · ${a.endpoint} · ${new Date(a.starts*1000).toLocaleDateString(fa?'fa-IR':'en-GB')} — ${a.ends?new Date((a.ends-1)*1000).toLocaleDateString(fa?'fa-IR':'en-GB'):t('باز','Open')}`);assignments.append(li);}
  if(!assignments.children.length)assignments.append(text('li',t('انتسابی ثبت نشده است.','No assignments configured.')));fragment.append(assignments);
  fragment.append(text('h3',t('انتساب‌های صف','Queue assignments')));const queues=document.createElement('ul');for(const a of data.queue_assignments||[])queues.append(text('li',`${names.get(a.unit_id)||'—'} · ${a.queue} · ${new Date(a.starts*1000).toLocaleDateString(fa?'fa-IR':'en-GB')} — ${a.ends?new Date((a.ends-1)*1000).toLocaleDateString(fa?'fa-IR':'en-GB'):t('باز','Open')}`));if(!queues.children.length)queues.append(text('li',t('انتساب صفی ثبت نشده است.','No queue assignments configured.')));fragment.append(queues);host.replaceChildren(fragment);
 }
 async function refresh(){try{render(await request('GET'));updateWorkflow();out.textContent='';}catch{out.textContent=t('ساختار در دسترس نیست؛ مجوز مدیریت و گزارش سراسری لازم است.','Structure unavailable; global management and reporting permissions are required.');}}
 async function mutate(body){if(busy)return;busy=true;try{await request('POST',body);await refresh();out.textContent=t('تغییر ثبت شد.','Change saved.');}catch{out.textContent=t('ثبت انجام نشد؛ مقادیر، تداخل تاریخ و دسترسی را بررسی کنید.','Could not save; check values, date overlap and permissions.');}finally{busy=false;}}
 $('unit-admin-refresh').addEventListener('click',refresh);
 const workflow=$('unit-access-workflow');
 if(workflow){
  const fields=workflow.elements,feedback=$('unit-workflow-feedback'),save=workflow.querySelector('button[type=submit]');
  const newFields=workflow.querySelector('[data-workflow-new]');
  const updateMode=()=>{
   const creating=fields.target_mode.value==='new';
   workflow.querySelector('[data-workflow-existing]').hidden=creating;
   fields.unit_id.disabled=creating;
   newFields.hidden=!creating;
   fields.unit_name.disabled=fields.unit_kind.disabled=!creating;
   fields.parent.disabled=!creating||fields.unit_kind.value==='organization';
   const kinds=['organization','department','unit','subunit'];
   const expected=kinds[kinds.indexOf(fields.unit_kind.value)-1];
   for(const option of fields.parent.options)option.hidden=Boolean(option.value)&&option.dataset.kind!==expected;
   if(fields.parent.selectedOptions[0]?.hidden)fields.parent.value='';
   fields.parent.required=creating&&Boolean(expected);
  };
  const resolveExtension=value=>{
   const digits=value.replace(/[۰-۹]/g,char=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(char)))
    .replace(/[٠-٩]/g,char=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(char)));
   if(!/^\d+$/.test(digits))return value;
   const matches=[...($('unit-recording-endpoints')?.options||[])].map(option=>option.value)
    .filter(endpoint=>endpoint.split('/')[1]===digits);
   if(matches.length!==1)throw Error(t('برای این شماره یک داخلی قطعی پیدا نشد. گزینهٔ درست را از فهرست انتخاب کنید.','This number does not resolve uniquely. Select its exact extension from the list.'));
   return matches[0];
  };
  fields.target_mode.addEventListener('change',updateMode);
  fields.unit_kind.addEventListener('change',updateMode);
  updateWorkflow=updateMode;
  workflow.addEventListener('change',event=>{
   if(event.target.name==='capability'&&event.target.checked&&['recording_play','recording_download'].includes(event.target.value))
    workflow.querySelector('[name=capability][value=call_details]').checked=true;
  });
  let requested=false;
  const autoLoad=()=>{
   if(document.body.dataset.view==='users'&&!requested){
    requested=true;
    refresh().finally(updateMode);
   }
  };
  new MutationObserver(autoLoad).observe(document.body,{attributes:true,attributeFilter:['data-view']});
  autoLoad();
  workflow.addEventListener('submit',async event=>{
   event.preventDefault();
   if(busy)return;
   const capabilities=[...workflow.querySelectorAll('[name=capability]:checked')].map(input=>input.value);
   if(!capabilities.length){feedback.textContent=t('دست‌کم یک مجوز انتخاب کنید.','Select at least one permission.');return;}
   const creating=fields.target_mode.value==='new';
   let endpoint=fields.endpoint.value.trim()||null;
   try{if(endpoint)endpoint=resolveExtension(endpoint);}
   catch(error){feedback.textContent=error.message;return;}
   busy=true;save.disabled=true;
   try{
    const result=await request('POST',{operation:'configure_access',username:fields.username.value,
     unit_id:creating?null:fields.unit_id.value,new_unit:creating?{name:fields.unit_name.value,kind:fields.unit_kind.value,parent:fields.parent.disabled?null:fields.parent.value||null}:null,
     endpoint,queue:fields.queue.value.trim()||null,start_date:fields.start.value,end_date:fields.end.value||null,
     capabilities,descendants:fields.descendants.checked});
    await refresh();
    fields.target_mode.value='existing';
    fields.unit_id.value=result.id;
    fields.endpoint.value=fields.queue.value='';
    updateMode();
    feedback.textContent=t('عضویت، انتساب و مجوزهای انتخاب‌شده ثبت شدند.','Selected membership, assignments and permissions were saved.');
   }catch(error){
    feedback.textContent=error.message==='409'?t('این انتساب یا عضویت با بازهٔ موجود تداخل دارد؛ بازه یا واحد را بررسی کنید.','The assignment or membership overlaps an existing interval. Check the unit and dates.'):
     t('ثبت انجام نشد. کاربر، واحد و تاریخ را بررسی کنید.','Access was not saved. Check the account, unit and dates.');
   }finally{busy=false;save.disabled=false;}
  });
  updateMode();
 }
 $('unit-change-refresh').addEventListener('click',async()=>{const feedback=$('unit-change-feedback'),host=$('unit-change-list');feedback.textContent=t('در حال دریافت…','Loading…');host.replaceChildren();try{const r=await fetch('/api/organization/access/changes',{credentials:'same-origin'});if(!r.ok||r.redirected)throw Error();const data=await r.json(),table=document.createElement('table'),head=document.createElement('thead'),tr=document.createElement('tr');for(const value of [t('زمان','Time'),t('مدیر','Administrator'),t('عملیات','Operation'),t('واحد و مورد','Unit and subject'),t('شناسهٔ مورد','Target ID')]){const th=text('th',value);th.scope='col';tr.append(th);}head.append(tr);table.append(head);const body=document.createElement('tbody'),labels={create:t('ساخت واحد','Create unit'),assign:t('انتساب داخلی','Assign extension'),assign_queue:t('انتساب صف','Assign queue'),close_queue:t('پایان انتساب صف','End queue assignment'),member:t('عضویت','Membership'),grant:t('اعطای مجوز','Grant'),revoke:t('لغو مجوز','Revoke'),close:t('بستن بازه','Close interval')};for(const row of data.rows){const line=document.createElement('tr');for(const value of [new Date(row.at*1000).toLocaleString(fa?'fa-IR':'en-GB'),row.actor,labels[row.operation]||row.operation,[row.unit_name,row.subject,row.endpoint,row.queue,row.capability].filter(Boolean).join(' · ')||'—',row.target])line.append(text('td',value));body.append(line);}table.append(body);host.append(table);feedback.textContent=data.rows.length?'':t('تغییری ثبت نشده است.','No changes recorded.');}catch{feedback.textContent=t('تاریخچه در دسترس نیست.','History unavailable.');}});
 $('unit-create-form').addEventListener('submit',event=>{event.preventDefault();const f=event.currentTarget;mutate({operation:'create',name:f.elements.name.value,kind:f.elements.kind.value,parent:f.elements.parent.value||null});});
 $('unit-queue-assign-form').addEventListener('submit',event=>{event.preventDefault();const f=event.currentTarget;mutate({operation:'assign_queue',unit_id:f.elements.unit_id.value,queue:f.elements.queue.value.trim(),start_date:f.elements.start.value,end_date:f.elements.end.value||null});});
 $('unit-queue-close-form').addEventListener('submit',event=>{event.preventDefault();const f=event.currentTarget;if(f.elements.id.value)mutate({operation:'close_queue',id:f.elements.id.value,end_date:f.elements.end.value});});
 for(const id of ['unit-assign-form','unit-member-form'])$(id).addEventListener('submit',event=>{event.preventDefault();const f=event.currentTarget;
  try{const body={operation:id==='unit-assign-form'?'assign':'member',unit_id:f.elements.unit_id.value,start_date:f.elements.start.value,end_date:f.elements.end.value||null};
   if(body.operation==='assign')body.endpoint=f.elements.endpoint.value.trim();else body.username=f.elements.username.value.trim();mutate(body);
  }catch{out.textContent=t('تاریخ معتبر وارد کنید.','Enter a valid date.');}});
 $('unit-grant-form').addEventListener('submit',event=>{event.preventDefault();const f=event.currentTarget;mutate({operation:'grant',unit_id:f.elements.unit_id.value,username:f.elements.username.value.trim(),capability:f.elements.capability.value,descendants:f.elements.descendants.checked});});
 $('unit-close-form').addEventListener('submit',event=>{event.preventDefault();const f=event.currentTarget,select=$('unit-open-interval');if(!select.selectedOptions.length)return;mutate({operation:'close',id:select.value,end_date:f.elements.end.value,membership:select.selectedOptions[0].dataset.membership==='true'});});
})();
