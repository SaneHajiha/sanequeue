import {test,expect} from '@playwright/test';
import {resolve} from 'node:path';
if(process.env.UI_CHROMIUM_EXECUTABLE)test.use({launchOptions:{executablePath:process.env.UI_CHROMIUM_EXECUTABLE}});

for(const locale of ['fa','en']) for(const width of [390,1440]) {
 test(`background summary ${locale} ${width}`,async({page})=>{
  await page.setViewportSize({width,height:900});
  await page.goto('/');
  await page.setContent(`<html lang="${locale}"><body data-view="reports">
    <script id="ops-config" type="application/json">{"csrf":"token"}</script>
    <form id="history-filters"><input name="from" value="2026-10-01"><input name="to" value="2026-10-28"><select name="queue"><option value="8001">8001</option></select></form>
    <section id="history-agent-rankings-section"><section id="agent-summary-jobs">
    <form id="agent-summary-job-form"><input name="min_samples" type="number" min="1" max="100" value="1"><input name="top" type="number" min="1" max="20" value="10"><button id="agent-summary-job-create">Create</button></form>
    <button id="agent-summary-job-refresh">Refresh</button><p id="agent-summary-job-feedback"></p><div id="agent-summary-job-list"></div>
    <section id="agent-summary-job-result" hidden><p id="agent-summary-job-period"></p><p id="agent-summary-job-source"></p>
    <div id="agent-summary-job-answers-chart"></div><div id="agent-summary-job-answers-table"></div><div id="agent-summary-job-talk-chart"></div><div id="agent-summary-job-talk-table"></div><div id="agent-summary-job-presence"></div></section>
    </section></section></body></html>`);
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  const job={id:'abc',state:'completed',start:1790800200,end:1793219400,updated:1793219400,progress:3,can_download:true};
  const rank={state:'partial',unresolved_answered_count:2,rows:[{rank:1,agent:'PJSIP/100',value:3,answered_count:3,talk_known_count:3}]};
  const result={start:job.start,end:job.end,source_watermark:20,projection_version:10,snapshot:{visits:{sequence:3},activity:{sequence:4}},rankings:{answered_count:rank,avg_queue_talk_seconds:rank},presence:[{agent:'PJSIP/100',observed_seconds:30,unique_on_duty_seconds:20,unique_on_call_seconds:10,unique_paused_seconds:0,explicit_acw_seconds:null,coverage_complete:false}]};
  await page.route('**/api/history/agent-summary-jobs**',route=>route.fulfill({json:route.request().url().endsWith('/result')?{result}:{jobs:[job]}}));
  await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/report-charts.js')});
  await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/agent-summary-jobs.js')});
  await page.locator('#agent-summary-job-refresh').click();
  await page.locator('#agent-summary-job-list button').first().click();
  await expect(page.locator('#agent-summary-job-result')).toBeVisible();
  await expect(page.locator('#agent-summary-job-answers-chart svg')).toBeVisible();
  await expect(page.locator('#agent-summary-job-talk-chart svg')).toBeVisible();
  await expect(page.locator('#agent-summary-job-presence')).toContainText('PJSIP/100');
  await expect(page.locator('#agent-summary-job-presence')).toContainText('—');
  await expect(page.locator('#agent-summary-job-answers-table')).toContainText(locale==='fa'?'رتبه‌بندی کامل نیست':'ranking is incomplete');
  await page.screenshot({path:test.info().outputPath('agent-summary.png'),fullPage:true});
  await page.locator('[name=from]').fill('2026-10-02');
  await expect(page.locator('#agent-summary-job-result')).toBeHidden();
  expect(errors).toEqual([]);
 });
}
