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
 let reportPicker=null;
 function reportSection(target='history-summary-section'){
  if(!report)return;
  const section=document.getElementById(target);
  if(!section||!section.classList.contains('history-section')||!report.contains(section))return;
  report.querySelectorAll('.history-section').forEach(item=>{item.hidden=item!==section;});
  const kpis=document.getElementById('history-kpis');
  if(kpis)kpis.hidden=target!=='history-summary-section';
  if(reportPicker)reportPicker.value=target;
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
   for(const destination of destinations){
    if(!report.querySelector('#'+destination.target))continue;
    const option=document.createElement('option');option.value=destination.target;
    option.textContent=destination.button.textContent.trim();reportPicker.append(option);
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
   if(document.body.dataset.view!==link.dataset.moduleView)button.click();
   if(link.dataset.moduleView==='reports')reportSection(link.dataset.moduleTarget);
   remember(link.dataset.moduleView,link.dataset.moduleTarget);
   nav.querySelectorAll('.module-shortcut').forEach(item=>{if(item===link)item.setAttribute('aria-current','location');else item.removeAttribute('aria-current');});
   requestAnimationFrame(()=>{
    const target=document.getElementById(link.dataset.moduleTarget);
    if(target){target.scrollIntoView({block:'start',behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});target.tabIndex=-1;target.focus({preventScroll:true});}
   });
  }
  const view=event.target.closest('button[data-view]');
  if(view){
   if(view.dataset.view==='reports')reportSection();
   activate(view.dataset.view);remember(view.dataset.view);
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
   const selector=option.dataset.target?'[data-module-target="'+option.dataset.target+'"]':'[data-view="'+option.dataset.view+'"]';
   nav.querySelector(selector)?.click();
   jump.value=option.value;
  };
 }
 const observer=new MutationObserver(()=>activate(document.body.dataset.view));
 observer.observe(document.body,{attributes:true,attributeFilter:['data-view']});
 activate(document.body.dataset.view);
 try{
  const saved=JSON.parse(sessionStorage.getItem(savedKey)||'null');
  if(saved){
   const destination=[...nav.querySelectorAll('button[data-module-view],button[data-view]')].find(button=>
    saved.target?button.dataset.moduleView===saved.view&&button.dataset.moduleTarget===saved.target:button.dataset.view===saved.view);
   destination?.click();
  }
 }catch{/* Navigation preferences never prevent access to the default view. */}
 if(title)title.setAttribute('aria-live','polite');
})();
