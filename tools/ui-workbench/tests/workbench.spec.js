import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
import {existsSync} from 'node:fs';

test.beforeEach(async({page})=>{
  await page.route('**/*',route=>{const host=new URL(route.request().url()).hostname;return ['127.0.0.1','localhost'].includes(host)?route.continue():route.abort('blockedbyclient');});
});
for(const locale of ['fa','en'])for(const theme of ['light','dark'])for(const width of [390,1280]){
  test(`${locale} ${theme} ${width}: accessible responsive baseline`,async({page})=>{
    await page.setViewportSize({width,height:960});await page.emulateMedia({reducedMotion:'reduce'});
    const errors=[];page.on('pageerror',error=>errors.push(error.message));page.on('response',response=>{if(response.status()>=400)errors.push(`${response.status()} ${response.url()}`);});
    await page.goto(`/?locale=${locale}&theme=${theme}`);await page.evaluate(()=>document.fonts.ready);
    expect(await page.evaluate(()=>document.fonts.check('16px Vazirmatn'))).toBeTruthy();
    await expect(page.locator('.sq-workbench')).toHaveAttribute('dir',locale==='fa'?'rtl':'ltr');
    await expect(page.locator('tbody tr')).toHaveCount(6);
    expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
    const result=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze();expect(result.violations).toEqual([]);
    if(process.env.UI_SKIP_VISUAL==='1') await page.screenshot({path:test.info().outputPath(`${locale}-${theme}-${width}.png`),fullPage:true});
    else await expect(page).toHaveScreenshot(`${locale}-${theme}-${width}.png`,{fullPage:true});
    expect(errors).toEqual([]);
  });
}
test('filters, contextual definition, validation and success feedback',async({page})=>{
  await page.goto('/?locale=en');await page.getByLabel('Queue filter').selectOption('8001');await expect(page.locator('tbody tr')).toHaveCount(3);
  await page.locator('summary').first().click();await expect(page.getByText('Answered visits to a queue', {exact:false}).first()).toBeVisible();
  await page.getByRole('button',{name:'Save',exact:true}).click();await expect(page.getByText('Enter a name')).toBeVisible();await expect(page.getByLabel('Display name')).toBeFocused();
  await page.getByLabel('Display name').fill('Example Agent');await page.getByRole('button',{name:'Save',exact:true}).click();await expect(page.getByText('Saved',{exact:true})).toBeVisible();
});
test('loading, empty, error/retry, denied, disabled and keyboard skip link',async({page})=>{
  await page.goto('/?locale=en');await page.keyboard.press('Tab');await expect(page.getByRole('link',{name:'Skip to content'})).toBeFocused();await page.keyboard.press('Enter');await expect(page.locator('main')).toBeFocused();
  for(const [state,label] of [['loading','Loading'],['empty','No data available'],['denied','You do not have permission to view this'],['disabled','Disabled'],['error','Unable to load data']]){
    await page.getByRole('combobox',{name:'Display state',exact:true}).selectOption(state);await expect(page.locator('.sq-state-panel p')).toHaveText(label);await expect(page.locator('table')).toHaveCount(0);
    if(state==='disabled')await expect(page.getByRole('button',{name:'Save'})).toBeDisabled();
    expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations).toEqual([]);
  }
  await page.getByRole('button',{name:'Retry'}).click();await expect(page.locator('table')).toBeVisible();
});
test('built Storybook renders a real component story',async({page})=>{
  test.skip(!existsSync(new URL('../storybook-static/iframe.html',import.meta.url)),'Run build-storybook first to test the built story.');
  await page.goto('/storybook-static/iframe.html?id=sanequeue-components--button&viewMode=story');
  await expect(page.getByRole('button',{name:'ذخیره',exact:true})).toBeVisible();
});

test('built Storybook renders shared reporting charts and Persian calendar',async({page})=>{
  test.skip(!existsSync(new URL('../storybook-static/iframe.html',import.meta.url)),'Run build-storybook first.');
  const errors=[];page.on('pageerror',error=>errors.push(error.message));
  await page.goto('/storybook-static/iframe.html?id=sanequeue-reporting--charts-and-persian-calendar&viewMode=story');
  await expect(page.locator('.sq-report-design')).toBeVisible();
  await expect(page.locator('.sq-chart-viewport svg')).toHaveCount(3);
  await page.locator('.sq-date-trigger').first().click();
  await expect(page.getByRole('dialog')).toBeVisible();
  expect(errors).toEqual([]);
});
