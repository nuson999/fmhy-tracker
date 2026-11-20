// Local Chromium verification. Set NODE_PATH to an existing Playwright install.
// Assets are served from disk through Playwright routes; no live site is changed.
const { chromium } = require('playwright');
const fs = require('node:fs');
const path = require('node:path');
const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const output = path.join(root, '.cache', 'browser-check');
const baseline = process.argv.includes('--baseline');
const baselineHtml = baseline ? execFileSync('git', ['show', 'HEAD:index.html'], { cwd: root }) : null;
const launch = { headless: true };
if (process.env.CHROME_PATH) launch.executablePath = process.env.CHROME_PATH;

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch(launch);
  try {
    const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, reducedMotion: 'reduce' });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    await page.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.hostname !== 'fmhy.test') return route.abort();
      if (baselineHtml && url.pathname === '/') return route.fulfill({ contentType: 'text/html', body: baselineHtml });
      const file = path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname)));
      if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) return route.fulfill({ status: 404 });
      await route.fulfill({ path: file });
    });
    await page.goto('http://fmhy.test/?starred=0');
    await page.locator('.link').first().waitFor();
    await page.screenshot({ path: path.join(output, baseline ? 'before-desktop.png' : 'after-desktop.png') });
    await page.locator('.monthly-toggle-label').click();
    await page.waitForFunction(() => state.showMonthly && !state.monthlyLoading);
    const metrics = await page.evaluate(() => {
      const samples = { search: [], filter: [], page: [] };
      const measure = (kind, operation) => {
        const start = performance.now();
        operation();
        document.getElementById('commits-container').getBoundingClientRect();
        samples[kind].push(performance.now() - start);
      };
      for (let i = 0; i < 24; i++) {
        measure('search', () => { state.searchQuery = i % 2 ? 'video' : 'github'; state.currentPage = 1; renderCommits(); });
        state.searchQuery = ''; state.currentFilter = 'all'; renderCommits();
        measure('filter', () => setFilter(i % 2 ? 'new' : 'updated'));
        state.currentFilter = 'all'; renderCommits();
        measure('page', () => changePage(i % 2 ? -1 : 1));
      }
      const result = {};
      for (const [kind, values] of Object.entries(samples)) {
        const sorted = values.slice(4).sort((a, b) => a - b);
        result[kind] = { medianMs: sorted[Math.floor(sorted.length / 2)], p95Ms: sorted[Math.ceil(sorted.length * .95) - 1] };
      }
      clearAllFilters();
      return { rows: getRows().length, ...result };
    });
    fs.writeFileSync(path.join(output, baseline ? 'baseline.json' : 'after.json'), JSON.stringify(metrics, null, 2));
    if (!baseline) await verify(page, output);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ mode: baseline ? 'baseline' : 'after', metrics, errors }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

