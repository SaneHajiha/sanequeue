import {test,expect} from '@playwright/test';
import {resolve} from 'node:path';
if(process.env.UI_CHROMIUM_EXECUTABLE)test.use({launchOptions:{executablePath:process.env.UI_CHROMIUM_EXECUTABLE}});
for(const locale of ['fa','en'])test(`distinct callers ${locale}`,async({page})=>{
 await page.goto('/');await page.setContent(`<html lang="${locale}"><body data-view="reports"><form id="history-filters"><input name="from" value="2026-10-01"><input name="to" value="2026-10-02"><select name="queue"><option value="8001">8001</option></select></form><section id="history-summary-section"><button id="unique-callers-run">Calculate</button><p id="unique-callers-feedback"></p><div id="unique-callers-result"></div><div id="unique-callers-chart"></div><div id="unique-callers-table"></div></section></body></html>`);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.route('**/api/history/unique-callers?**',route=>route.fulfill({json:{state:'available',total_unique:1,known_number_visits:10,unknown_number_visits:1,missing_entry_visits:0,by_day:[{day:'2026-10-01',unique_numbers:1,known_number_visits:10}],by_queue:[{queue:'8001',unique_numbers:1,known_number_visits:10}]}}));
 await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/report-charts.js')});await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/report-periods.js')});await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/unique-callers.js')});
 await page.locator('#unique-callers-run').click();await expect(page.locator('#unique-callers-chart svg')).toBeVisible();await expect(page.locator('#unique-callers-table table')).toHaveCount(2);await expect(page.locator('#unique-callers-table')).toContainText('8001');
 await expect(page.locator('#unique-callers-table table').first()).not.toContainText('2026-10-01');
 await page.evaluate(()=>document.dispatchEvent(new Event('sanequeue:reports-loaded')));await expect(page.locator('#unique-callers-table table')).toHaveCount(2);await expect(page.locator('#unique-callers-chart svg')).toBeVisible();
 await page.locator('[name=from]').fill('2026-10-02');await expect(page.locator('#unique-callers-table table')).toHaveCount(0);expect(errors).toEqual([]);
});
