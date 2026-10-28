/* Actual shipped plans script: frozen builder definitions and private lifecycle. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../qpanel/themes/qpanel/static/js/report-plans.js'),'utf8');
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const clone=value=>JSON.parse(JSON.stringify(value));
const definition={dataset:'queue_visits',queues:['8001','8002'],columns:['agent','caller','wait_seconds'],group_by:['queue'],filters:{talk_min:7,outcomes:['answered']}};
const custom={id:'a'.repeat(32),version:1,name:'Private <img src=x>',queues:['8001','8002'],outcome:null,format:'xlsx',language:'en',period:'yesterday',at:'08:00',weekdays:[0,2,4],enabled:true,archived:false,builder_definition:clone(definition)};
const legacy={...custom,id:'b'.repeat(32),name:'Standard report',queues:['8001'],format:'pdf',builder_definition:undefined};

function fixture(){
 const nodes=new Map(),events=new Map(),observers=[],requests=[];
 function node(id){
  if(!nodes.has(id)){
   const value={id,value:'',disabled:false,checked:false,hidden:false,options:[],listeners:{},textContent:'',_html:'',
    addEventListener(type,fn){this.listeners[type]=fn;},replaceChildren(){this._html='';this.textContent='';this.options=[];},
    removeAttribute(name){if(name==='disabled')this.disabled=false;},focus(){},scrollIntoView(){},
    click(){return this.onclick?.({target:this,preventDefault(){}});},
    querySelector(selector){if(selector==='[type="submit"]')return node('submit');if(selector==='option[value="pdf"]')return this.options.find(o=>o.value==='pdf');return null;}
   };
   Object.defineProperty(value,'innerHTML',{get(){return this._html;},set(html){this._html=html;if(html.includes('<option'))this.options=[...html.matchAll(/<option value="([^"]*)">([^<]*)<\/option>/g)].map(match=>({value:match[1],textContent:match[2],selected:false,disabled:false}));}});
   Object.defineProperty(value,'selectedOptions',{get(){return this.options.filter(option=>option.selected);}});
   nodes.set(id,value);
  }
  return nodes.get(id);
 }
 const fields={};for(const key of ['name','queues','outcome','format','language','period','at','weekdays','enabled'])fields[key]=node('field-'+key);
 fields.weekdays.options=Array.from({length:7},(_,n)=>({value:String(n),selected:true}));
 fields.format.options=['xlsx','csv','pdf'].map(value=>({value,disabled:false,removeAttribute(name){if(name==='disabled')this.disabled=false;}}));
 const form=node('report-plan-form');form.hidden=true;form.elements=fields;form.reset=()=>{for(const field of Object.values(fields)){field.value='';field.checked=false;}fields.format.value='xlsx';fields.period.value='yesterday';fields.at.value='08:00';};
 const dates={from:{value:'2026-10-01'},to:{value:'2026-10-02'},queue:{value:'8001',options:[{value:'',textContent:'All'},{value:'8001',textContent:'Support'},{value:'8002',textContent:'Sales'}]}};
 node('history-filters').elements=dates;node('ops-config').textContent='{"csrf":"synthetic-csrf"}';
 node('plan-navigation').onclick=()=>{node('history-plan-section').hidden=false;};
 const document={getElementById:node,querySelector(){return node('plan-navigation');},documentElement:{lang:'en'},body:{dataset:{view:'live'}},addEventListener(type,fn){events.set(type,fn);}};
 vm.runInNewContext(source,{document,console,JSON,String,Number,Array,Uint8Array,URLSearchParams,AbortController,Set,crypto:{getRandomValues:values=>values.fill(1)},
  MutationObserver:class{constructor(fn){observers.push(fn);}observe(){}},fetch(url,options){return new Promise((resolve,reject)=>requests.push({url,options,reject,resolve:data=>resolve({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data})}));}});
 const click=(name,plan)=>node('report-plan-list').onclick({target:{closest:()=>({dataset:{[name]:plan.id},disabled:false})}});
 return {node,fields,form,dates,document,requests,events,observers,click,enter(){document.body.dataset.view='reports';observers[0]();},leave(){document.body.dataset.view='live';observers[0]();}};
}

(async()=>{
 const f=fixture();f.enter();f.requests[0].resolve({plans:[custom,legacy]});await settle();
 assert.ok(f.node('report-plan-list').innerHTML.includes('&lt;img'));assert.ok(!f.node('report-plan-list').innerHTML.includes('<img'));
 await f.click('planEdit',custom);assert.equal(f.fields.queues.disabled,true);assert.equal(f.fields.outcome.disabled,true);assert.equal(f.fields.format.options[2].disabled,true);
 f.fields.at.value='09:30';const save=f.form.onsubmit({preventDefault(){}});const payload=JSON.parse(f.requests[1].options.body);
 assert.deepEqual(payload.builder_definition,definition);assert.deepEqual(payload.queues,['8001','8002']);assert.equal(payload.outcome,null);assert.equal(payload.at,'09:30');
 assert.equal(f.requests[1].options.headers['X-CSRF-Token'],'synthetic-csrf');
 f.requests[1].resolve({plan:{...custom,version:2}});await settle();f.requests[2].resolve({plans:[{...custom,version:2},legacy]});await save;
 assert.equal(f.form.hidden,true);
 await f.click('planEdit',legacy);assert.equal(f.fields.queues.disabled,false);assert.equal(f.fields.format.options[2].disabled,false);
 const standard=f.form.onsubmit({preventDefault(){}});assert.ok(!Object.hasOwn(JSON.parse(f.requests[3].options.body),'builder_definition'));
 f.requests[3].resolve({plan:legacy});await settle();f.requests[4].resolve({plans:[custom,legacy]});await standard;
 f.node('history-plan-section').hidden=true;const original=clone(definition);f.events.get('sanequeue:builder-schedule')({detail:{definition:original,name:'Frozen custom'}});original.filters.talk_min=999;assert.equal(f.node('history-plan-section').hidden,false,'builder scheduling navigates to the visible plan section');
 const scheduled=f.form.onsubmit({preventDefault(){}});const frozen=JSON.parse(f.requests[5].options.body);
 assert.deepEqual(frozen.builder_definition,definition);assert.equal(frozen.format,'xlsx');assert.equal(frozen.name,'Frozen custom');
 f.requests[5].resolve({plan:custom});await settle();f.requests[6].resolve({plans:[custom]});await scheduled;
 // A late history response must not re-publish private content after leaving.
 const history=f.click('planHistory',custom);const inFlight=f.requests[7];f.leave();assert.equal(inFlight.options.signal.aborted,true);
 inFlight.resolve({runs:[{date_key:'PRIVATE HISTORY',state:'completed'}]});await history;
 assert.equal(f.node('report-plan-list').innerHTML,'');assert.equal(f.node('report-plan-history').innerHTML,'');
 f.enter();assert.equal(f.requests.length,9,'same-query re-entry must reauthorize');f.requests[8].resolve({plans:[]});await settle();

 const initial=fixture();initial.enter();initial.node('report-plan-new').click();initial.requests[0].resolve({plans:[custom]});await settle();
 assert.ok(initial.node('report-plan-list').innerHTML.includes(custom.id),'opening New during initial metadata load must not strand the plan list');

 const editing=fixture();editing.enter();editing.requests[0].resolve({plans:[custom]});await settle();await editing.click('planEdit',custom);
 const oldSave=editing.form.onsubmit({preventDefault(){}});editing.fields.at.value='11:00';editing.form.listeners.input?.();editing.form.listeners.change?.();
 editing.requests[1].resolve({plan:custom});await settle();
 if(editing.requests[2]){editing.requests[2].resolve({plans:[custom]});await settle();}
 await oldSave;assert.equal(editing.form.hidden,false,'late save must not discard newer unsaved scheduling input');assert.equal(editing.fields.at.value,'11:00');
 console.log('report plans frontend: custom definition preservation, clone, legacy reset, CSRF, private leave/re-entry, pending refresh and stale-save guards passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
