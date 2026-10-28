/* Execute the real enhancement against a minimal DOM and controllable network. */
const assert=require('node:assert/strict'),fs=require('node:fs'),vm=require('node:vm');
class Element{
 constructor(tag='div',text=''){this.tagName=tag;this.children=[];this._text=text;this.dataset={};this.isConnected=true;this.listeners={};}
 set textContent(v){this.children=[];this._text=String(v);}get textContent(){return this._text+this.children.map(x=>x.textContent).join('');}
 append(...xs){this.children.push(...xs);}replaceChildren(...xs){this.children=xs;this._text='';}setAttribute(){}addEventListener(k,f){this.listeners[k]=f;}querySelectorAll(){return [];}closest(){return this;}
}
const dialog=new Element();dialog.open=true;const body=new Element();body.dataset.view='reports';const config=new Element('script','{"csrf":"synthetic"}');
const document={body,documentElement:{lang:'en'},listeners:{},createElement:t=>new Element(t),getElementById:id=>id==='history-detail'?dialog:id==='ops-config'?config:null,addEventListener(k,f){this.listeners[k]=f;}};
const requests=[];const context={document,MutationObserver:class{observe(){}},AbortController,crypto:require('node:crypto').webcrypto,Uint8Array,Map,encodeURIComponent,fetch:(path,options)=>new Promise(resolve=>requests.push({path,options,resolve}))};
vm.runInNewContext(fs.readFileSync('qpanel/themes/qpanel/static/js/generative-reports.js','utf8'),context);
const host=new Element(),open=new Element('button');open.dataset.generativeSource='a'.repeat(32);open.nextElementSibling=host;
const tick=()=>new Promise(r=>setImmediate(r));
function reply(request,data,status=200){request.resolve({redirected:false,ok:status===200,headers:{get:()=> 'application/json'},json:async()=>data});}
function all(node){return [node,...node.children.flatMap(all)];}function button(text){const found=all(host).find(n=>n.tagName==='button'&&n.textContent===text);assert.ok(found,text);return found;}
(async()=>{
 document.listeners.click({target:open});assert.equal(requests.length,1);
 const job={id:'b'.repeat(32),state:'completed'};
 reply(requests[0],{enabled:true,jobs:[job]});await tick();
 button('Show analysis and evidence').onclick();reply(requests[1],{job:{...job,result:{analysis:{summary:[{text:'<img src=x onerror=alert(1)>',evidence:['s1']}],themes:[],suggestions:[]},evidence:{s1:{start:0,end:2,text:'Synthetic quoted source'}},engine:{model:'synthetic'}}}});await tick();
 assert.ok(host.textContent.includes('<img src=x onerror=alert(1)>'));
 assert.equal(all(host).filter(n=>n.tagName==='a')[0].href,'#gen-evidence-'+job.id+'-s1');
 button('Refresh status').onclick();assert.ok(!host.textContent.includes('Synthetic quoted source'),'clear private content before new authorization');
 reply(requests[2],{error:'denied'},403);await tick();assert.ok(!host.textContent.includes('Synthetic quoted source'));assert.ok(host.textContent.includes('access is unavailable'));
 document.listeners.click({target:open});const pending=requests[3];dialog.open=false;dialog.listeners.close();assert.ok(pending.options.signal.aborted);reply(pending,{enabled:true,jobs:[job]});await tick();assert.equal(host.textContent,'');
 console.log('generative frontend: result escaping, local citations, denied refresh clearing, close abort and late-response guards passed');
})().catch(error=>{console.error(error);process.exitCode=1;});
