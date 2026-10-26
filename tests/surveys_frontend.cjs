/* Run the shipped supervisor survey view with deferred responses. No DOM library. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../qpanel/themes/qpanel/static/js/surveys.js'),'utf8');
function setup(view='surveys'){
 const nodes={},requests=[],observers=[];
 const make=()=>({value:'',textContent:'',hidden:false,children:[],append(...values){this.children.push(...values);},replaceChildren(...values){this.children=values;},add(value){this.children.push(value);},setAttribute(){},close(){},showModal(){}});
 for(const key of ['surveys-view','ops-config','survey-queue','survey-status','survey-summary','survey-rows','survey-from','survey-to','survey-filter','survey-more','survey-refresh','survey-detail','survey-detail-close','survey-detail-content'])nodes[key]=make();
 nodes['ops-config'].textContent='{"csrf":"test"}';const body={dataset:{view}};
 const document={body,documentElement:{lang:'en'},getElementById:key=>nodes[key]||null,createElement:make};
 vm.runInNewContext(source,{document,Intl,Date,URLSearchParams,Object,JSON,Option:function(text,value){this.textContent=text;this.value=value;},MutationObserver:class{constructor(callback){observers.push(callback);}observe(){}},fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))});
 return {nodes,requests,move(value){body.dataset.view=value;observers.forEach(fn=>fn());},observe(){observers.forEach(fn=>fn());}};
}
const response=value=>({redirected:false,ok:true,headers:{get:()=> 'application/json'},json:async()=>value});
const report=offered=>({rows:[],next_before:null,summary:{offered,csat_numerator:0,csat_denominator:0,csat_percent:null}});
const config={bindings:{},forms:[],queues:['8001'],role:'supervisor'};
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 let state=setup();assert.equal(state.requests.length,1,'restored view must load immediately');state.observe();assert.equal(state.requests.length,1);
 state.requests[0].resolve(response(config));await flush();assert.equal(state.requests.length,2);assert.match(state.requests[1].url,/\/report\?/);
 state.requests[1].resolve(response(report(1)));await flush();assert.match(state.nodes['survey-summary'].textContent,/1/);
 state.nodes['survey-filter'].onsubmit({preventDefault(){}});state.nodes['survey-filter'].onsubmit({preventDefault(){}});
 state.requests[3].resolve(response(report(22)));await flush();state.requests[2].resolve(response(report(11)));await flush();assert.match(state.nodes['survey-summary'].textContent,/22/,'older filter result cannot overwrite current results');
 state.nodes['survey-filter'].onsubmit({preventDefault(){}});state.move('live');state.requests[4].resolve(response(report(99)));await flush();assert.match(state.nodes['survey-summary'].textContent,/22/,'result after leaving is ignored');
 state.move('surveys');assert.equal(state.requests.length,6);state.requests[5].resolve(response(config));await flush();state.requests[6].resolve(response(report(0)));await flush();assert.match(state.nodes['survey-summary'].textContent,/0/);
 state=setup('live');assert.equal(state.requests.length,0,'hidden view must not poll');state.move('surveys');assert.equal(state.requests.length,1);
 console.log('PASS customer survey UI: restored view, deduplication, scoped report loading, stale-filter guard, disposal and re-entry');
})().catch(error=>{console.error(error);process.exitCode=1;});
