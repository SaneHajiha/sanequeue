/* Execute the shipped ranking controller with deterministic scoped responses. */
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
const nodes=new Map(),events=new Map(),pending=[],charts=[];let observer;
function node(id){if(!nodes.has(id))nodes.set(id,{id,value:'',hidden:false,textContent:'',children:[],listeners:{},
 append(...items){this.children.push(...items);},replaceChildren(){this.children=[];},setAttribute(){},
 addEventListener(name,fn){this.listeners[name]=fn;},reportValidity(){return true;}});return nodes.get(id);}
const dates={from:{value:'2026-10-01'},to:{value:'2026-10-02'},queue:{value:'8001'}};
const fields={metric:{value:'answered_count'},min_samples:{value:'5'},top:{value:'10'}};
node('history-filters').elements=dates;node('agent-ranking-form').elements=fields;
const document={getElementById:node,createElement:tag=>node('created-'+nodes.size+'-'+tag),documentElement:{lang:'en'},body:{dataset:{view:'reports'}},addEventListener:(name,fn)=>events.set(name,fn)};
vm.runInNewContext(fs.readFileSync('qpanel/themes/qpanel/static/js/agent-rankings.js','utf8'),{
 document,JSON,URLSearchParams,String,Intl,AbortController,
 MutationObserver:class{constructor(fn){observer=fn;}observe(){}},
 window:{SaneQueueReportCharts:{clear(){charts.length=0;},render(host,data){charts.push(data);}}},
 fetch(url,options){return new Promise(resolve=>pending.push({url,options,resolve:data=>resolve({ok:true,redirected:false,headers:{get:()=> 'application/json'},json:async()=>data})}));}
});
const settle=()=>new Promise(resolve=>setImmediate(resolve));
const data={state:'available',metric:'answered_count',rows:[{rank:1,agent:'<img onerror=alert(1)>',value:7,answered_count:7,talk_known_count:6}]};
(async()=>{
 const form=node('agent-ranking-form'),submit=()=>form.onsubmit({preventDefault(){}});
 submit();assert.ok(pending[0].url.includes('queue=8001'));assert.ok(pending[0].url.includes('min_samples=5'));
 pending[0].resolve(data);await settle();assert.equal(charts.length,1);assert.equal(charts[0].series[0].values[0],7);
 const table=node('agent-ranking-table').children[0];assert.equal(table.children[1].children[0].children[1].textContent,data.rows[0].agent,'identity is text, never HTML');
 submit();dates.to.value='2026-10-03';pending[1].resolve(data);await settle();assert.equal(charts.length,0,'stale dates never render');
 submit();document.body.dataset.view='live';observer();assert.equal(pending[2].options.signal.aborted,true);pending[2].resolve(data);await settle();assert.equal(charts.length,0);
 document.body.dataset.view='reports';submit();pending[3].resolve({state:'unavailable',rows:[]});await settle();assert.ok(node('agent-ranking-feedback').textContent.includes('insufficient'));
 console.log('agent ranking frontend: scoped request, exact chart values, safe identity, stale-date/leave guards and unknown state passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
