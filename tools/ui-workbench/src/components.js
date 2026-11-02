import './tokens.css';
import './style.css';

export const words = {
  fa: {title:'کارگاه رابط SaneQueue',intro:'نمونهٔ توسعه با دادهٔ ساختگی؛ به مرکز تلفن متصل نیست.',theme:'تم',locale:'زبان',light:'روشن',dark:'تیره',state:'حالت نمایش',success:'آماده',loading:'در حال بارگذاری',empty:'داده‌ای موجود نیست',error:'دریافت اطلاعات ناموفق بود',denied:'مجوز مشاهده ندارید',disabled:'غیرفعال',retry:'تلاش مجدد',save:'ذخیره',saved:'ذخیره شد',name:'نام نمایشی',required:'نام را وارد کنید',kpi:'تماس پاسخ‌داده‌شده',help:'تعداد مراجعه‌های پاسخ‌داده‌شده به صف در بازهٔ نمونه؛ این عدد تعداد مشتری یکتا نیست.',period:'بازه: امروز · منبع: دادهٔ ساختگی · واحد: مراجعه',unknown:'نامشخص',agents:'وضعیت کارشناسان',available:'آماده',ringing:'در حال زنگ خوردن',oncall:'در حال مکالمه',paused:'توقف',wrapup:'پس از تماس',offline:'خارج از دسترس',agent:'کارشناس',queue:'صف',status:'وضعیت',skip:'رفتن به محتوا',profile:'نمونهٔ فرم پروفایل',details:'راهنمای شاخص',table:'فهرست وضعیت کارشناسان؛ برای ستون‌های بیشتر افقی حرکت کنید',all:'همهٔ صف‌ها',filter:'فیلتر صف'},
  en: {title:'SaneQueue UI Workbench',intro:'Synthetic development fixtures. No PBX connection.',theme:'Theme',locale:'Language',light:'Light',dark:'Dark',state:'Display state',success:'Ready',loading:'Loading',empty:'No data available',error:'Unable to load data',denied:'You do not have permission to view this',disabled:'Disabled',retry:'Retry',save:'Save',saved:'Saved',name:'Display name',required:'Enter a name',kpi:'Answered queue visits',help:'Answered visits to a queue during the sample period. This is not a count of unique customers.',period:'Period: today · Source: synthetic fixture · Unit: visits',unknown:'Unknown',agents:'Agent states',available:'Available',ringing:'Ringing',oncall:'On call',paused:'Paused',wrapup:'Wrap-up',offline:'Offline',agent:'Agent',queue:'Queue',status:'Status',skip:'Skip to content',profile:'Sample profile form',details:'Metric definition',table:'Agent status list; scroll horizontally for more columns',all:'All queues',filter:'Queue filter'}
};

function element(tag, text, className) {
  const node = document.createElement(tag);
  if (text !== undefined) node.textContent = text;
  if (className) node.className = className;
  return node;
}

export function button(label, {disabled = false, onClick} = {}) {
  const node = element('button', label, 'sq-button');
  node.type = 'button'; node.disabled = disabled;
  if (onClick) node.addEventListener('click', onClick);
  return node;
}

export function statusBadge(state, locale = 'fa') {
  const badge = element('span', words[locale][state], `sq-status sq-status--${state}`);
  badge.dataset.state = state;
  return badge;
}

export function kpi(locale = 'fa', unknown = false) {
  const w = words[locale], card = element('article', undefined, 'sq-card');
  card.append(element('h2', w.kpi), element('strong', unknown ? w.unknown : (12).toLocaleString(locale), 'sq-value'), element('p', w.period, 'sq-muted'));
  const details = element('details'); details.append(element('summary', w.details), element('p', w.help)); card.append(details);
  return card;
}

