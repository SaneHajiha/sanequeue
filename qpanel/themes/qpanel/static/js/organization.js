/* Organization identity and reversible monitoring maintenance controls. */
(()=>{'use strict';
 const config=JSON.parse(document.getElementById('ops-config').textContent);
 const form=document.getElementById('organization-form');
 if(!form)return;
 const fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b;
 const feedback=document.getElementById('organization-feedback');
 const moduleStatus=document.getElementById('module-status');
 async function api(path,options={}){
  const response=await fetch(path,{credentials:'same-origin',...options,headers:{'X-CSRF-Token':config.csrf,...options.headers}});
  if(response.redirected||!response.headers.get('content-type')?.includes('application/json'))throw new Error('login_required');
  const value=await response.json();if(!response.ok)throw new Error(value.error||'request_failed');return value;
 }
 function moduleState(value){
  moduleStatus.textContent=value.enabled?t('مانیتورینگ فعال است','Monitoring enabled'):t('مانیتورینگ غیرفعال است؛ تماس‌های مرکز تلفن ادامه دارند','Monitoring disabled; PBX calls continue');
  document.getElementById('module-disable').disabled=!value.enabled;
  document.getElementById('module-enable').disabled=value.enabled;
 }
 async function load(){
  try{
   const [organization,module]=await Promise.all([api('/api/organization'),api('/api/module')]);
   if(!form.dataset.loaded){form.elements.name.value=organization.name;form.elements.subtitle.value=organization.subtitle;form.dataset.loaded='true';}
   moduleState(module);
  }catch(error){feedback.textContent=t('دریافت تنظیمات ممکن نشد؛ نشست و مجوز تنظیمات را بررسی کنید.','Unable to load settings; check your session and settings permission.');}
 }
 form.addEventListener('submit',async event=>{
  event.preventDefault();const button=form.querySelector('[type=submit]');button.disabled=true;
  try{
   const body=new FormData(form);body.set('remove_logo',form.elements.remove_logo.checked?'true':'false');
   const value=await api('/api/organization',{method:'POST',body});
   document.querySelectorAll('[data-organization-name]').forEach(node=>node.textContent=value.name);
   document.querySelectorAll('[data-organization-subtitle]').forEach(node=>node.textContent=value.subtitle);
   document.querySelectorAll('[data-organization-logo]').forEach(node=>{node.hidden=!value.logo_url;if(value.logo_url)node.src=value.logo_url+'?v='+value.updated_at;});
   document.querySelectorAll('[data-organization-mark]').forEach(node=>node.hidden=Boolean(value.logo_url));
   form.elements.logo.value='';form.elements.remove_logo.checked=false;
   feedback.textContent=t('هویت سازمان ذخیره شد؛ صفحهٔ ورود هم همین تنظیمات را نمایش می‌دهد.','Organization saved; the sign-in page uses the same identity.');
  }catch(error){feedback.textContent=t('ذخیره انجام نشد؛ قالب واقعی فایل و نام را بررسی کنید.  نام و تصویر PNG/JPEG/WebP/AVIF حداکثر ۵۱۲ کیلوبایت را بررسی کنید.','Save failed; check the name and PNG/JPEG/WebP/AVIF image up to 512 KB.');}
  finally{button.disabled=false;}
 });
 for(const enabled of [false,true])document.getElementById(enabled?'module-enable':'module-disable').addEventListener('click',async()=>{
  try{
   const value=await api('/api/module',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({enabled})});moduleState(value);
  }catch(error){moduleStatus.textContent=t('تغییر وضعیت انجام نشد؛ از فرمان اضطراری روی سرور استفاده کنید.','State change failed; use the server emergency command.');}
 });
 document.querySelector('nav button[data-view="settings"]')?.addEventListener('click',load);
})();
