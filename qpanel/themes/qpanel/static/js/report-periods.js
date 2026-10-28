/* Civil report labels: localised dates never change the backend bucket calendar. */
(()=>{'use strict';
const DAY=86400000,fa=()=>document.documentElement.lang==='fa';
function date(iso){if(typeof iso!=='string'||!/^\d{4}-\d{2}-\d{2}$/.test(iso))return null;const value=new Date(iso+'T12:00:00Z');return Number.isFinite(value.getTime())&&value.toISOString().slice(0,10)===iso?value:null;}
function display(iso){if(!date(iso))return '—';return window.SaneQueueDates?.formatISO(iso,{style:'short'})||new Intl.DateTimeFormat(fa()?'fa-IR-u-ca-persian':'en-GB',{timeZone:'UTC',dateStyle:'short'}).format(date(iso));}
function period(first,last){return display(first)+(fa()?' تا ':' – ')+display(last);}
function caption(params){const queue=params.get('queue');const extra=[...params.entries()].filter(([key,value])=>value&&!['from','to','queue','lang','limit','before','before_id','before_time'].includes(key));return period(params.get('from'),params.get('to'))+(fa()?' · تهران · صف: ':' · Tehran · Queue: ')+(queue||(fa()?'همهٔ صف‌های مجاز':'All authorised queues'))+(extra.length?(fa()?' · با فیلترهای تکمیلیِ فرم':' · Additional form filters applied'):'');}
function bucket(value,interval,range={}){
 if(typeof value!=='string')return null;let first,last,hour=null;
 if(interval==='month'&&/^\d{4}-\d{2}$/.test(value)){
  first=value+'-01';const d=date(first);if(!d)return null;d.setUTCMonth(d.getUTCMonth()+1);d.setUTCDate(0);last=d.toISOString().slice(0,10);
 }else if(interval==='hour'&&/^\d{4}-\d{2}-\d{2} (?:[01]\d|2[0-3]):00$/.test(value)){first=last=value.slice(0,10);hour=Number(value.slice(11,13));}
 else if((interval==='day'||interval==='week')&&date(value)){first=value;last=interval==='week'?new Date(date(value).getTime()+6*DAY).toISOString().slice(0,10):value;}
 else return null;
 const d=date(first);if(!d)return null;const fullFirst=first,fullLast=last;
 if(date(range.start)&&range.start>first)first=range.start;
 if(date(range.end)&&range.end<last)last=range.end;
 if(first>last)return null;
 const partial=first!==fullFirst||last!==fullLast;
 let label=interval==='month'?period(first,last)+(fa()?(partial?' · بخشی از ماه میلادی':' · ماه میلادی'):(partial?' · partial Gregorian month':' · Gregorian month')):interval==='week'?period(first,last)+(partial?(fa()?' · بخشی از هفته':' · partial week'):''):display(first);
 if(hour!==null)label+=' · '+String(hour).padStart(2,'0')+':00';
 return {label,first,last,x:d.getTime()+(hour===null?0:hour*3600000),month:d.getUTCFullYear()*12+d.getUTCMonth()};
}
function trend(rows,interval,range={}){
 const values=rows.map(row=>bucket(row.bucket,interval,range));
 if(values.some(value=>!value))throw Error('invalid_report_bucket');
 const gaps=values.map((value,i)=>{if(!i)return false;const previous=values[i-1];if(value.x<=previous.x)throw Error('unordered_report_buckets');return interval==='month'?value.month-previous.month>1:value.x-previous.x>({hour:3600000,day:DAY,week:7*DAY}[interval]);});
 return {labels:values.map(value=>value.label),x:values.map(value=>value.x),gaps,type:values.length>1?'line':'bar'};
}
window.SaneQueueReportPeriods=Object.freeze({display,period,caption,bucket,trend});
})();
