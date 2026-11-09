// Run against an isolated demo_monitor.py process using its generated demo password.
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const path = require('node:path');
const { chromium } = require('playwright');

const { SANEQUEUE_BROWSER_URL, SANEQUEUE_DEMO_PASSWORD, SANEQUEUE_CHROMIUM, SANEQUEUE_SCREENSHOTS } = process.env;
const baseline = process.argv.includes('--capture-baseline');

async function waitText(page, selector, expected) {
    await page.waitForFunction(({ selector, expected }) =>
        document.querySelector(selector)?.textContent.trim() === expected,
    { selector, expected });
}

async function capture(page, filename) {
    if (SANEQUEUE_SCREENSHOTS) {
        await fs.mkdir(SANEQUEUE_SCREENSHOTS, { recursive: true });
        await page.screenshot({ path: path.join(SANEQUEUE_SCREENSHOTS, filename) });
    }
}

async function main() {
    const url = new URL(SANEQUEUE_BROWSER_URL);
    assert.equal(url.hostname, '127.0.0.1');
    assert.ok(SANEQUEUE_DEMO_PASSWORD);
    const browser = await chromium.launch({ executablePath: SANEQUEUE_CHROMIUM });
    try {
        const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
        await page.goto(new URL('/operations', url).href);
        await page.locator('input[name=username]').fill('admin');
        await page.locator('input[name=pw]').fill(SANEQUEUE_DEMO_PASSWORD);
        await page.locator('button[type=submit]').click();
        await page.locator('#language-toggle').click();
        await page.waitForFunction(() => document.documentElement.lang === 'en');
        assert.equal(await page.locator('html').getAttribute('dir'), 'ltr');
        await page.locator('#theme-toggle').click();
        await waitText(page, '#metrics .metric.danger b', baseline ? '0' : '—');
        assert.equal(await page.locator('body').evaluate(element => element.classList.contains('dark')), false);
        assert.equal(await page.locator('nav button[data-view]').count(), 18);
        await capture(page, baseline ? '01-baseline-en-light-desktop.png' : '02-fixed-en-light-desktop.png');
        if (baseline) return;

        const abandon = '#metrics .metric.danger b';
        const level = '#metrics .metric.sla b';
        const firstCard = page.locator('#queue-cards .queue-overview-card').first();
        const wallboardAbandon = '#wallboard-summary > div:last-child strong';
        assert.equal(await firstCard.locator('.queue-overview-kpis b').nth(1).textContent(), '—');
        assert.equal(await page.locator(wallboardAbandon).textContent(), '—');
        await firstCard.locator('.queue-summary-open').click();
        await waitText(page, '#qs-metrics .summary-metric--2 b', '—');
        await page.keyboard.press('Escape');
        assert.equal(await page.locator('#queue-summary-dialog').isVisible(), false);

        const names = await page.locator('#queue-filter option').evaluateAll(options =>
            options.map(option => option.value).filter(Boolean));
        assert.equal(names.length, 3);
        let observedToday = { available: true, queues: {} };
        await page.route('**/api/operations', async route => {
            const response = await route.fetch();
            const data = await response.json();
            data.observed_today = observedToday;
            await route.fulfill({ response, json: data });
        });
        const refresh = async () => {
            const [response] = await Promise.all([
                page.waitForResponse(response => new URL(response.url()).pathname === '/api/operations'),
                page.locator('#refresh').click(),
            ]);
            assert.equal(response.status(), 200);
        };
        await refresh();
        await waitText(page, abandon, '0');
        await waitText(page, level, '—');

        observedToday = {
            available: true,
            queues: {
                [names[0]]: { answered: 1, abandoned: 0, sla_known: 1, sla_met: 1, wait_seconds: 10 },
                [names[1]]: { answered: 0, abandoned: 1, sla_known: 0, sla_met: 0 },
            },
        };
        await refresh();
        await waitText(page, abandon, '1');
        await waitText(page, level, '50%');
        await page.locator('#queue-filter').selectOption(names[1]);
        await waitText(page, level, '0%');
        await waitText(page, '#queue-cards .queue-service-ring b', '0%');
        await page.locator('#queue-filter').selectOption('');
        observedToday.queues[names[2]] = { answered: 1, abandoned: 0, sla_known: 0, sla_met: 0 };
        await refresh();
        await waitText(page, level, '—');

        await page.unroute('**/api/operations');
        await refresh();
        await waitText(page, abandon, '—');
        await page.locator('#language-toggle').click();
        await page.waitForFunction(() => document.documentElement.lang === 'fa');
        assert.equal(await page.locator('html').getAttribute('dir'), 'rtl');
        await page.locator('#theme-toggle').click();
        await page.setViewportSize({ width: 390, height: 844 });
        await waitText(page, abandon, '—');
        assert.equal(await page.locator('body').evaluate(element => element.classList.contains('dark')), true);
        assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
        await capture(page, '03-fixed-fa-dark-mobile.png');
        await page.locator('#view-jump').selectOption('wallboard');
        await waitText(page, wallboardAbandon, '—');
        assert.equal(await page.locator('#wallboard-view').isVisible(), true);
        await capture(page, '04-fixed-fa-dark-wallboard-mobile.png');
        console.log('Passed: missing coverage, observed zero, abandon-only and weighted service level, unknown threshold, queue dialog, wallboard, two locales and themes.');
    } finally {
        await browser.close();
    }
}

main().catch(error => {
    console.error(error);
    process.exitCode = 1;
});
