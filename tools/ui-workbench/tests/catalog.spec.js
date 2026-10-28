import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
for(const locale of ['fa','en'])for(const theme of ['light','dark']){
 test(`module catalog ${locale} ${theme}`,async({page})=>{
  await page.setViewportSize({width:locale==='fa'?390:1280,height:960});
  const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort());
  await page.goto(`/?view=catalog&locale=${locale}&theme=${theme}`);await page.evaluate(()=>document.fonts.ready);
  await expect(page.locator('[data-module-id]')).toHaveCount(37);
  await expect(page.locator('[data-module-id="extension_callback"]')).toBeVisible();
  await page.locator('[data-catalog-state]').selectOption('planned');await expect(page.locator('[data-module-id]')).toHaveCount(13);
  await expect(page.locator('[data-module-id="queue_callback"]')).toBeVisible();
  await page.locator('[data-catalog-state]').selectOption('');await page.locator('[data-catalog-query]').fill('نظرسنجي');await expect(page.locator('[data-module-id="customer_surveys"]')).toBeVisible();
  await page.locator('[data-catalog-query]').fill('<img src=x onerror=alert(1)>');await expect(page.locator('[data-module-id]')).toHaveCount(0);await expect(page.locator('img')).toHaveCount(0);
  await page.locator('[data-catalog-query]').fill('');await page.locator('[data-catalog-pilot]').check();await expect(page.locator('[data-module-id="fax"]')).toHaveCount(0);
  await page.locator('[data-module-id="customer_surveys"] summary').click();await expect(page.locator('[data-module-id="customer_surveys"] .catalog-boundary')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations).toEqual([]);
  await page.screenshot({path:test.info().outputPath(`catalog-${locale}-${theme}.png`),fullPage:true});expect(errors).toEqual([]);
 });
}
