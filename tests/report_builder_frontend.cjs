/* Execute the shipped builder with controlled HTTP; no PBX or browser service. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),events=new Map(),observers=[],pending=[];let sequence=0;
function node(id){if(!nodes.has(id)){const value={id,value:'',textContent:'',hidden:false,children:[],listeners:{},options:[],selected:false,
 append(...items){this.children.push(...items);for(const item of items)if(item.tag==='option')this.options.push(item);},
 replaceChildren(){this.children=[];this.options=[];this.textContent='';},addEventListener(type,fn){this.listeners[type]=fn;},
 querySelector(selector){return node(selector);},reportValidity(){return true;}};
 Object.defineProperty(value,'selectedOptions',{get(){return this.options.filter(option=>option.selected);}});nodes.set(id,value);}return nodes.get(id);}
const fields={};for(const name of ['name','queues','columns','groups','outcomes','wait_min','wait_max','talk_min','talk_max'])fields[name]=node('field-'+name);
node('sq-builder-form').elements=fields;
const dates={from:{value:'2026-10-01'},to:{value:'2026-10-02'},queue:{options:[{value:'8001',textContent:'Support'}]}};node('history-filters').elements=dates;
node('ops-config').textContent='{"csrf":"secret-csrf"}';
const document={getElementById:node,createElement(tag){const item=node('created-'+(++sequence));item.tag=tag;return item;},documentElement:{lang:'en'},body:{dataset:{view:'live'}},addEventListener(name,fn){events.set(name,fn);}};
vm.runInNewContext(fs.readFileSync(path.join(__dirname,'../qpanel/themes/qpanel/static/js/report-builder.js'),'utf8'),{
 document,URLSearchParams,Intl,Date,Number,String,Math,JSON,console,Set,AbortController,MutationObserver:class{constructor(fn){observers.push(fn);}observe(){}},
 fetch(url,options){return new Promise((resolve,reject)=>pending.push({url,options,reject,resolve:data=>resolve({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data})}));}
});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const result=(text,next=null)=>({columns:['caller'],rows:[{caller:text}],next,contract:{}});
(async()=>{
 document.body.dataset.view='reports';observers[0]();assert.equal(pending.length,1);
 pending[0].resolve({templates:[]});await settle();assert.equal(fields.queues.selectedOptions[0].value,'8001');
 const submit=()=>node('sq-builder-form').onsubmit({preventDefault(){}});
 submit();submit();assert.equal(pending.length,3);
 const body=JSON.parse(pending[2].options.body);assert.equal(body.definition.dataset,'queue_visits');assert.deepEqual(body.definition.queues,['8001']);assert.equal(pending[2].options.headers['X-CSRF-Token'],'secret-csrf');
 pending[2].resolve(result('<img src=x onerror=alert(1)>','opaque-next'));await settle();
 assert.equal(node('sq-builder-body').children[0].children[0].textContent,'<img src=x onerror=alert(1)>');
 pending[1].reject(Error('late failure'));await settle();
 assert.equal(node('sq-builder-body').children.length,1,'obsolete failure must not clear current results');
 node('sq-builder-more').onclick();assert.equal(JSON.parse(pending[3].options.body).before,'opaque-next');
 pending[3].resolve(result('Caller #PRIVATE'));await settle();assert.equal(node('sq-builder-body').children[0].children[0].textContent,'Caller #PRIVATE');
 submit();dates.to.value='2026-10-03';events.get('sanequeue:reports-loaded')();
 pending[4].resolve(result('OLD CUSTOMER'));await settle();assert.equal(node('sq-builder-body').children.length,0,'old date response must remain hidden');
 pending[5].resolve({templates:[]});await settle();
 submit();const old=pending[6];document.body.dataset.view='live';observers[0]();
 assert.equal(old.options.signal.aborted,true,'leaving Reports aborts private requests');
 assert.equal(node('sq-builder-body').children.length,0);
 document.body.dataset.view='reports';observers[0]();assert.equal(pending.length,8,'re-entry reloads metadata even with same dates');
 old.resolve(result('REVOKED OLD CUSTOMER'));await settle();assert.equal(node('sq-builder-body').children.length,0);
 pending[7].resolve({templates:[]});await settle();
 submit();node('history-builder-section').hidden=true;observers[1]();
 assert.equal(pending[8].options.signal.aborted,true,'hiding the section aborts requests');
 node('history-builder-section').hidden=false;observers[1]();assert.equal(pending.length,10,'section re-entry reauthorizes metadata');
 pending[8].resolve(result('HIDDEN CUSTOMER'));pending[9].resolve({templates:[]});await settle();
 assert.equal(node('sq-builder-body').children.length,0);
 console.log('report-builder frontend: real script masking display, CSRF, keyset, XSS text and stale-response checks passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
