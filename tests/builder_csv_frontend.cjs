/* Execute the shipped builder with controlled HTTP; no PBX or browser service. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),events=new Map(),observers=[],pending=[];let sequence=0;const dispatched=[];const downloaded=[],revoked=[];
function node(id){if(!nodes.has(id)){const value={id,value:'',textContent:'',hidden:false,children:[],listeners:{},options:[],selected:false,
 append(...items){this.children.push(...items);for(const item of items)if(item.tag==='option')this.options.push(item);},
 replaceChildren(){this.children=[];this.options=[];this.textContent='';},addEventListener(type,fn){this.listeners[type]=fn;},
 querySelector(selector){return node(selector);},reportValidity(){return true;},click(){downloaded.push(this);},remove(){}};
 Object.defineProperty(value,'selectedOptions',{get(){return this.options.filter(option=>option.selected);}});nodes.set(id,value);}return nodes.get(id);}
const fields={};for(const name of ['name','queues','columns','groups','outcomes','wait_min','wait_max','talk_min','talk_max'])fields[name]=node('field-'+name);
node('sq-builder-form').elements=fields;
const dates={from:{value:'2026-10-01'},to:{value:'2026-10-02'},queue:{options:[{value:'8001',textContent:'Support'}]}};node('history-filters').elements=dates;
node('ops-config').textContent='{"csrf":"secret-csrf"}';
const document={getElementById:node,createElement(tag){const item=node('created-'+(++sequence));item.tag=tag;return item;},documentElement:{lang:'en'},body:{dataset:{view:'live'},append(){}},addEventListener(name,fn){events.set(name,fn);},dispatchEvent(event){dispatched.push(event);}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../qpanel/themes/qpanel/static/js/report-builder.js'),'utf8'),{
 document,CustomEvent:class{constructor(type,options){this.type=type;this.detail=options.detail;}},URLSearchParams,Intl,Date,Number,String,Math,JSON,console,Set,AbortController,setTimeout:fn=>fn(),URL:{createObjectURL:()=> 'blob:synthetic',revokeObjectURL:url=>revoked.push(url)},MutationObserver:class{constructor(fn){observers.push(fn);}observe(){}},
 fetch(url,options){return new Promise((resolve,reject)=>pending.push({url,options,reject,resolve:(data,csv=false)=>resolve({ok:true,redirected:false,headers:{get:()=> csv?'text/csv':'application/json'},json:async()=>data,blob:async()=>data})}));}
});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const result=(text,next=null)=>({columns:['caller'],rows:[{caller:text}],next,contract:{}});
(async()=>{
 document.body.dataset.view='reports';observers[0]();pending[0].resolve({templates:[]});await settle();
 const exportButton=node('sq-builder-export');
 exportButton.onclick();assert.equal(exportButton.disabled,true);assert.equal(pending.length,2);
 const first=pending[1],body=JSON.parse(first.options.body);
 assert.equal(first.options.headers['X-CSRF-Token'],'secret-csrf');assert.equal(body.language,'en');assert.deepEqual(body.definition.queues,['8001']);
 assert.ok(first.url.includes('/builder/export.csv?'));assert.equal(first.options.method,'POST');
 first.resolve('synthetic-csv',true);await settle();assert.equal(downloaded.length,1);assert.equal(revoked[0],'blob:synthetic');assert.equal(exportButton.disabled,false);
 assert.ok(node('sq-builder-feedback').textContent.includes('Complete bounded-result'));
 exportButton.onclick();dates.to.value='2026-10-03';events.get('sanequeue:reports-loaded')();
 pending[2].resolve('obsolete-csv',true);await settle();assert.equal(downloaded.length,1,'changed dates cannot download stale CSV');
 pending[3].resolve({templates:[]});await settle();
 exportButton.onclick();const leaving=pending[4];document.body.dataset.view='live';observers[0]();assert.equal(leaving.options.signal.aborted,true);
 leaving.resolve('revoked-csv',true);await settle();assert.equal(downloaded.length,1,'leaving reports cannot publish CSV');
 assert.equal(exportButton.disabled,false);
 document.body.dataset.view='reports';observers[0]();pending[5].resolve({templates:[]});await settle();
 node('sq-builder-job-format').value='xlsx';node('sq-builder-job').onclick();const job=pending[6];
 assert.ok(job.url.includes('/export-jobs?'));assert.ok(job.url.includes('format=xlsx'));
 assert.deepEqual(JSON.parse(job.options.body).builder_definition.queues,['8001']);
 assert.equal(job.options.headers['X-CSRF-Token'],'secret-csrf');job.resolve({id:'job-123'});await settle();
 assert.ok(node('sq-builder-feedback').textContent.includes('job-123'));assert.equal(node('sq-builder-job').disabled,false);
 node('sq-builder-schedule').onclick();assert.equal(dispatched[0].type,'sanequeue:builder-schedule');
 assert.equal(JSON.stringify(dispatched[0].detail.definition.queues),'["8001"]');
 console.log('builder CSV frontend: exact definition/CSRF, bounded download, URL disposal, changed-date guard and leave abort passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
