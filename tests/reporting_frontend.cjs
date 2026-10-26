/* Exercise the shipped scripts with controlled HTTP responses, without a PBX. */
'use strict';
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');
const path=require('node:path');
const root=path.join(__dirname,'..');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
function setup(file){
 const nodes=new Map(),events=new Map(),observers=[],pending=[];
 function element(id){
  if(!nodes.has(id))nodes.set(id,{id,value:'',textContent:'',innerHTML:'',hidden:false,disabled:false,open:false,options:[],attrs:{},listeners:{},children:[],dataset:{},
   replaceChildren(){this.innerHTML='';this.textContent='';this.children=[];},append(...items){this.children.push(...items);},setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];},
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
 const context={document,window:{},URLSearchParams,Intl,Date,Number,String,Math,AbortController,
  MutationObserver:class{constructor(callback){observers.push(callback);}observe(){}},CustomEvent:class{constructor(type){this.type=type;}},
  fetch(url){return new Promise((resolve,reject)=>pending.push({url,resolve:data=>resolve({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data}),reject}));},
  console,setTimeout,URL,crypto:require('node:crypto').webcrypto};
 vm.runInNewContext(fs.readFileSync(path.join(root,'qpanel/themes/qpanel/static/js',file),'utf8'),context,{filename:file});
 return {element,fields,document,pending,observers};
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
(async()=>{await reporting();await plans();await transcripts();await exportRecovery();console.log('Reporting frontend: failure, stale-response, detail race, plan-loading and transcript security and export recovery checks passed');})().catch(error=>{console.error(error);process.exitCode=1;});
