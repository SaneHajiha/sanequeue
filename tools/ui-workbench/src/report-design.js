import './tokens.css';
import './style.css';
import './report-design.css';
import '../../../qpanel/themes/qpanel/static/css/report-charts.css';
import '../../../qpanel/themes/qpanel/static/css/date-picker.css';
import '../../../qpanel/themes/qpanel/static/css/report-date-range.css';

export async function mountReportDesign({locale='fa',theme='light',target=null}={}){
 const fa=locale==='fa',t=(a,b)=>fa?a:b,el=(tag,text,cls)=>{const node=document.createElement(tag);if(text!==undefined)node.textContent=text;if(cls)node.className=cls;return node;};
 document.documentElement.lang=locale;document.documentElement.dir=fa?'rtl':'ltr';document.documentElement.dataset.theme=theme;document.body.classList.add('sq-report-design-body');document.body.dataset.view='reports';
 const root=el('main',undefined,'sq-workbench sq-report-design');root.dataset.theme=theme;root.dir=fa?'rtl':'ltr';root.lang=locale;
 for(const name of ['ink','bg','card','line','accent','muted','soft','danger'])document.documentElement.style.setProperty('--'+name,'var(--sq-'+name+')');
 const header=el('header'),eyebrow=el('p','SaneQueue · '+t('گزارش‌ها و تحلیل','Reports & analytics'),'sq-design-eyebrow');header.append(eyebrow,el('h1',t('از داده تا تصمیم روشن','A clearer view of performance')),el('p',t('نمونهٔ طراحی با دادهٔ ساختگی؛ به سرور تماس متصل نیست.','Synthetic design fixture. No connection to the PBX.'),'sq-muted'));
 const toolbar=el('div',undefined,'sq-design-toolbar'),toggle=el('button',t('تغییر تم','Toggle theme'),'sq-button');toggle.type='button';toggle.onclick=()=>{theme=theme==='light'?'dark':'light';root.dataset.theme=theme;document.documentElement.dataset.theme=theme;document.body.classList.toggle('dark',theme==='dark');};
 const language=el('a',fa?'English':'فارسی','sq-button');language.href='?view=report-design&locale='+(fa?'en':'fa')+'&theme='+theme;toolbar.append(toggle,language);header.append(toolbar);root.append(header);
 const form=el('form',undefined,'sq-design-filters');form.id='history-filters';
 for(const [name,label,value] of [['from',t('از تاریخ','From date'),'2026-09-01'],['to',t('تا تاریخ؛ شامل این روز','Through date, inclusive'),'2026-09-30']]){const wrap=el('label',label),input=el('input');input.name=name;input.type='date';input.required=true;input.value=value;wrap.append(input);form.append(wrap);}
 const queueLabel=el('label',t('صف','Queue')),queue=el('select');queue.name='queue';for(const [value,label] of [['',t('همهٔ صف‌های مجاز','All authorised queues')],['8001',t('۸۰۰۱ · فروش','8001 · Sales')],['8002',t('۸۰۰۲ · پشتیبانی','8002 · Support')]]){const option=el('option',label);option.value=value;queue.append(option);}queueLabel.append(queue);form.append(queueLabel);
 const run=el('button',t('نمایش گزارش','Run report'),'sq-button sq-design-primary');run.type='submit';form.append(run);root.append(form);
 const kpis=el('section',undefined,'sq-design-kpis');kpis.setAttribute('aria-label',t('خلاصهٔ همین بازه','Selected-period summary'));root.append(kpis);
 const feedback=el('p',undefined,'sq-muted');feedback.setAttribute('role','status');root.append(feedback);
 const trend=el('div');trend.id='design-trend';root.append(trend);const grid=el('section',undefined,'sq-design-chart-grid'),queues=el('div'),sla=el('div');queues.id='design-queues';sla.id='design-sla';grid.append(queues,sla);root.append(grid);
 (target||document.querySelector('#app')).append(root);
 await import('../../../qpanel/themes/qpanel/static/js/date-picker.js');await import('../../../qpanel/themes/qpanel/static/js/report-periods.js');await import('../../../qpanel/themes/qpanel/static/js/report-date-range.js');await import('../../../qpanel/themes/qpanel/static/js/report-charts.js');
 window.SaneQueueReportDates.bind(form,form.elements.from,form.elements.to);
 function render(){const first=new Date(form.elements.from.value+'T12:00:00Z'),last=new Date(form.elements.to.value+'T12:00:00Z'),days=Math.round((last-first)/86400000)+1;if(!form.reportValidity()||days<1||days>366)return;
  const rows=[];for(let i=0;i<days;i++){if(i===8)continue;const date=new Date(first.getTime()+i*86400000).toISOString().slice(0,10);rows.push({bucket:date,answered:i===13?null:480+(i*83)%380,abandoned:18+(i*11)%67});}
  const answered=rows.reduce((sum,row)=>sum+(row.answered??0),0),abandoned=rows.reduce((sum,row)=>sum+row.abandoned,0),nf=new Intl.NumberFormat(fa?'fa-IR':'en',{maximumFractionDigits:1});kpis.replaceChildren();
  for(const [label,value,note] of [[t('پاسخ‌های معلوم','Known answers'),answered,t('مراجعهٔ صف؛ نه مشتری یکتا','Queue visits, not unique customers')],[t('رهاشده','Abandoned'),abandoned,t('همان بازه و صف‌های منتخب','Same period and selected queues')],[t('سطح خدمت نمونه','Sample service level'),'91.6%',t('پاسخ تا ۲۰ ثانیه / انتظار معلوم','Answered within 20s / known wait')],[t('میانگین انتظار نمونه','Sample average wait'),'00:28',t('فقط مقادیر معلوم','Known values only')]]){const card=el('article',undefined,'sq-design-kpi');card.append(el('span',label),el('strong',typeof value==='number'?nf.format(value):value),el('small',note));kpis.append(card);}
  const subtitle=window.SaneQueueReportPeriods.period(form.elements.from.value,form.elements.to.value)+' · '+t('تهران · دادهٔ ساختگی','Tehran · Synthetic data');
  window.SaneQueueReportCharts.render(trend,{title:t('روند پاسخ و رهاشدن','Answered and abandoned trends'),subtitle,unit:t('مراجعهٔ صف','Queue visits'),...window.SaneQueueReportPeriods.trend(rows,'day'),series:[{label:t('پاسخ‌داده','Answered'),values:rows.map(row=>row.answered)},{label:t('رهاشده','Abandoned'),values:rows.map(row=>row.abandoned)}]});
  window.SaneQueueReportCharts.render(queues,{title:t('انتظار در صف‌ها','Queue waiting time'),subtitle,unit:t('ثانیه','Seconds'),labels:[t('۸۰۰۱ · فروش','8001 · Sales'),t('۸۰۰۲ · پشتیبانی','8002 · Support'),t('۸۰۰۳ · امور مشتریان','8003 · Customer care'),t('۸۰۰۴ · مالی','8004 · Finance')],series:[{label:t('میانگین پاسخ','Answered mean'),values:[42,83,null,28]},{label:t('صدک ۹۰','90th percentile'),values:[96,160,null,65]}]});
  window.SaneQueueReportCharts.render(sla,{title:t('مقایسهٔ سطح خدمت','Service level by queue'),subtitle,unit:t('درصد','Percent'),maximum:100,labels:['8001','8002','8003','8004'],series:[{label:t('سطح خدمت','Service level'),values:[94.2,81.6,null,98.1]}]});feedback.textContent=t('برای بازه‌های بیشتر، صفحه‌بندی نمودار را ببینید. روز غایب و مقدار نامعلوم به صفر تبدیل نشده‌اند.','Use chart paging for longer ranges. Missing periods and unknown values are not converted to zero.');
 }
 form.addEventListener('submit',event=>{event.preventDefault();render();});render();window.__reportDesignReady=true;return root;
}
