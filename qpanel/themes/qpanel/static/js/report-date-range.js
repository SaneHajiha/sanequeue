/* Explicit date presets; ISO fields remain the single request contract. */
(()=>{'use strict';const bound=new WeakSet();
function bind(form,from,to){if(!form||!from||!to||bound.has(form)||!window.SaneQueueDates)return;bound.add(form);
 const dates=window.SaneQueueDates,fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b;
 const bar=document.createElement('div');bar.className='sq-range-presets';bar.setAttribute('role','group');bar.setAttribute('aria-label',t('بازه‌های آماده','Date presets'));
 const status=document.createElement('p');status.className='sq-range-summary';status.setAttribute('role','status');
 const add=(iso,days)=>{const d=dates.parseISO(iso);if(!d)return null;d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10);};
 const presets=[['today',t('امروز','Today')],['yesterday',t('دیروز','Yesterday')],['week',t('۷ روز اخیر','Last 7 days')],['month',t('۳۰ روز اخیر','Last 30 days')],['calendar',t('این ماه شمسی','This month')],['previous',t('ماه شمسی قبل','Previous month')]];
 function update(){const a=dates.parseISO(from.value),b=dates.parseISO(to.value),days=a&&b?Math.round((b-a)/86400000)+1:0;
  const message=!a||!b?t('تاریخ آغاز و پایان را انتخاب کنید.','Choose both dates.'):days<1?t('تاریخ پایان باید پس از آغاز یا برابر آن باشد.','End date must be on or after the start.'):days>366?t('بازهٔ گزارش حداکثر ۳۶۶ روز است.','Reports may cover at most 366 days.'):'';
  to.setCustomValidity(!a||!b?'':message);status.textContent=message||t('بازهٔ انتخاب‌شده: ','Selected period: ')+dates.formatISO(from.value)+' '+t('تا','to')+' '+dates.formatISO(to.value)+' · '+new Intl.NumberFormat(fa?'fa-IR':'en').format(days)+' '+t('روز، ساعت تهران','days, Tehran time');
  status.classList.toggle('is-error',!!message);for(const input of [from,to])dates.enhance(input)?.sync();
 }
 function select(key){const today=dates.todayISO();let first=today,last=today;
  if(key==='yesterday')first=last=add(today,-1);if(key==='week')first=add(today,-6);if(key==='month')first=add(today,-29);
  if(key==='calendar'){const days=dates.monthDays(today,fa);first=days[0];}
  if(key==='previous'){const previous=dates.moveMonth(today,-1,fa),days=previous?dates.monthDays(previous,fa):[];first=days[0];last=days.at(-1);}
  if(!first||!last)return;from.value=first;to.value=last;for(const input of [from,to]){input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}update();
  for(const button of bar.querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.preset===key));
 }
 for(const [key,label] of presets){const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.preset=key;button.setAttribute('aria-pressed','false');button.onclick=()=>select(key);bar.append(button);}
 const start=document.createElement('span');start.className='sq-range-caption';start.textContent=t('انتخاب سریع بازه','Quick date range');bar.prepend(start);form.prepend(bar);form.append(status);
 for(const input of [from,to]){dates.enhance(input);for(const event of ['input','change'])input.addEventListener(event,()=>{for(const button of bar.querySelectorAll('button'))button.setAttribute('aria-pressed','false');update();});}form.addEventListener('reset',()=>setTimeout(update,0));update();
}
window.SaneQueueReportDates=Object.freeze({bind});})();