export function agentTable(locale = 'fa', queue = '') {
  const w = words[locale], wrapper = element('div', undefined, 'sq-table-scroll');
  wrapper.tabIndex = 0; wrapper.setAttribute('role','region'); wrapper.setAttribute('aria-label',w.table);
  const table = element('table'), head = element('thead'), row = element('tr'), body = element('tbody');
  table.append(element('caption', w.agents));
  for (const title of [w.agent,w.queue,w.status]) { const th = element('th',title); th.scope='col'; row.append(th); }
  head.append(row);
  ['available','ringing','oncall','paused','wrapup','offline'].forEach((state,i) => {
    const q = i % 2 ? '8002' : '8001'; if (queue && queue !== q) return;
    const tr=element('tr'); tr.append(element('td',`Agent ${i+1}`),element('td',q));
    const td=element('td'); td.append(statusBadge(state,locale)); tr.append(td); body.append(tr);
  });
  table.append(head,body); wrapper.append(table); return wrapper;
}

export function statePanel(state, locale = 'fa', onRetry = () => {}) {
  const w=words[locale], panel=element('section',undefined,'sq-card sq-state-panel');
  panel.setAttribute('aria-label', w.state);
  const message=element('p',w[state]); message.setAttribute('role',state==='error'?'alert':'status'); panel.append(message);
  if(state==='error') panel.append(button(w.retry,{onClick:onRetry}));
  if(state==='disabled') panel.append(button(w.save,{disabled:true}));
  return panel;
}

export function profileForm(locale = 'fa') {
  const w=words[locale], form=element('form',undefined,'sq-card'); form.noValidate=true;
  form.append(element('h2',w.profile));
  const label=element('label',w.name); label.htmlFor='display-name';
  const input=element('input'); input.id='display-name'; input.name='displayName'; input.required=true; input.maxLength=80;
  const message=element('p'); message.id='profile-feedback'; message.setAttribute('aria-live','polite'); input.setAttribute('aria-describedby',message.id);
  const submit=button(w.save); submit.type='submit';
  form.append(label,input,submit,message);
  form.addEventListener('submit',event=>{event.preventDefault();const valid=Boolean(input.value.trim());input.setAttribute('aria-invalid',String(!valid));message.textContent=valid?w.saved:w.required;if(!valid)input.focus();});
  return form;
}

export function renderWorkbench({locale='fa',theme='light',state='success',queue=''}={}) {
  const w=words[locale], root=element('div',undefined,'sq-workbench'); root.lang=locale; root.dir=locale==='fa'?'rtl':'ltr'; root.dataset.theme=theme;
  const skip=element('a',w.skip,'sq-skip'); skip.href='#main';root.append(skip);
  const header=element('header');header.append(element('h1',w.title),element('p',w.intro));
  const controls=element('div',undefined,'sq-toolbar');
  const options={locale:[['fa','فارسی'],['en','English']],theme:[['light',w.light],['dark',w.dark]],state:['success','loading','empty','error','denied','disabled'].map(s=>[s,w[s]]),queue:[['',w.all],['8001','8001'],['8002','8002']]};
  const values={locale,theme,state,queue};
  for(const key of Object.keys(options)){
    const label=element('label',w[key==='queue'?'filter':key]);const select=element('select');select.name=key;
    for(const [value,title] of options[key]){const option=element('option',title);option.value=value;option.selected=value===values[key];select.append(option);}
    select.addEventListener('change',()=>{const next={...values,[key]:select.value};root.replaceWith(renderWorkbench(next));});label.append(select);controls.append(label);
  }
  header.append(controls);root.append(header);
  const main=element('main');main.id='main';main.tabIndex=-1;
  if(state==='success') {const grid=element('div',undefined,'sq-grid');grid.append(kpi(locale),kpi(locale,true));main.append(grid,agentTable(locale,queue),profileForm(locale));}
  else main.append(statePanel(state,locale,()=>root.replaceWith(renderWorkbench({...values,state:'success'}))));
  root.append(main);return root;
}
