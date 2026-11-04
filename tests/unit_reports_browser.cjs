// Synthetic browser smoke test; pass Playwright module, Chromium and rendered
// fixture paths explicitly. No connection to a PBX or external model is made.
const {chromium}=require(process.argv[2]);
const fs=require('node:fs');
const assert=require('node:assert/strict');
const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.argv[3],args:['--no-sandbox']});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:900}}),errors=[],writes=[],trendBuckets=[],performanceQueries=[],classifications=[],aggregateExports=[],catalog=[];
  page.on('pageerror',e=>errors.push(e.message));
  await page.route('http://sanequeue-fixture.test/**',async route=>{
   const request=route.request(),url=new URL(request.url());
   if(url.pathname==='/')return route.fulfill({contentType:'text/html',body:'<!doctype html><title>fixture</title>'});
   if(/^\/assets\/css\/[a-z0-9-]+\.css$/.test(url.pathname)){
    const name=path.basename(url.pathname),file=path.resolve('qpanel/themes/qpanel/static/css',name);
    if(fs.existsSync(file))return route.fulfill({contentType:'text/css',body:fs.readFileSync(file,'utf8')});
   }
   if(url.pathname.endsWith('/summary')){if(url.pathname==='/api/history/cdr/summary')performanceQueries.push(url.searchParams);return route.fulfill({json:{totals:{segments_started:1,answered_segments:1,unanswered_segments:0,average_duration_seconds:12,known_billsec_sum:10},can_search_numbers:true,endpoints:[{endpoint:'PJSIP/101',segments_started:1,answered_segments:1,unanswered_segments:0,unknown_disposition_segments:0,known_billsec_sum:10,average_answered_billsec:10}]}});}
   if(url.pathname.endsWith('/trend')){trendBuckets.push(url.searchParams.get('bucket'));return route.fulfill({json:{rows:[{period:'2026-10-24',inbound:1,outbound:0,internal:0,unknown:0}]}});}
   if(url.pathname.endsWith('/cdr'))return route.fulfill({json:{rows:[{ts:1792820000,src:'<img src=x>',dst:'***',direction:'inbound',disposition:'ANSWERED',duration:12}],next:null}});
   if(url.pathname.endsWith('/ai'))return route.fulfill({json:{state:'available',metric:'count',direction:'all',value:1,comparison:{start:1792600000,end:1792772800,value:2,difference:-1}}});
   if(url.pathname==='/api/history/cdr/segment/classification'){if(request.method()==='POST'){classifications.push(request.postDataJSON());return route.fulfill({json:{classification:request.postDataJSON()}});}return route.fulfill({json:{classification:{reason:'پشتیبانی',subreason:'نصب',outcome:'حل شد'}}});}
   if(url.pathname==='/api/history/cdr/classification/catalog'){if(request.method()==='POST'){const item=request.postDataJSON();if(item.active)catalog.push({reason:item.reason,subreason:item.subreason});else catalog.splice(catalog.findIndex(x=>x.reason===item.reason&&x.subreason===item.subreason),1);}return route.fulfill({json:{items:catalog}});}
   if(url.pathname==='/api/history/cdr/classification/analysis'){const period=url.searchParams.get('bucket')==='weekday'?'0':'03';return route.fulfill({json:{segments:2,labelled:1,unlabelled:1,rows:[{reason:'پشتیبانی',subreason:'نصب',outcome:'حل شد',count:1},{reason:'',subreason:'',outcome:'',count:1}],timeline:[{period,reason:'پشتیبانی',count:1},{period,reason:'',count:1}]}});}
   if(url.pathname.startsWith('/api/history/cdr/aggregate/')){aggregateExports.push({path:url.pathname,party:url.searchParams.get('party'),origin:url.searchParams.get('origin'),weekdays:url.searchParams.get('weekdays'),bucket:url.searchParams.get('bucket'),csrf:request.headers()['x-csrf-token']});return route.fulfill({contentType:'text/csv',body:'heading\nvalue\n'});}
   if(url.pathname==='/api/organization/tokens')return route.fulfill({json:request.method()==='POST'?{token:'synthetic-only-token',id:'a'.repeat(32),expires:1890000000}:{tokens:[]}});
   if(url.pathname==='/api/organization/access/changes')return route.fulfill({json:{rows:[{at:1792820000,actor:'admin',operation:'grant',target:'a'.repeat(32)}]}});
   if(url.pathname==='/api/organization/access'){
    if(request.method()==='POST'){writes.push(request.postDataJSON());return route.fulfill({json:{id:'b'.repeat(32),revision:2}});}
    return route.fulfill({json:{units:[{id:'a'.repeat(32),name:'مالی',kind:'unit',parent:null}],assignments:[],members:[],grants:[]}});
   }
   return route.fulfill({status:404,body:''});
  });
  await page.goto('http://sanequeue-fixture.test/');
  await page.setContent(fs.readFileSync(process.argv[4],'utf8'),{waitUntil:'domcontentloaded'});
  await page.evaluate(()=>{document.body.dataset.view='reports';document.getElementById('reports-view').hidden=false;document.getElementById('history-unit-section').hidden=false;
   const f=document.getElementById('history-filters');f.elements.from.value='2026-10-24';f.elements.to.value='2026-10-25';});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/report-charts.js')});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/unit-reports.js')});
  await page.click('#unit-report-run');await page.waitForSelector('#unit-report-table tbody tr');
  assert.match(await page.locator('#unit-trend-table').textContent(),/۱/);
  assert.ok(await page.locator('#unit-trend-chart svg').count());
  await Promise.all([page.waitForResponse(r=>r.url().includes('/cdr/trend')&&r.url().includes('bucket=month')),page.selectOption('#unit-trend-bucket','month')]);
  assert.ok(trendBuckets.includes('month'));
  assert.equal(await page.locator('#unit-report-table img').count(),0);
  assert.match(await page.locator('#unit-report-table').innerText(),/<img src=x>/);
  await page.locator('#history-unit-section details').filter({has:page.locator('#unit-ai-form')}).locator('summary').click();
  await page.locator('#unit-ai-form input').fill('تعداد تماس');
  await page.locator('#unit-ai-form button').click();await page.waitForFunction(()=>document.getElementById('unit-ai-feedback').textContent.includes('۱'));
  assert.match(await page.locator('#unit-ai-feedback').textContent(),/دورهٔ قبل/);
  const tokenDetails=page.locator('#history-unit-section details').filter({has:page.locator('#unit-token-form')});
  await tokenDetails.locator('summary').click();await page.locator('#unit-token-form button[type=submit]').click();
  await page.waitForFunction(()=>document.getElementById('unit-token-secret').textContent.includes('synthetic-only-token'));
  await tokenDetails.locator('summary').click();
  await page.waitForFunction(()=>document.getElementById('unit-token-secret').textContent==='');
  assert.deepEqual(errors,[]);
  await page.locator('#history-unit-section').scrollIntoViewIfNeeded();
  if(process.argv[5])await page.screenshot({path:process.argv[5],fullPage:false});
  await page.evaluate(()=>{document.getElementById('history-unit-section').hidden=true;document.getElementById('history-pbx-performance-section').hidden=false;});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/pbx-performance.js')});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/pbx-aggregate-export.js')});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/pbx-endpoint-picker.js')});
  await page.locator('#pbx-performance-run').click();
  await page.waitForFunction(()=>document.getElementById('pbx-performance-table').textContent.includes('PJSIP/101'));
  assert.match(await page.locator('#pbx-performance-table').textContent(),/۱۰۰/);
  assert.ok(await page.locator('#pbx-performance-chart svg').count());
  await page.waitForSelector('#pbx-performance-trend-chart svg');
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/history/cdr/trend')&&r.url().includes('bucket=week')),page.selectOption('#pbx-performance-trend-bucket','week')]);
  assert.ok(trendBuckets.includes('week'));
  await page.locator('#history-pbx-performance-section').scrollIntoViewIfNeeded();
  if(process.argv[5])await page.screenshot({path:process.argv[5].replace(/\.png$/,'-performance.png'),fullPage:false});
  await page.locator('#pbx-performance-filters details.history-cdr-advanced > summary').click();
  await page.locator('#pbx-performance-filters .pbx-endpoint-picker summary').click();
  await page.locator('#pbx-performance-filters .pbx-endpoint-picker input[type=checkbox]').check();
  assert.equal(await page.locator('#pbx-performance-filters [name=endpoint]').inputValue(),'PJSIP/101');
  await page.locator('#pbx-performance-filters .pbx-endpoint-picker input[type=checkbox]').uncheck();
  await page.locator('#pbx-performance-filters [name=party]').fill('101');
  await page.locator('#pbx-performance-filters [name=origin]').fill('101');
  await page.locator('#pbx-performance-filters [name=weekdays]').selectOption('0');
  await Promise.all([page.waitForResponse(r=>r.url().includes('/api/history/cdr/summary')&&r.url().includes('party=101')),page.locator('#pbx-performance-run').click()]);
  assert.equal(performanceQueries.at(-1).get('party'),'101');
  assert.equal(performanceQueries.at(-1).get('origin'),'101');
  assert.equal(performanceQueries.at(-1).get('weekdays'),'0');
  await Promise.all([page.waitForEvent('download'),page.locator('#pbx-performance-export').click()]);
  assert.equal(aggregateExports.at(-1).party,'101');assert.equal(aggregateExports.at(-1).csrf,'fixture-token');
  assert.equal(aggregateExports.at(-1).origin,'101');assert.equal(aggregateExports.at(-1).weekdays,'0');
  await page.evaluate(()=>{const target=document.querySelector('.module-navigation [data-module-target="history-cdr-section"]');target.addEventListener('click',()=>{document.body.dataset.reportTarget='history-cdr-section';document.getElementById('history-pbx-performance-section').hidden=true;document.getElementById('history-cdr-section').hidden=false;});document.getElementById('history-cdr-filters').addEventListener('submit',event=>{event.preventDefault();window.drilldown=Object.fromEntries(new FormData(event.currentTarget));});});
  await page.locator('#pbx-performance-table button[data-endpoint]').click();
  await page.waitForFunction(()=>window.drilldown?.endpoint==='PJSIP/101');
  assert.equal(await page.evaluate(()=>window.drilldown.party),'101');
  assert.equal(await page.evaluate(()=>window.drilldown.origin),'101');
  assert.equal(await page.evaluate(()=>window.drilldown.weekdays),'0');
  await page.evaluate(()=>{document.getElementById('history-pbx-performance-section').hidden=true;document.getElementById('history-cdr-section').hidden=false;const h=document.getElementById('history-cdr-table');h.dataset.classification='true';h.innerHTML='<table><tbody><tr data-cdr-id="segment"><td><details open><summary>جزئیات</summary></details></td></tr></tbody></table>';});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/cdr-reasons.js')});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/cdr-reason-catalog.js')});
  await page.locator('[data-cdr-classify]').click();
  await page.locator('#cdr-reason-editor details summary').click();
  await page.locator('#cdr-catalog-form [name=reason]').fill('پشتیبانی');
  await page.locator('#cdr-catalog-form [name=subreason]').fill('نصب');
  await Promise.all([page.waitForResponse(r=>r.url().includes('/classification/catalog')&&r.request().method()==='POST'),page.locator('#cdr-catalog-form button').click()]);
  await page.waitForFunction(()=>document.getElementById('cdr-catalog-list').textContent.includes('پشتیبانی'));
  assert.equal(await page.locator('#cdr-catalog-reasons option').count(),1);
  await Promise.all([page.waitForResponse(r=>r.url().includes('/classification/catalog')&&r.request().method()==='POST'),page.locator('#cdr-catalog-list button').click()]);
  await page.waitForFunction(()=>!document.getElementById('cdr-catalog-list').textContent.includes('پشتیبانی'));
  await page.waitForFunction(()=>document.querySelector('#cdr-reason-form [name=reason]').value==='پشتیبانی');
  await page.locator('#cdr-reason-form [name=outcome]').fill('پیگیری شد');
  await Promise.all([page.waitForResponse(r=>r.url().includes('/segment/classification')&&r.request().method()==='POST'),page.locator('#cdr-reason-form button[type=submit]').click()]);
  assert.equal(classifications[0].outcome,'پیگیری شد');
  await page.evaluate(()=>{document.getElementById('history-cdr-section').hidden=true;document.getElementById('history-pbx-reasons-section').hidden=false;});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/cdr-reason-analysis.js')});
  await page.locator('#pbx-reason-run').click();await page.waitForFunction(()=>document.getElementById('pbx-reason-table').textContent.includes('پشتیبانی'));
  assert.match(await page.locator('#pbx-reason-table').textContent(),/بدون دلیل/);
  assert.ok(await page.locator('#pbx-reason-chart svg').count());
  assert.ok(await page.locator('#pbx-reason-timeline-chart svg').count());
  await page.locator('#pbx-reason-bucket').selectOption('weekday');
  await page.locator('#pbx-reason-filters details.history-cdr-advanced > summary').click();
  await page.locator('#pbx-reason-filters [name=party]').fill('101');
  await page.locator('#pbx-reason-filters [name=origin]').fill('101');
  await page.locator('#pbx-reason-filters [name=weekdays]').selectOption('0');
  await Promise.all([page.waitForResponse(r=>r.url().includes('/classification/analysis')&&r.url().includes('bucket=weekday')),page.locator('#pbx-reason-run').click()]);
  await page.waitForFunction(()=>document.getElementById('pbx-reason-timeline-table').textContent.includes('شنبه'));
  await page.locator('#history-pbx-reasons-section').scrollIntoViewIfNeeded();
  if(process.argv[5])await page.screenshot({path:process.argv[5].replace(/\.png$/,'-reasons.png'),fullPage:false});
  await Promise.all([page.waitForEvent('download'),page.locator('#pbx-reason-export').click()]);
  assert.match(aggregateExports.at(-1).path,/reasons\/export\.csv$/);assert.equal(aggregateExports.at(-1).party,'101');
  assert.equal(aggregateExports.at(-1).origin,'101');assert.equal(aggregateExports.at(-1).weekdays,'0');
  await Promise.all([page.waitForEvent('download'),page.locator('#pbx-reason-timeline-export').click()]);
  assert.match(aggregateExports.at(-1).path,/reasons-timeline\/export\.csv$/);assert.equal(aggregateExports.at(-1).bucket,'weekday');assert.equal(aggregateExports.at(-1).party,'101');
  await page.evaluate(()=>{document.getElementById('reports-view').hidden=true;document.getElementById('users-view').hidden=false;});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/date-picker.js')});
  await page.addScriptTag({path:path.resolve('qpanel/themes/qpanel/static/js/unit-admin.js')});
  await page.locator('#unit-admin-refresh').click();
  await page.locator('#unit-access-panel details').filter({has:page.locator('#unit-change-refresh')}).locator('summary').click();
  await page.locator('#unit-change-refresh').click();
  await page.waitForFunction(()=>document.getElementById('unit-change-list').textContent.includes('admin'));
  await page.locator('#unit-create-form [name=name]').fill('دفتر مرکزی');
  await page.locator('#unit-create-form button[type=submit], #unit-create-form button:not([type])').click();
  await page.waitForFunction(()=>document.getElementById('unit-admin-feedback').textContent.includes('ثبت شد'));
  assert.equal(writes[0].operation,'create');assert.equal(writes[0].name,'دفتر مرکزی');
  await page.locator('#unit-grant-form [name=username]').fill('manager');
  await Promise.all([page.waitForResponse(r=>r.url().endsWith('/api/organization/access')&&r.request().method()==='POST'),page.locator('#unit-grant-form button').click()]);
  assert.equal(writes[1].operation,'grant');assert.equal(writes[1].username,'manager');
  assert.equal(writes[1].capability,'summary');assert.equal(writes[1].descendants,false);
  assert.deepEqual(errors,[]);
  process.stdout.write('unit report browser smoke passed\n');
 }finally{await browser.close();}
})().catch(error=>{process.stderr.write(String(error.stack||error)+'\n');process.exitCode=1;});
