/* Exercise the shipped scripts with controlled HTTP responses, without a PBX. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.join(__dirname,'..');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup(file,withCharts=false){
 const nodes=new Map(),events=new Map(),observers=[],pending=[];
 function element(id){
  if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,open:false,isConnected:true,options:[],attrs:{},listeners:{},children:[],dataset:{},
   reportValidity(){return true;},replaceChildren(){this.innerHTML='';this.textContent='';this.children=[];},append(...items){this.children.push(...items);},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},
   addEventListener(k,v){this.listeners[k]=v;},querySelector(){return element('date-caption');},querySelectorAll(){return [];},
   close(){this.open=false;this.listeners.close?.();},showModal(){this.open=true;}});
  return nodes.get(id);
 }
 const fields={};for(const key of ['from','to','queue','pause_direction','outcome'])fields[key]=element('field-'+key);
 fields.pause_direction.value='outbound';element('history-filters').elements=fields;
 element('ops-config').textContent='{"csrf":"test"}';
 let serial=0;
 const document={createElement:tag=>element(tag+'-'+(++serial)),documentElement:{lang:'en'},body:{dataset:{view:'live'}},getElementById:element,
  addEventListener(k,v){events.set(k,v);},dispatchEvent(event){events.get(event.type)?.(event);}};
 const charts=new Map();const chartAPI={clear(host){if(host)charts.delete(host.id);},render(host,value){if(host.id==='history-analysis-chart')assert.equal(element('history-analysis-results').hidden,false,'chart parent must be visible before render');charts.set(host.id,value);}};
 const context={document,window:withCharts?{SaneQueueReportCharts:chartAPI}:{},URLSearchParams,Intl,Date,Number,String,Math,AbortController,
  FormData:class{constructor(form){this.rows=Object.entries(form.elements||{}).map(([k,v])=>[k,v.value||'']);}[Symbol.iterator](){return this.rows[Symbol.iterator]();}},
  MutationObserver:class{constructor(callback){observers.push(callback);}observe(){}},CustomEvent:class{constructor(type){this.type=type;}},
  fetch(url,options={}){return new Promise((resolve,reject)=>pending.push({url,options,signal:options.signal,resolve:data=>resolve({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data}),reject}));},
  console,setTimeout,URL,crypto:require('node:crypto').webcrypto};
 vm.runInNewContext(fs.readFileSync(path.join(root,'qpanel/themes/qpanel/static/js',file),'utf8'),context,{filename:file});
 return {element,fields,document,pending,observers,events,charts};
}
function data(url){
 if(url.includes('/overview?'))return {queues:[],allowed_queues:['8001'],sources:{}};
 if(url.includes('/activity?'))return {agents:[],rows:[]};
 return {rows:[],next:null};
}
async function reporting(){
 const state=setup('reports.js'),{element,pending}=state;
 const submit=()=>element('history-filters').listeners.submit({preventDefault(){}});
 const targets=['history-kpis','history-queues','history-table','history-agents','history-duty-agents','history-activity','history-activity-intervals','history-outbound'];
 for(const id of targets)element(id).innerHTML='OLD CUSTOMER DATA';
 submit();assert.equal(pending.length,6);
 for(const id of targets)assert.equal(element(id).innerHTML,'',id+' must clear on new filters');
 assert.equal(element('reports-view').attrs['aria-busy'],'true');
 pending[0].reject(Error('server_error'));await settle();
 assert.match(element('history-feedback').textContent,/Unable to load/);
 for(const id of targets)assert.equal(element(id).innerHTML,'');
 assert.equal(element('reports-view').attrs['aria-busy'],'false');

 submit();const obsolete=pending.slice(6);submit();const current=pending.slice(12);
 for(const response of current)response.resolve(data(response.url));await settle();
 const feedback=element('history-feedback').textContent;
 assert.match(feedback,/Displayed queue visits/);
 obsolete[0].reject(Error('late_failure'));await settle();
 assert.equal(element('history-feedback').textContent,feedback,'old failure must not overwrite current results');

 const trigger={dataset:{historyDetail:'opaque-id'},disabled:false};
 const detail=element('history-table').onclick({target:{closest:()=>trigger}});
 const request=pending[pending.length-1];submit();request.resolve({});await detail;
 assert.equal(element('history-detail').open,false,'old detail must not reopen after filter changes');
}
async function plans(){
 const state=setup('report-plans.js'),{element,document,pending,observers,fields}=state;
 // report-plans only accesses these select controls when a response arrives.
 element('report-plan-form').hidden=true;
 element('report-plan-form').elements={queues:element('plan-queues')};
 fields.queue.options=[{value:'8001',textContent:'8001'}];
 document.body.dataset.view='reports';observers[0]();assert.equal(pending.length,1,'initial plans load without manual refresh');
 pending[0].resolve({plans:[]});await settle();
 observers[0]();assert.equal(pending.length,1,'same view/filter must not repeatedly fetch');
 fields.queue.value='8001';document.dispatchEvent({type:'sanequeue:reports-loaded'});
 assert.equal(pending.length,2,'applied queue scope refreshes plans');
 pending[1].resolve({plans:[]});await settle();
}
async function transcripts(){
 const {element,pending,observers,document}=setup('transcript-search.js');
 document.body.dataset.view='reports';
 const submit=()=>element('transcript-search-form').listeners.submit({preventDefault(){}});
 element('transcript-search-query').value='private query';
 const old=submit(),current=submit();assert.equal(pending.length,2);
 pending[1].resolve({rows:[{id:'job',queue:'8001',excerpt:'<img src=x onerror=alert(1)>'}]});await current;
 const host=element('transcript-search-results');assert.equal(host.children.length,1);
 const card=host.children[0];assert.equal(card.children[1].textContent,'<img src=x onerror=alert(1)>');
 assert.equal(card.children[1].innerHTML,'','transcript excerpts never render trusted HTML');
 pending[0].reject(Error('obsolete'));await old;assert.equal(host.children.length,1,'stale search error preserves current rows');
 const failed=submit();assert.equal(host.children.length,0,'a new search clears prior private results');pending[2].reject(Error('revoked'));await failed;
 assert.match(element('transcript-search-status').textContent,/Search failed/);
 assert.equal(host.children.length,0);assert.equal(host.attrs['aria-busy'],undefined);
 const leave=submit();document.body.dataset.view='live';observers[0]();pending[3].resolve({rows:[{id:'old',queue:'8001',excerpt:'PRIVATE OLD'}]});await leave;assert.equal(host.children.length,0,'leaving module invalidates pending private excerpts');assert.equal(element('transcript-search-status').textContent,'');
}
async function exportRecovery(){
 const {element,pending,document,observers}=setup('report-exports.js');document.body.dataset.view='reports';
 element('history-jobs-refresh').onclick();await settle();assert.equal(pending.length,1);
 pending[0].resolve({jobs:[],recovery:[{job_id:'<img src=x onerror=alert(1)>',state:'quarantined',size:1024}]});await settle();
 const host=element('history-export-recovery');assert.equal(host.hidden,false);const item=host.children[0].children[2].children[0];assert.match(item.textContent,/<img/);assert.equal(item.innerHTML,'');
 element('history-jobs-refresh').onclick();await settle();assert.equal(host.hidden,true);assert.equal(host.children.length,0,'new refresh clears old recovery data');pending[1].reject(Error('revoked'));await settle();assert.equal(host.children.length,0);
 element('history-jobs-refresh').onclick();await settle();document.body.dataset.view='live';observers[0]();pending[2].resolve({jobs:[],recovery:[{job_id:'PRIVATE',state:'quarantined',size:10}]});await settle();assert.equal(host.children.length,0,'late export metadata does not reappear after leaving');assert.equal(element('history-jobs-feedback').textContent,'');
}
async function journey(){
 const {element,pending,document,observers,events}=setup('journey-reports.js');
 document.body.dataset.view='reports';const dialog=element('history-detail');dialog.open=true;
 const host=element('journey-result');
 const button={dataset:{historyJourney:'opaque',journeyQuery:'from=2026-10-26'},isConnected:true,disabled:false,nextElementSibling:host};
 const click=()=>events.get('click')({target:{closest:()=>button}});
 const payload={events:[{ts:100,kind:'IVR_SELECTION',source:'cel',node:'leg1',ivr_id:'3',digit:'2',caller:'n1'}],edges:[],numbers:{n1:'<img src=x onerror=alert(1)>'},final_hangup:null,
  termination:{queue_segment:{party:'caller'},final:{party:null,reason:'conflicting_causality'}}};
 const obsolete=click();element('history-filters').listeners.submit();
 assert.equal(pending[0].signal.aborted,true);pending[0].resolve(payload);await obsolete;
 assert.equal(host.innerHTML,'','late journey must not reappear after changed filters');
 const loaded=click();pending[1].resolve(payload);await loaded;
 assert.match(host.innerHTML,/Queue segment ended by: Caller/);
 assert.match(host.innerHTML,/Conflicting hangup evidence/);assert.match(host.innerHTML,/IVR 3/);assert.match(host.innerHTML,/Key: 2/);
 assert.match(host.innerHTML,/&lt;img/);assert.doesNotMatch(host.innerHTML,/<img/);
 assert.equal(host.attrs['aria-busy'],undefined);assert.equal(button.disabled,false);
 const old=click(),fresh=click();pending[3].resolve({...payload,final_hangup:{node:'leg2',party:'agent'}});await fresh;
 const current=host.innerHTML;assert.match(current,/Consistent direct hangup evidence: Agent/);
 pending[2].reject(Error('late failure'));await old;assert.equal(host.innerHTML,current,'old failure cannot overwrite fresh causality');
 const closing=click();dialog.close();pending[4].resolve(payload);await closing;
 assert.equal(host.innerHTML,'','closing private detail clears and invalidates pending data');
 dialog.showModal();const leaving=click();document.body.dataset.view='live';observers[0]();
 pending[5].resolve(payload);await leaving;assert.equal(host.innerHTML,'');
 document.body.dataset.view='reports';const detached=click();host.isConnected=false;observers[1]();
 pending[6].reject(Error('detached'));await detached;assert.equal(host.innerHTML,'');
 host.isConnected=true;const reentry=click();assert.equal(pending.length,8,'reentry must make a fresh authorized request');
 pending[7].reject(Error('revoked'));await reentry;assert.match(host.textContent,/Unable to load/);assert.equal(host.innerHTML,'');
 const last=click();pending[8].resolve(payload);await last;document.dispatchEvent({type:'sanequeue:reports-loaded'});
 assert.equal(host.innerHTML,'','a new applied report discards completed private journey data too');
}
async function customerSegments(){
 const {element,pending,document,observers}=setup('customer-segments.js');
 const form=element('segments-vip-form');form.elements={queue:element('segment-queue'),number:element('segment-number'),enabled:element('segment-enabled'),period:element('segment-period')};
 const host=element('segments-results'),section=element('history-customer-segments-section');
 const payload={vip:[{queue:'8001',classification:'unclassified',visits:1,answered:1,abandoned:0,sla_denominator:0,sla_percent:null}],blocks:[],observations:[{queue:'8001',number:'<img src=x onerror=alert(1)>',at:100,reason:'blacklist',source:'source'}],labels:[],queues:['8001'],can_manage:true};
 document.body.dataset.view='reports';observers[0]();assert.equal(pending.length,1);
 document.dispatchEvent({type:'sanequeue:reports-loaded'});pending[1].resolve(payload);await settle();
 const text=node=>node.textContent+' '+node.children.map(text).join(' ');
 assert.match(text(host),/<img/);assert.equal(host.innerHTML,'','customer numbers must use text nodes');
 const current=host.children.length;pending[0].reject(Error('stale'));await settle();assert.equal(host.children.length,current);
 element('segments-refresh').listeners.click();section.hidden=true;observers[1]();pending[2].resolve(payload);await settle();assert.equal(host.children.length,0);
 section.hidden=false;observers[1]();pending[3].resolve(payload);await settle();
 form.elements.queue.value='8001';form.elements.number.value='09123456789';form.elements.enabled.value='1';form.elements.period.checked=false;
 const save=form.listeners.submit({preventDefault(){}});assert.equal(pending[4].options.headers['X-CSRF-Token'],'test');const first=JSON.parse(pending[4].options.body);
 pending[4].reject(Error('uncertain'));await save;
 const retry=form.listeners.submit({preventDefault(){}});const second=JSON.parse(pending[5].options.body);assert.equal(first.request_key,second.request_key,'uncertain metadata save retries the same logical operation');
 pending[5].resolve({});await settle();pending[6].resolve(payload);await retry;
 document.body.dataset.view='live';observers[0]();assert.equal(host.children.length,0);assert.equal(form.hidden,true);
}

async function chartAdapters(){
 const prepare=file=>{const s=setup(file,true);s.document.body.dataset.view='reports';s.fields.from.value='2026-10-01';s.fields.to.value='2026-10-02';s.fields.queue.value='8001';return s;};
 const a=prepare('agent-metrics-reports.js');
 const metrics={agents:[{agent:'100',answered_queue_segments:3,unique_queue_talk_seconds:20,on_duty_seconds:60,acw_seconds:null,aht_seconds:null,occupancy_percent:null,coverage:{complete:false,reasons:['explicit_acw_unavailable']}}],totals:{agents:1}};
 let action=a.element('history-agent-metrics-run').onclick();a.pending[0].resolve(metrics);await action;
 assert.deepEqual(Array.from(a.charts.get('history-agent-answer-chart').series[0].values),[3]);assert.deepEqual(Array.from(a.charts.get('history-agent-aht-chart').series[0].values),[null]);
 action=a.element('history-agent-metrics-run').onclick();assert.equal(a.charts.size,0,'new request clears old chart');a.pending[1].reject(Error('denied'));await action;assert.equal(a.charts.size,0);
 action=a.element('history-agent-metrics-run').onclick();a.document.body.dataset.view='live';a.observers.forEach(f=>f());a.document.body.dataset.view='reports';a.pending[2].resolve(metrics);await action;assert.equal(a.charts.size,0,'late response cannot restore chart after leave and reentry');
 const c=prepare('cdr-reports.js');action=c.element('history-cdr-filters').onsubmit({preventDefault(){}});c.pending[0].resolve({rows:[],next:null,can_search_numbers:true});c.pending[1].resolve({totals:{segments_started:10,answered_segments:6,unanswered_segments:4,known_billsec_sum:120},trunk_traffic:[{trunk:'trunk A',did:'line1',direction:'inbound',segments_started:10,answered_segments:6,known_billsec_sum:120}]});await settle();
 assert.deepEqual(Array.from(c.charts.get('history-trunk-chart').series[0].values),[10],'chart uses complete aggregate, not empty page rows');c.element('history-cdr-filters').listeners.change();assert.equal(c.charts.size,0);
 c.element('history-cdr-filters').onsubmit({preventDefault(){}});c.element('history-cdr-filters').listeners.input();c.pending[2].resolve({rows:[],next:null});c.pending[3].resolve({totals:{},trunk_traffic:[]});await settle();assert.equal(c.charts.size,0,'typing local filter invalidates pending chart before blur');
 const v=prepare('customer-segments.js');const vf=v.element('segments-vip-form');vf.elements={queue:v.element('vip-queue'),number:v.element('vip-number'),enabled:v.element('vip-enabled'),period:v.element('vip-period')};v.observers[0]();
 const vip={vip:[{queue:'8001',classification:'vip',visits:3,answered:2,abandoned:1,sla_denominator:2,sla_percent:50}],blocks:[],observations:[],labels:[],queues:['8001'],can_manage:false,sla_seconds:20};
 v.element('segments-sla').listeners.input();v.pending[0].resolve(vip);await settle();assert.equal(v.charts.size,0,'changed SLA invalidates old response');
 v.element('segments-refresh').listeners.click();v.pending[1].resolve(vip);await settle();assert.equal(v.charts.get('history-vip-sla-chart').maximum,100);assert.deepEqual(Array.from(v.charts.get('history-vip-sla-chart').series[0].values),[50]);
 v.element('segments-refresh').listeners.click();v.fields.from.value='2026-10-03';v.element('history-filters').listeners.input();v.pending[2].resolve(vip);await settle();assert.equal(v.charts.size,0,'typing central date invalidates old VIP payload');
 const s=prepare('shift-reports.js');action=s.element('history-shifts-run').onclick();s.pending[0].resolve({agents:[{agent:'100',scheduled_seconds:120,on_duty_seconds:60,uncovered_seconds:null}],shifts:[],schedule_configured:true});await action;
 assert.equal(s.charts.get('history-shift-chart').unit,'Minutes');assert.deepEqual(Array.from(s.charts.get('history-shift-chart').series[0].values),[2]);assert.deepEqual(Array.from(s.charts.get('history-shift-chart').series[2].values),[null]);
 const t=prepare('report-analytics.js');action=t.element('history-analysis-run').onclick();t.pending[0].resolve({totals:{visits:4,answered:3,abandoned:1,sla_percent:100},trends:[{bucket:'2026-10-01',visits:4,answered:3,abandoned:1,average_wait_seconds:2,sla_percent:100,incomplete:0}],queues:[{queue:'8001',asa_seconds:2,wait_percentiles:{p50_seconds:2,p90_seconds:4,p95_seconds:5},longest_wait_seconds:5,abandon_percent:25,sla_numerator:3,sla_denominator:3,unknown_wait:0}],heatmap:[]});await action;
 assert.deepEqual(Array.from(t.charts.get('history-analysis-chart').series[0].values),[3]);assert.deepEqual(Array.from(t.charts.get('history-queue-wait-chart').series[2].values),[4]);t.element('history-filters').listeners.change();assert.equal(t.charts.size,0);
}

async function ringAttempts(){
 const {element,document,pending,observers,charts}=setup('ring-attempts.js',true);document.body.dataset.view='reports';
 const payload={totals:{attempts:3,known_duration_attempts:2,unknown_duration_attempts:1,average_known_ring_seconds:1.5},groups:[{queue:'8001',agent:'<img src=x>',attempts:3,known_duration_attempts:2,known_ring_seconds:3,average_known_ring_seconds:1.5}],rows:[{timestamp:100,queue:'8001',agent:'<img src=x>',ring_seconds:null,correlation:'queue_visit_unproven'}],next:'opaque-cursor',coverage:{queue_log:{fresh:true},source_gap:false}};
 element('ring-attempts-run').listeners.click();pending[0].resolve(payload);await settle();
 assert.equal(charts.get('ring-attempts-chart').series[0].values[0],3);assert.equal(element('ring-attempts-more').hidden,false);
 const allText=node=>node.textContent+' '+node.children.map(allText).join(' ');assert.match(allText(element('ring-attempts-rows')),/<img src=x>/);assert.equal(element('ring-attempts-rows').innerHTML,'');
 element('ring-attempts-more').listeners.click();assert.match(pending[1].url,/before=opaque-cursor/);element('history-filters').listeners.input();pending[1].resolve(payload);await settle();assert.equal(charts.size,0);assert.equal(element('ring-attempts-run').disabled,false,'filter changes must not strand disabled button');
 element('ring-attempts-run').listeners.click();document.body.dataset.view='live';observers.forEach(f=>f());document.body.dataset.view='reports';pending[2].resolve(payload);await settle();assert.equal(charts.size,0);assert.equal(element('ring-attempts-rows').children.length,0);
 element('ring-attempts-run').listeners.click();pending[3].reject(Error('denied'));await settle();assert.equal(charts.size,0);assert.match(element('ring-attempts-feedback').textContent,/Report unavailable/);
}
(async()=>{await ringAttempts();await chartAdapters();await reporting();await plans();await transcripts();await exportRecovery();await journey();await customerSegments();console.log('Reporting frontend: failure, stale-response, transcript, export recovery, journey and customer-segment lifecycle checks passed');})().catch(error=>{console.error(error);process.exitCode=1;});