async function verify(page, output) {
  assert.equal(await page.locator('.pagination').count(), 2);
  const top = page.getByRole('navigation', { name: 'Results pages (top)' });
  await top.getByRole('button', { name: 'Page 2', exact: true }).click();
  assert.equal(new URL(page.url()).searchParams.get('page'), '2');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'commits-container');
  await top.getByRole('spinbutton').fill('12');
  await top.getByRole('button', { name: 'Go', exact: true }).click();
  assert.equal(new URL(page.url()).searchParams.get('page'), '12');
  await page.reload();
  await page.waitForFunction(() => state.showMonthly && !state.monthlyLoading);
  assert.equal(await page.evaluate(() => state.currentPage), 12);
  assert.match(await top.innerText(), /Page 12 of/);

  // Filter reset, correct facet counts, and disclosure continuity in a real DOM.
  await page.locator('[data-filter="updated"]').click();
  assert.equal(await page.evaluate(() => state.currentPage), 1);
  const detail = page.locator('.change-details').first();
  const identity = await detail.getAttribute('data-change-id');
  await detail.locator('summary').click();
  await top.getByRole('button', { name: 'Next →', exact: true }).click();
  await top.getByRole('button', { name: '← Previous', exact: true }).click();
  assert.equal(await page.locator('.change-details').first().getAttribute('data-change-id'), identity);
  assert.equal(await page.locator('.change-details').first().evaluate(el => el.open), true);
  await page.locator('.change-details').first().locator('summary').click();
  await top.getByRole('button', { name: 'Next →', exact: true }).click();
  await top.getByRole('button', { name: '← Previous', exact: true }).click();
  assert.equal(await page.locator('.change-details').first().evaluate(el => el.open), false);
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
  assert.equal(await page.evaluate(() => state.showMonthly), true);
  await page.locator('[data-category="video"]').click();
  assert.equal(await page.evaluate(() => document.activeElement.dataset.category), 'video');
  await page.keyboard.press('/');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'search-input');
  await page.keyboard.type('github');
  await page.waitForFunction(() => !document.getElementById('clear-all').disabled && state.searchQuery === 'github');
  await page.waitForTimeout(180); // Exercise the intentional 120 ms debounce.
  assert.equal(new URL(page.url()).searchParams.get('q'), 'github');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'search-input');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'search-clear');
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => state.searchQuery), '');
  await page.getByRole('button', { name: 'Clear filters', exact: true }).click();

  for (const width of [1280, 768, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => window.scrollTo(0, 0));
    const layout = await page.evaluate(() => ({
      width: document.documentElement.clientWidth,
      scrollWidth: document.documentElement.scrollWidth,
      toolbar: getComputedStyle(document.querySelector('.toolbar')).position,
      mobileCategory: getComputedStyle(document.querySelector('.mobile-category')).display,
    }));
    assert.ok(layout.scrollWidth <= layout.width, `horizontal overflow at ${width}: ${JSON.stringify(layout)}`);
    assert.ok(!['fixed', 'sticky'].includes(layout.toolbar));
    if (width < 600) {
      assert.notEqual(layout.mobileCategory, 'none');
      await page.locator('#category-select').focus();
      await page.locator('#category-select').selectOption('video');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'category-select');
      await page.getByRole('button', { name: 'Clear filters', exact: true }).click();
    }
    await page.screenshot({ path: path.join(output, `after-${width}.png`) });
  }
  await page.emulateMedia({ colorScheme: 'dark', reducedMotion: 'reduce' });
  await page.waitForFunction(() => document.documentElement.dataset.theme === 'dark');
  assert.equal(await page.locator('html').getAttribute('data-theme'), 'dark');
  await page.screenshot({ path: path.join(output, 'after-320-dark.png') });

  // Missing archive must keep recent results usable and offer a working retry.
  await page.route('**/monthly_commits.json', route => route.fulfill({ status: 503, body: 'Unavailable' }));
  await page.goto('http://fmhy.test/?starred=0&history=1&page=12');
  await page.locator('#monthly-retry').waitFor({ state: 'visible' });
  assert.equal(await page.evaluate(() => state.showMonthly), false);
  assert.ok(await page.locator('.link').count() > 0);
  assert.equal(await page.evaluate(() => state.currentPage), 1);
  await page.unroute('**/monthly_commits.json');
  await page.getByRole('button', { name: 'Retry history' }).click();
  await page.waitForFunction(() => state.showMonthly && !state.monthlyLoading);
  assert.equal(await page.locator('#monthly-retry').isVisible(), false);
  assert.equal(await page.locator('link[href*="fonts.googleapis"]').count(), 0);

  // Deferred off-screen rows must reveal their actual content when reached.
  await page.locator('.link').last().scrollIntoViewIfNeeded();
  assert.ok(await page.locator('.link').last().locator('.resource-content').isVisible());
  await page.screenshot({ path: path.join(output, 'after-320-bottom-dark.png') });
  await page.locator('.change-details').first().locator('summary').focus();
  await page.keyboard.press('Enter');
  assert.equal(await page.locator('.change-details').first().evaluate(el => el.open), true);
  await page.screenshot({ path: path.join(output, 'after-320-details-dark.png') });

  // A filter selected while an initial archive request is pending wins over
  // the old page in the URL.
  let releaseArchive;
  await page.route('**/monthly_commits.json', async route => {
    await new Promise(resolve => { releaseArchive = resolve; });
    await route.fulfill({ path: path.join(root, 'monthly_commits.json') });
  });
  await page.goto('http://fmhy.test/?starred=0&history=1&page=12');
  await page.waitForFunction(() => state.monthlyLoading);
  await page.locator('[data-filter="new"]').click();
  assert.ok(releaseArchive);
  releaseArchive();
  await page.waitForFunction(() => state.showMonthly && !state.monthlyLoading);
  assert.equal(await page.evaluate(() => state.currentPage), 1);
  assert.equal(await page.evaluate(() => state.currentFilter), 'new');
}
