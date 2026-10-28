import {test,expect} from '@playwright/test';
import AxeBuilder from '@axe-core/playwright';
test.use({timezoneId:'America/Los_Angeles'});

async function open(page,locale='fa',theme='light',width=1440){
 await page.setViewportSize({width,height:1000});
 await page.addInitScript(()=>{const Original=Date;const fixed=Original.parse('2026-10-28T10:00:00Z');globalThis.Date=class extends Original{constructor(...args){super(...(args.length?args:[fixed]));}static now(){return fixed;}};});
 await page.route('**/*',route=>['127.0.0.1','localhost'].includes(new URL(route.request().url()).hostname)?route.continue():route.abort());
 await page.goto(`/?view=report-design&locale=${locale}&theme=${theme}`);await page.waitForFunction(()=>window.__reportDesignReady===true);await page.evaluate(()=>document.fonts.ready);
}
for(const locale of ['fa','en'])for(const theme of ['light','dark'])for(const width of [390,1440]){
 test(`report design ${locale} ${theme} ${width}`,async({page})=>{
  const errors=[];page.on('pageerror',error=>errors.push(error.message));await open(page,locale,theme,width);
  await expect(page.locator('.sq-report-chart')).toHaveCount(3);await expect(page.locator('#design-trend svg')).toBeVisible();
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations).toEqual([]);
  if(process.env.UI_SKIP_VISUAL==='1')await page.screenshot({path:test.info().outputPath('report-design.png'),fullPage:true});
  else await expect(page).toHaveScreenshot(`report-design-${locale}-${theme}-${width}.png`,{fullPage:true});
  await page.locator('.sq-date-trigger').first().click();const dialog=page.getByRole('dialog');await expect(dialog).toBeVisible();
  expect((await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa','wcag21aa']).analyze()).violations).toEqual([]);
  if(process.env.UI_SKIP_VISUAL==='1')await page.screenshot({path:test.info().outputPath('calendar.png')});
  else await expect(page).toHaveScreenshot(`calendar-${locale}-${theme}-${width}.png`);
  await page.keyboard.press('Escape');await expect(dialog).not.toBeVisible();await expect(page.locator('.sq-date-trigger').first()).toBeFocused();expect(errors).toEqual([]);
 });
}
test('Persian calendar keyboard, canonical ISO and presets in a different timezone',async({page})=>{
 await open(page,'fa','light',390);const from=page.locator('[name=from]'),to=page.locator('[name=to]'),trigger=page.locator('.sq-date-trigger').first();
 await trigger.click();await page.keyboard.press('ArrowRight');await page.keyboard.press('Enter');await expect(from).toHaveValue('2026-08-31');await expect(trigger).toBeFocused();
 await trigger.click();await page.keyboard.press('PageDown');await page.keyboard.press('Enter');await expect(from).toHaveValue('2026-10-01');
 await expect(page.locator('.sq-range-summary')).toContainText('تاریخ پایان');
 await page.getByRole('button',{name:'۷ روز اخیر',exact:true}).click();await expect(from).toHaveValue('2026-10-22');await expect(to).toHaveValue('2026-10-28');
 await page.getByRole('button',{name:'ماه شمسی قبل',exact:true}).click();await expect(from).toHaveValue('2026-09-23');await expect(to).toHaveValue('2026-10-22');
 await page.getByRole('button',{name:'نمایش گزارش',exact:true}).click();await expect(page.locator('#design-trend svg')).toBeVisible();
});
test('invalid native fallback remains focusable and prevents an invalid report',async({page})=>{
 await open(page);await page.locator('.sq-date-native summary').first().click();await page.locator('[name=from]').fill('');await page.getByRole('button',{name:'نمایش گزارش',exact:true}).click();
 await expect(page.locator('[name=from]')).toBeFocused();await expect(page.locator('.sq-range-summary')).toContainText('تاریخ آغاز');await expect(page.locator('#design-trend svg')).toHaveCount(0);
});
test('direct Persian month and year browsing commits only the selected civil day',async({page})=>{
 await open(page);const from=page.locator('[name=from]');await page.locator('.sq-date-trigger').first().click();const dialog=page.getByRole('dialog');
 await dialog.getByRole('combobox',{name:'سال',exact:true}).selectOption('1405');await dialog.getByRole('combobox',{name:'ماه',exact:true}).selectOption('1');await expect(from).toHaveValue('2026-09-01');
 await dialog.locator('[data-iso="2026-03-21"]').click();await expect(from).toHaveValue('2026-03-21');
 await page.locator('.sq-date-trigger').first().click();await dialog.getByRole('combobox',{name:'سال',exact:true}).selectOption('1403');await dialog.getByRole('combobox',{name:'ماه',exact:true}).selectOption('12');
 await dialog.locator('[data-iso="2025-03-20"]').click();await expect(from).toHaveValue('2025-03-20');await expect(page.locator('.sq-range-summary')).toContainText('۳۶۶');
});
test('chart keyboard, paging, live theme and real SVG/PNG downloads',async({page})=>{
 await open(page);
 for(const [name,value] of [['from','2026-07-31'],['to','2026-10-28']]){const input=page.locator(`[name=${name}]`),details=input.locator('..');await details.locator('summary').click();await input.fill(value);await details.locator('summary').click();}
 await page.getByRole('button',{name:'نمایش گزارش',exact:true}).click();const chart=page.locator('#design-trend');await expect(chart.locator('.sq-chart-navigation')).toContainText('۶۰');await chart.getByRole('button',{name:'بعدی',exact:true}).click();await expect(chart.locator('.sq-chart-navigation')).toContainText('۶۱');await expect(chart.getByRole('button',{name:'قبلی',exact:true})).toBeFocused();
 const point=chart.locator('[role=img][tabindex="0"]').first();await point.focus();await page.keyboard.press('ArrowRight');await expect(chart.locator('.sq-chart-tooltip')).not.toBeEmpty();await page.keyboard.press('Escape');
 await page.getByRole('button',{name:'تغییر تم',exact:true}).click();await expect(page.locator('html')).toHaveAttribute('data-theme','dark');await expect(chart.locator('svg')).toBeVisible();
 await expect(chart.locator('.sq-chart-navigation')).toContainText('۶۱');const svgDownload=page.waitForEvent('download');await chart.getByRole('button',{name:'دریافت SVG',exact:true}).click();const svg=await svgDownload;await svg.saveAs(test.info().outputPath('chart.svg'));
 const pngDownload=page.waitForEvent('download');await chart.getByRole('button',{name:'دریافت PNG',exact:true}).click();const png=await pngDownload;await png.saveAs(test.info().outputPath('chart.png'));
});
test('existing charts adapt when the viewport changes without reloading',async({page})=>{
 await open(page,'fa','dark',1440);await page.setViewportSize({width:390,height:900});
 await expect.poll(()=>page.locator('#design-trend svg').getAttribute('viewBox')).toMatch(/^0 0 (?:3\d\d|4\d\d) /);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
 await expect(page.locator('#design-trend .sq-chart-legend')).toBeVisible();
});
test('unknown, empty and invalid chart states do not invent zero data',async({page})=>{
 await open(page);await page.evaluate(()=>window.SaneQueueReportCharts.render(document.getElementById('design-trend'),{title:'Fixture',labels:['Zero','Unknown'],series:[{label:'Wait',values:[0,null]}]}));
 const chart=page.locator('#design-trend');await chart.locator('summary').click();await expect(chart.locator('tbody tr').nth(0)).toContainText('۰');await expect(chart.locator('tbody tr').nth(1)).toContainText('نامعلوم');
 await page.evaluate(()=>window.SaneQueueReportCharts.render(document.getElementById('design-trend'),{title:'Fixture',labels:[],series:[{label:'Wait',values:[]}]}));await expect(chart.locator('svg')).toHaveCount(0);await expect(chart).toContainText('داده');
 await page.evaluate(()=>window.SaneQueueReportCharts.render(document.getElementById('design-trend'),{title:'Fixture',labels:['Invalid'],series:[{label:'Wait',values:[-1]}]}));await expect(chart.locator('svg')).toHaveCount(0);await expect(chart).toContainText('معتبر نیست');
});
