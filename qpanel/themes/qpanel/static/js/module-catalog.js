'use strict';
(function(global){
 const escape=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const normalize=value=>String(value??'').normalize('NFKC').replace(/ي/g,'ی').replace(/ك/g,'ک').toLowerCase();
 function select(items,{query='',group='',state='',pilot=false}={}){
  const q=normalize(query).trim();
  return items.filter(m=>(!group||m.group===group)&&(!state||(m.implementation||m.state)===state)&&(!pilot||m.pilot)&&(!q||normalize([m.id,m.fa,m.en,m.note.fa,m.note.en,...m.features.flatMap(f=>[f.fa,f.en])].join(' ')).includes(q)));
 }
 function mount(root,catalog,{fa=true}={}){
  const t=(a,b)=>fa?a:b,lang=fa?'fa':'en';
  if(!catalog||!Array.isArray(catalog.modules)){root.textContent=t('فهرست قابلیت‌ها در دسترس نیست.','The module catalog is unavailable.');return;}
  const stateLabel=s=>s==='planned'?t('برنامهٔ توسعه','Planned'):s==='partial'?t('بخشی پیاده‌شده','Partially built'):t('کد موجود؛ نیازمند پذیرش','Built; acceptance pending');
  root.innerHTML=`<div class="catalog-filters"><label>${t('جستجوی ماژول یا قابلیت','Find a module or capability')}<input type="search" data-catalog-query maxlength="100"></label><label>${t('گروه','Group')}<select data-catalog-group><option value="">${t('همهٔ گروه‌ها','All groups')}</option>${catalog.groups.map(g=>`<option value="${escape(g.id)}">${escape(g[lang])}</option>`).join('')}</select></label><label>${t('وضعیت توسعه','Development state')}<select data-catalog-state><option value="">${t('همهٔ وضعیت‌ها','All states')}</option><option value="built">${stateLabel('built')}</option><option value="partial">${stateLabel('partial')}</option><option value="planned">${stateLabel('planned')}</option></select></label><label class="catalog-check"><input type="checkbox" data-catalog-pilot>${t('فقط محدودهٔ پایلوت فعلی','Current pilot scope only')}</label></div><p class="catalog-count" role="status" aria-live="polite"></p><div data-catalog-results></div>`;
  const results=root.querySelector('[data-catalog-results]');
  function render(){
   const items=select(catalog.modules,{query:root.querySelector('[data-catalog-query]').value,group:root.querySelector('[data-catalog-group]').value,state:root.querySelector('[data-catalog-state]').value,pilot:root.querySelector('[data-catalog-pilot]').checked});
   root.querySelector('.catalog-count').textContent=t(`${items.length} ماژول از ${catalog.modules.length} · وضعیت کد با فعال‌بودن روی این سرور متفاوت است.`,`${items.length} of ${catalog.modules.length} modules · Code status does not mean enabled on this host.`);
   results.innerHTML=items.length?catalog.groups.map(group=>{const rows=items.filter(m=>m.group===group.id);if(!rows.length)return '';return `<section class="catalog-group" aria-labelledby="catalog-${escape(group.id)}"><h3 id="catalog-${escape(group.id)}">${escape(group[lang])}</h3><div class="feature-catalog">${rows.map(m=>`<article class="cap-card catalog-module" data-module-id="${escape(m.id)}"><div><h4>${escape(m[lang])}</h4><p>${escape(m.note[lang])}</p></div><span class="cap-pill ${escape(m.state)}">${stateLabel(m.implementation||m.state)}</span><details><summary>${t('زیرقابلیت‌ها و مرز پذیرش','Capabilities and acceptance boundary')} (${m.features.length})</summary><ul>${m.features.map(f=>`<li><span>${escape(f[lang])}</span><span class="catalog-feature-state">${stateLabel(f.state)}</span></li>`).join('')}</ul><p class="catalog-boundary">${escape(m.acceptance[lang])}</p>${m.pilot?`<p>${t('در محدودهٔ پایلوت؛ تأیید محیط واقعی هنوز لازم است.','In pilot scope; real-environment acceptance is still required.')}</p>`:''}</details></article>`).join('')}</div></section>`;}).join(''):`<p class="empty">${t('ماژولی با این فیلتر پیدا نشد.','No modules match these filters.')}</p>`;
  }
  root.querySelectorAll('input,select').forEach(control=>control.addEventListener(control.type==='search'?'input':'change',render));render();
 }
 global.SaneQueueCatalog={mount,select};
 if(typeof module!=='undefined')module.exports={select};
})(typeof window==='undefined'?globalThis:window);
