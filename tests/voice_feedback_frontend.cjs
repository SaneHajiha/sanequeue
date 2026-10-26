/* Exercise the actual shipped script with deferred requests and a minimal DOM. */
'use strict';
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),assert=require('node:assert/strict');
const source=fs.readFileSync(path.join(__dirname,'../qpanel/themes/qpanel/static/js/voice-feedback.js'),'utf8');
function setup(view='voice-feedback'){
 const nodes={},requests=[],observers=[];const make=()=>({value:'',textContent:'',hidden:false,children:[],disabled:false,files:[],append(...n){this.children.push(...n);},replaceChildren(...n){this.children=n;},pause(){},load(){},removeAttribute(){},reportValidity(){return true;},click(){},play:async()=>{}});
 const ids=['voice-feedback-view','ops-config','vf-player','vf-detail','vf-history','vf-message','vf-filter-queue','vf-filter-status','vf-upload-queue','vf-rows','vf-next','vf-summary','vf-evidence','vf-review-status','vf-assignee','vf-note','vf-followup','vf-play','vf-download','vf-audit','vf-file','vf-session','vf-upload','vf-upload-button','vf-review','vf-save','vf-refresh'];for(const id of ids)nodes[id]=make();
 nodes['ops-config'].textContent='{"csrf":"test"}';const body={dataset:{view}};
 vm.runInNewContext(source,{document:{body,documentElement:{lang:'en'},getElementById:id=>nodes[id],createElement:make},Intl,Date,URLSearchParams,AbortController,crypto:{randomUUID:()=> 'idempotent-key'},URL:{createObjectURL:()=> 'blob:local',revokeObjectURL(){}},MutationObserver:class{constructor(fn){observers.push(fn);}observe(){}},fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))});
 return {nodes,requests,observe(){observers.forEach(fn=>fn());},move(view){body.dataset.view=view;observers.forEach(fn=>fn());}};
}
const response=data=>({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data});
const report=(id='a'.repeat(32),queue='8001')=>({queues:['8001'],counts:{new:1},next:null,rows:[{id,queue,created:100,duration:1,status:'new',assignee:'<img src=x onerror=alert(1)>'}]});
const flush=()=>new Promise(resolve=>setImmediate(resolve));
(async()=>{
 let s=setup();assert.equal(s.requests.length,1);s.observe();assert.equal(s.requests.length,1);
 s.requests[0].resolve(response(report()));await flush();assert.equal(s.nodes['vf-rows'].children[0].children[4].textContent,'<img src=x onerror=alert(1)>');
 s.nodes['vf-refresh'].onclick();s.move('live');assert.equal(s.requests[1].options.signal.aborted,true);s.requests[1].resolve(response(report('b'.repeat(32),'STALE')));await flush();assert.equal(s.nodes['vf-rows'].children.length,0);
 s.move('voice-feedback');assert.equal(s.requests.length,3);s.requests[2].resolve(response(report()));await flush();
 const button=s.nodes['vf-rows'].children[0].children[5].children[0];button.onclick();s.move('live');s.requests[3].resolve(response({feedback:{id:'a'.repeat(32),queue:'8001',evidence:{},status:'new',note:'private',version:1},assignees:[],capabilities:{play:true,download:true}}));await flush();assert.equal(s.nodes['vf-detail'].hidden,true);
 s=setup('live');assert.equal(s.requests.length,0);s.move('voice-feedback');s.requests[0].resolve(response(report()));await flush();s.nodes['vf-file'].files=[{size:100}];s.nodes['vf-upload-queue'].value='8001';
 const pending=s.nodes['vf-upload'].onsubmit({preventDefault(){}});assert.equal(s.requests[1].options.headers['Idempotency-Key'],'idempotent-key');assert.equal(s.requests[1].options.headers['X-CSRF-Token'],'test');s.requests[1].resolve({ok:false});await pending;assert.equal(s.nodes['vf-upload-button'].disabled,false);
 console.log('PASS voice feedback: actual script restore/dedupe, XSS text, leave abort/clear, stale detail, manual upload CSRF and idempotency');
})().catch(error=>{console.error(error);process.exitCode=1;});
