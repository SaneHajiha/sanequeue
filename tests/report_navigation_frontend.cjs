/* Report picker keeps authorised destinations, families and section visibility. */
'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict');
function node(tag){return {tag,children:[],dataset:{},textContent:'',hidden:false,listeners:{},classList:{contains:()=>true,toggle(){}},append(...items){this.children.push(...items);},replaceChildren(...items){this.children=items;},addEventListener(type,fn){this.listeners[type]=fn;},setAttribute(){},removeAttribute(){}};}
const sections=new Map(['history-summary-section','history-cdr-section','history-agent-rankings-section','history-builder-section'].map(id=>[id,node('section')]));
const local=node('nav'),report=node('report'),nav=node('main-nav'),body=node('body');body.dataset.view='reports';
const overview=node('button');overview.textContent='Overview';overview.dataset.view='reports';overview.closest=()=>null;overview.click=()=>{};
const shortcuts=[['history-cdr-section','pbx'],['history-agent-rankings-section','contact-center'],['history-builder-section','shared']].map(([target,family])=>{const button=node('button');button.textContent=target;button.dataset={moduleTarget:target,moduleView:'reports'};button.closest=selector=>selector==='[data-report-family]'?{dataset:{reportFamily:family}}:null;button.click=()=>{};return button;});
nav.querySelectorAll=selector=>selector==='.nav-module'?[]:selector.includes('data-module-view')?shortcuts:selector==='button[data-view]'?[overview]:[];
nav.querySelector=selector=>selector==='button[data-view="reports"]'?overview:null;
report.querySelector=selector=>selector==='.history-navigation'?local:sections.get(selector.slice(1));
report.querySelectorAll=()=>[...sections.values()];report.contains=section=>[...sections.values()].includes(section);
const document={body,documentElement:{lang:'en'},querySelector:selector=>selector==='.module-navigation'?nav:null,getElementById:id=>id==='reports-view'?report:sections.get(id)||null,createElement:node};
vm.runInNewContext(fs.readFileSync('qpanel/themes/qpanel/static/js/navigation.js','utf8'),{document,JSON,Map,MutationObserver:class{observe(){}},sessionStorage:{getItem:()=>null}});
const picker=local.children[0].children[0];assert.equal(picker.id,'history-section-picker');
assert.deepEqual(picker.children.map(group=>group.label),['Contact center & queues','PBX','Shared tools']);
assert.equal(picker.children.reduce((sum,group)=>sum+group.children.length,0),4);
assert.ok(picker.children[0].children.some(option=>option.value==='history-agent-rankings-section'));
assert.equal(sections.get('history-summary-section').hidden,false);assert.equal(sections.get('history-cdr-section').hidden,true);
console.log('report navigation frontend: authorised grouped picker and single-section visibility passed');
