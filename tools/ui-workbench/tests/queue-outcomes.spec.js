import {test,expect} from '@playwright/test';
import {resolve} from 'node:path';
if(process.env.UI_CHROMIUM_EXECUTABLE)test.use({launchOptions:{executablePath:process.env.UI_CHROMIUM_EXECUTABLE}});
for(const locale of ['fa','en'])for(const kind of ['answered','unanswered'])test(`queue outcomes ${locale} ${kind}`,async({page})=>{
 await page.goto('/');await page.setContent(`<html lang="${locale}"><body data-view="reports"><form id="history-filters"><input name="from" value="2026-10-01"><input name="to" value="2026-10-02"><select name="queue"><option value="8001">8001</option></select></form><section data-queue-outcome="${kind}"><button data-outcome-run>Run</button><p data-outcome-feedback></p><div data-outcome-summary></div><div data-outcome-chart></div><div data-outcome-queues></div><div data-outcome-days></div><div data-outcome-reasons></div></section></body></html>`);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));const metrics={visits:10,answered:4,unanswered:4,unresolved:2,abandoned:1,exitwithtimeout:1,exitwithkey:1,exitempty:1,average_answered_wait_seconds:4,average_unanswered_wait_seconds:10,answered_wait_samples:4,unanswered_wait_samples:4};
 await page.route('**/api/history/queue-outcomes?**',route=>route.fulfill({json:{state:'available',totals:metrics,missing_entry_visits:1,queues:[{queue:'8001',...metrics}],hours:[{hour:8,...metrics}],days:[{day:'2026-10-01',...metrics}]}}));
 await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/report-charts.js')});await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/report-periods.js')});await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/queue-outcomes.js')});
 await page.locator('[data-outcome-run]').click();await expect(page.locator('[data-outcome-chart] svg')).toBeVisible();await expect(page.locator('[data-outcome-queues]')).toContainText('8001');
 if(kind==='unanswered')await expect(page.locator('[data-outcome-reasons] tbody tr')).toHaveCount(4);
 await page.evaluate(()=>document.dispatchEvent(new Event('sanequeue:reports-loaded')));await expect(page.locator('[data-outcome-chart] svg')).toBeVisible();
 await page.locator('[name=from]').fill('2026-10-02');await expect(page.locator('[data-outcome-queues] table')).toHaveCount(0);expect(errors).toEqual([]);
});
test('busy outcome calculation is announced and can be retried',async({page})=>{
 await page.goto('/');await page.setContent('<html lang="en"><body data-view="reports"><form id="history-filters"><input name="from" value="2026-10-01"><input name="to" value="2026-10-02"><select name="queue"><option value="8001">8001</option></select></form><section data-queue-outcome="answered"><button data-outcome-run>Run</button><p data-outcome-feedback></p><div data-outcome-summary></div><div data-outcome-chart></div><div data-outcome-queues></div><div data-outcome-days></div></section></body></html>');
 await page.route('**/api/history/queue-outcomes?**',route=>route.fulfill({status:429,json:{error:'queue_outcomes_busy'}}));await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/queue-outcomes.js')});await page.locator('[data-outcome-run]').click();await expect(page.locator('[data-outcome-feedback]')).toContainText('Another calculation');await expect(page.locator('[data-outcome-run]')).toBeEnabled();
});
