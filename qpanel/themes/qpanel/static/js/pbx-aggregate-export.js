(()=>{'use strict';
 const $=id=>document.getElementById(id),dates=$('history-filters');if(!dates)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b;
 for(const [prefix,dataset,sectionId] of [['pbx-performance','performance','history-pbx-performance-section'],['pbx-reason','reasons','history-pbx-reasons-section'],['pbx-reason-timeline','reasons-timeline','history-pbx-reasons-section']]){
  const button=$(prefix+'-export'),section=$(sectionId),feedback=$(prefix+'-feedback')||$('pbx-reason-feedback');if(!button||!section||!feedback)continue;
  const params=()=>{const p=new URLSearchParams({from:dates.elements.from.value,to:dates.elements.to.value}),form=$(dataset==='performance'?'pbx-performance-filters':'pbx-reason-filters');for(const [key,value] of new FormData(form))if(value&&(key!=='bucket'||dataset==='reasons-timeline'))p.set(key,value);return p;};
  button.addEventListener('click',async()=>{const form=$(dataset==='performance'?'pbx-performance-filters':'pbx-reason-filters');if(!dates.reportValidity()||!form.reportValidity())return;const format=$(prefix+'-export-format').value;if(!['csv','xlsx','pdf'].includes(format))return;
   let cfg={};try{cfg=JSON.parse($('ops-config').textContent);}catch{}if(!cfg.csrf){feedback.textContent=t('نشست معتبر لازم است.','A valid session is required.');return;}
   const query=params().toString();button.disabled=true;feedback.textContent=t('در حال ساخت فایل…','Preparing file…');
   try{const response=await fetch('/api/history/cdr/aggregate/'+dataset+'/export.'+format+'?'+query,{method:'POST',credentials:'same-origin',headers:{'X-CSRF-Token':cfg.csrf}});
    const mime={csv:'text/csv',xlsx:'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',pdf:'application/pdf'}[format];if(!response.ok||response.redirected||!response.headers.get('content-type')?.includes(mime))throw Error('export');
    const blob=await response.blob();if(section.hidden||document.body.dataset.view!=='reports'||params().toString()!==query)return;
    const url=URL.createObjectURL(blob),link=document.createElement('a');link.href=url;link.download='pbx-'+dataset+'.'+format;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);feedback.textContent=t('فایل آماده شد.','File is ready.');
   }catch{if(!section.hidden)feedback.textContent=t('خروجی در دسترس نیست؛ مجوز و سقف داده را بررسی کنید.','Export unavailable; check permission and data limits.');}finally{button.disabled=false;}});
 }
})();
