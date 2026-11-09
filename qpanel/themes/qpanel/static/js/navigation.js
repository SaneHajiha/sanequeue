/* Progressive enhancement: native details and existing view buttons work alone. */
'use strict';
(() => {
 const nav=document.querySelector('.module-navigation');
 if(!nav)return;
 const groups=[...nav.querySelectorAll('.nav-module')];
 const jump=document.getElementById('view-jump');
 const title=document.getElementById('view-title');
 const savedKey='sanequeue.navigation';
 const report=document.getElementById('reports-view');
 const browser=typeof window!=='undefined'&&window.history&&window.location?window:null;
 let restoring=false;
 let reportPicker=null;
 function reportSection(target='history-summary-section'){
  if(!report)return;
  const section=document.getElementById(target);
  if(!section||!section.classList.contains('history-section')||!report.contains(section))return;
  report.querySelectorAll('.history-section').forEach(item=>{item.hidden=item!==section;});
  const kpis=document.getElementById('history-kpis');
  if(kpis)kpis.hidden=target!=='history-summary-section';
  if(reportPicker)reportPicker.value=target;
  // These views either use PBX-wide filters or provide their own queue selector.
  const globalPbx=new Set(['history-cdr-section','history-pbx-performance-section','history-pbx-reasons-section','history-outbound-dashboard-section','history-builder-section','history-transcript-section','history-unit-section']);
  const filterForm=document.getElementById('history-filters');
  const filterActions=document.getElementById('history-filter-actions');
  const queueControl=document.getElementById('history-filter-queue');
  const pauseControl=document.getElementById('history-filter-pause');
  const outcomeControl=document.getElementById('history-filter-outcome');
  const extensionCard=document.getElementById('extension-report-card');
  if(filterForm)filterForm.hidden=target==='history-transcript-section';
  // These sections have their own explicit run or preview controls.
  if(filterActions)filterActions.hidden=['history-cdr-section','history-pbx-performance-section','history-pbx-reasons-section','history-outbound-dashboard-section','history-builder-section','history-unit-section'].includes(target);
  if(queueControl)queueControl.hidden=globalPbx.has(target);
  for(const id of ['history-filter-time-from','history-filter-time-to']){const field=document.getElementById(id);if(field)field.hidden=target!=='history-cdr-section';}
  if(pauseControl)pauseControl.hidden=!['history-outbound-section','history-work-section'].includes(target);
  if(outcomeControl)outcomeControl.hidden=!['history-calls-section','history-export-jobs-section'].includes(target);
  if(extensionCard)extensionCard.hidden=target!=='history-summary-section';
  const heading=document.getElementById('history-cdr-heading');if(heading)heading.hidden=target!=='history-cdr-section';
  document.body.dataset.reportTarget=target;
  if(target==='history-cdr-section'){const family=nav.querySelector('[data-report-family="contact-center"]');if(family)family.open=false;}
 }
 // One report at a time, using only the server-authorized navigation items.
 // Native links and the full report remain available when JavaScript is off.
 if(report){
  const local=report.querySelector('.history-navigation');
  if(local){
   const label=document.createElement('label');
   label.textContent=document.documentElement.lang==='fa'?'گزارش موردنظر':'Choose a report';
   reportPicker=document.createElement('select');reportPicker.id='history-section-picker';
   const overview=nav.querySelector('button[data-view="reports"]');
   const destinations=[...(overview?[{target:'history-summary-section',button:overview}]:[]),
    ...[...nav.querySelectorAll('[data-module-view="reports"]')].map(button=>({target:button.dataset.moduleTarget,button}))];
   const reportGroups=new Map(),seenTargets=new Set(),fa=document.documentElement.lang==='fa';
   for(const destination of destinations){
    if(seenTargets.has(destination.target)||!report.querySelector('#'+destination.target))continue;
    seenTargets.add(destination.target);
    const option=document.createElement('option');option.value=destination.target;
    option.textContent=destination.button.textContent.trim();
    const family=destination.button.closest('[data-report-family]')?.dataset.reportFamily||'contact-center';
    if(!reportGroups.has(family)){const group=document.createElement('optgroup');group.label=({pbx:fa?'مرکز تلفن':'PBX','contact-center':fa?'کال‌سنتر و صف':'Contact center & queues',shared:fa?'ابزارهای مشترک':'Shared tools'})[family]||family;reportGroups.set(family,group);reportPicker.append(group);}
    reportGroups.get(family).append(option);
   }
   reportPicker.addEventListener('change',()=>{
    const destination=destinations.find(item=>item.target===reportPicker.value);
    destination?.button.click();
   });
   label.append(reportPicker);local.replaceChildren(label);
  }
  reportSection();
 }
 const remember=(view,target='')=>{try{sessionStorage.setItem(savedKey,JSON.stringify({view,target}));}catch{}};
 function destination(view,target=''){
  return [...nav.querySelectorAll('button[data-module-view],button[data-view]')].find(button=>
   target?button.dataset.moduleView===view&&button.dataset.moduleTarget===target:button.dataset.view===view);
 }
 function address(view,target=''){
  if(!browser||restoring)return;
  const url=new URL(browser.location.href);
  if(url.searchParams.get('sq_view')===view&&(url.searchParams.get('sq_section')||'')===target)return;
  url.searchParams.set('sq_view',view);
  if(target)url.searchParams.set('sq_section',target);else url.searchParams.delete('sq_section');
  browser.history.pushState(null,'',url);
 }
 function restoreAddress(useDefault=false){
  if(!browser)return false;
  const url=new URL(browser.location.href);
  const params=url.searchParams;
  const view=params.get('sq_view');
  if(!view&&!useDefault)return false;
  const target=params.get('sq_section')||'';
  const button=destination(view,target)||destination(view)||destination('live');
  restoring=true;
  try{button?.click();}finally{restoring=false;}
  if(view&&button&&(view!==(button.dataset.moduleView||button.dataset.view)||target!==(button.dataset.moduleTarget||''))){
   params.set('sq_view',button.dataset.moduleView||button.dataset.view);
   if(button.dataset.moduleTarget)params.set('sq_section',button.dataset.moduleTarget);else params.delete('sq_section');
   browser.history.replaceState(null,'',url);
  }
  return true;
 }
 groups.forEach(group=>group.addEventListener('toggle',()=>{
  if(group.open)groups.forEach(other=>{if(other!==group)other.open=false;});
 }));
 function activate(view){
  const button=[...nav.querySelectorAll('button[data-view]')].find(b=>b.dataset.view===view);
  if(!button)return;
  const group=button.closest('.nav-module');
  groups.forEach(g=>{g.classList.toggle('current-module',g===group);});
  if(group)group.open=true;
  const breadcrumb=document.querySelector('.breadcrumb');
  if(breadcrumb&&group)breadcrumb.textContent=group.querySelector('summary').textContent.trim();
 }
 nav.addEventListener('click',event=>{
  const link=event.target.closest('[data-module-view]');
  if(link){
   const button=[...nav.querySelectorAll('button[data-view]')].find(b=>b.dataset.view===link.dataset.moduleView);
   if(!button)return;
   if(document.body.dataset.view!==link.dataset.moduleView){
    const wasRestoring=restoring;
    restoring=true;
    try{button.click();}finally{restoring=wasRestoring;}
   }
   if(link.dataset.moduleView==='reports')reportSection(link.dataset.moduleTarget);
   if(link.dataset.moduleView==='reports'&&title)title.textContent=link.textContent.trim();
   remember(link.dataset.moduleView,link.dataset.moduleTarget);
   address(link.dataset.moduleView,link.dataset.moduleTarget);
   nav.querySelectorAll('.module-shortcut').forEach(item=>{if(item===link)item.setAttribute('aria-current','location');else item.removeAttribute('aria-current');});
   requestAnimationFrame(()=>{
    const target=document.getElementById(link.dataset.moduleTarget);
    if(target){
     // Show the shared date and scope controls before the results.
     const isReport=link.dataset.moduleView==='reports';
     const focusTarget=isReport?(document.querySelector('.page-heading h1')||target):target;
     (isReport?(document.querySelector('.topbar')||focusTarget):focusTarget).scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});
     focusTarget.tabIndex=-1;focusTarget.focus({preventScroll:true});
    }
   });
  }
  const view=event.target.closest('button[data-view]');
  if(view){
   if(view.dataset.view==='reports')reportSection();
   activate(view.dataset.view);remember(view.dataset.view);
   address(view.dataset.view);
   nav.querySelectorAll('.module-shortcut').forEach(item=>item.removeAttribute('aria-current'));
   document.querySelector('.topbar')?.scrollIntoView({block:'start',behavior:'instant'});
  }
 });
 // Group the compact mobile selector using the same authorized DOM. Never
 // add routes a user was not granted by the server-rendered navigation.
 if(jump){
  const selected=jump.value;
  jump.replaceChildren();
  for(const group of groups){
   const options=document.createElement('optgroup');
   options.label=group.querySelector('summary').textContent.trim();
   group.querySelectorAll('button[data-view],button[data-module-view]').forEach((button,index)=>{
    const option=document.createElement('option');
    option.value=button.dataset.view||group.dataset.module+':'+index;
    option.textContent=button.textContent.replace(/—/g,'').trim();
    option.dataset.view=button.dataset.view||button.dataset.moduleView;
    if(button.dataset.moduleTarget)option.dataset.target=button.dataset.moduleTarget;
    options.append(option);
   });
   jump.append(options);
  }
  jump.value=selected;
  jump.onchange=()=>{
   const option=jump.selectedOptions[0];
   if(!option)return;
   const selector=option.dataset.target?'[data-module-target="'+option.dataset.target+'"]':'[data-view="'+option.dataset.view+'"]';
   nav.querySelector(selector)?.click();
   jump.value=option.value;
  };
 }
 const observer=new MutationObserver(()=>activate(document.body.dataset.view));
 observer.observe(document.body,{attributes:true,attributeFilter:['data-view']});
 activate(document.body.dataset.view);
 try{
  browser?.addEventListener('popstate',()=>restoreAddress(true));
  if(!restoreAddress()){
   const saved=JSON.parse(sessionStorage.getItem(savedKey)||'null');
   restoring=true;
   try{if(saved)destination(saved.view,saved.target)?.click();}finally{restoring=false;}
  }
 }catch{/* Navigation preferences never prevent access to the default view. */}
 if(title)title.setAttribute('aria-live','polite');
})();
