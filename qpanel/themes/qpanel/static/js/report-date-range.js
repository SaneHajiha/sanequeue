/* Explicit date presets; ISO fields remain the single request contract. */
(()=>{'use strict';const bound=new WeakSet();
function bind(form,from,to){if(!form||!from||!to||bound.has(form)||!window.SaneQueueDates)return;bound.add(form);
 const dates=window.SaneQueueDates,fa=document.documentElement.lang==='fa',t=(a,b)=>fa?a:b;
 const bar=document.createElement('div');bar.className='sq-range-presets';bar.setAttribute('role','group');bar.setAttribute('aria-label',t('بازه‌های آماده','Date presets'));
 const status=document.createElement('p');status.className='sq-range-summary';status.setAttribute('role','status');
 const add=(iso,days)=>{const d=dates.parseISO(iso);if(!d)return null;d.setUTCDate(d.getUTCDate()+days);return d.toISOString().slice(0,10);};
 const presets=[['today',t('امروز','Today')],['yesterday',t('دیروز','Yesterday')],['week',t('۷ روز اخیر','Last 7 days')],['month',t('۳۰ روز اخیر','Last 30 days')],['calendar',t('این ماه شمسی','This month')]];
 const extraPresets=[['current-week',t('هفتهٔ جاری','Current week')],['previous-week',t('هفتهٔ گذشته','Previous week')],['quarter',t('سه ماه گذشته','Last three months')],['previous',t('ماه شمسی قبل','Previous month')]];
 function update(){const a=dates.parseISO(from.value),b=dates.parseISO(to.value),days=a&&b?Math.round((b-a)/86400000)+1:0;
  const message=!a||!b?t('تاریخ آغاز و پایان را انتخاب کنید.','Choose both dates.'):days<1?t('تاریخ پایان باید پس از آغاز یا برابر آن باشد.','End date must be on or after the start.'):days>366?t('بازهٔ گزارش حداکثر ۳۶۶ روز است.','Reports may cover at most 366 days.'):'';
  to.setCustomValidity(!a||!b?'':message);status.textContent=message||t('بازهٔ انتخاب‌شده: ','Selected period: ')+dates.formatISO(from.value)+' '+t('تا','to')+' '+dates.formatISO(to.value)+' · '+new Intl.NumberFormat(fa?'fa-IR':'en').format(days)+' '+t('روز','days');
  status.classList.toggle('is-error',!!message);for(const input of [from,to])dates.enhance(input)?.sync();
 }
 function select(key){const today=dates.todayISO();let first=today,last=today;
  if(key==='yesterday')first=last=add(today,-1);if(key==='week')first=add(today,-6);if(key==='month')first=add(today,-29);
  if(key==='current-week'||key==='previous-week'){const day=dates.parseISO(today).getUTCDay(),offset=(day+(fa?1:6))%7;first=add(today,-offset-(key==='previous-week'?7:0));if(key==='previous-week')last=add(today,-offset-1);}
  if(key==='quarter')first=dates.moveDateMonth(today,-3,fa);
  if(key==='calendar'){const days=dates.monthDays(today,fa);first=days[0];}
  if(key==='previous'){const previous=dates.moveMonth(today,-1,fa),days=previous?dates.monthDays(previous,fa):[];first=days[0];last=days.at(-1);}
  if(!first||!last)return;from.value=first;to.value=last;for(const input of [from,to]){input.dispatchEvent(new Event('input',{bubbles:true}));input.dispatchEvent(new Event('change',{bubbles:true}));}update();
  for(const button of bar.querySelectorAll('button'))button.setAttribute('aria-pressed',String(button.dataset.preset===key));more.value=extraPresets.some(preset=>preset[0]===key)?key:'';
 }
 for(const [key,label] of presets){const button=document.createElement('button');button.type='button';button.textContent=label;button.dataset.preset=key;button.setAttribute('aria-pressed','false');button.onclick=()=>select(key);bar.append(button);}
 const more=document.createElement('select'),moreLabel=t('بازه‌های بیشتر','More ranges');more.className='sq-range-more';more.setAttribute('aria-label',moreLabel);const placeholder=document.createElement('option');placeholder.value='';placeholder.textContent=moreLabel;more.append(placeholder);for(const [key,label] of extraPresets){const option=document.createElement('option');option.value=key;option.textContent=label;more.append(option);}more.addEventListener('change',()=>{if(more.value)select(more.value);});bar.append(more);
 const start=document.createElement('span');start.className='sq-range-caption';start.textContent=t('انتخاب سریع بازه','Quick date range');bar.prepend(start);form.prepend(bar);form.append(status);
 for(const input of [from,to]){dates.enhance(input);for(const event of ['input','change'])input.addEventListener(event,()=>{for(const button of bar.querySelectorAll('button'))button.setAttribute('aria-pressed','false');more.value='';update();});}form.addEventListener('reset',()=>setTimeout(()=>{more.value='';update();},0));update();if(from.value===dates.todayISO()&&to.value===from.value)bar.querySelector('[data-preset="today"]')?.setAttribute('aria-pressed','true');
}
window.SaneQueueReportDates=Object.freeze({bind});})();
