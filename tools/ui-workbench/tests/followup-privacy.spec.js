import {test,expect} from '@playwright/test';
import {resolve} from 'node:path';
if(process.env.UI_CHROMIUM_EXECUTABLE)test.use({launchOptions:{executablePath:process.env.UI_CHROMIUM_EXECUTABLE}});
test('abandoned follow-up clears private rows and ignores responses after a filter or view change',async({page})=>{
 await page.goto('/');await page.setContent('<html lang="en"><body data-view="reports"><form id="history-filters"><input name="from" value="2026-10-01"><input name="to" value="2026-10-02"><select name="queue"><option value="8001">8001</option></select></form><section id="history-followup-section"><button id="history-followup-run">Run</button><select id="history-followup-days"><option value="7">7</option></select><p id="history-followup-feedback"></p><div id="history-followup-result"></div><button id="history-followup-next" hidden>Next</button></section></body></html>');
 const data={next:null,rows:[{entered:1790812800,queue:'8001',caller:'<private>',first_reentry:null,later_answered:null,window_elapsed:false}]};let release;let call=0;
 await page.route('**/api/history/followup?**',async route=>{call++;if(call===2)await new Promise(resolve=>{release=resolve;});await route.fulfill({json:data}).catch(()=>{});});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.addScriptTag({path:resolve('../../qpanel/themes/qpanel/static/js/followup-reports.js')});
 await page.locator('#history-followup-run').click();await expect(page.locator('#history-followup-result')).toContainText('<private>');await expect(page.locator('#history-followup-result private')).toHaveCount(0);
 await page.locator('#history-followup-run').click();await expect.poll(()=>call).toBe(2);await page.locator('#history-filters [name=from]').fill('2026-10-02');release();await expect(page.locator('#history-followup-result table')).toHaveCount(0);await expect(page.locator('#history-followup-run')).toBeEnabled();
 await page.locator('#history-followup-run').click();await expect(page.locator('#history-followup-result table')).toHaveCount(1);await page.evaluate(()=>{document.body.dataset.view='live';});await expect(page.locator('#history-followup-result table')).toHaveCount(0);expect(errors).toEqual([]);
});
