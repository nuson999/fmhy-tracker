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
const baselineAssets = new Map();
if (baselineHtml) {
  for (const [file] of baselineHtml.toString().matchAll(/static\/dist\/(?:styles\.[a-f0-9]{16}\.css|app\.[a-f0-9]{16}\.js)/g)) {
    baselineAssets.set('/' + file, execFileSync('git', ['show', `HEAD:${file}`], { cwd: root }));
  }
}
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
      if (baselineAssets.has(url.pathname)) return route.fulfill({
        contentType: url.pathname.endsWith('.css') ? 'text/css' : 'text/javascript',
        body: baselineAssets.get(url.pathname),
      });
      const file = path.resolve(root, '.' + (url.pathname === '/' ? '/index.html' : decodeURIComponent(url.pathname)));
      if (!file.startsWith(root + path.sep) || !fs.existsSync(file)) return route.fulfill({ status: 404 });
      await route.fulfill({ path: file });
    });
    await page.goto('http://fmhy.test/?starred=0');
    await page.locator('.link').first().waitFor();
    await page.screenshot({ path: path.join(output, baseline ? 'before-desktop.png' : 'after-desktop.png') });
    await page.setViewportSize({ width: 390, height: 900 });
    await page.screenshot({ path: path.join(output, baseline ? 'before-390.png' : 'after-390-recent.png') });
    await page.setViewportSize({ width: 1280, height: 900 });
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
      setFilter('all'); setCategoryFilter('all');
      return { rows: getRows().length, ...result };
    });
    fs.writeFileSync(path.join(output, baseline ? 'baseline.json' : 'after.json'), JSON.stringify(metrics, null, 2));
    if (!baseline) await verify(page, output);
    assert.deepEqual(errors, []);
    console.log(JSON.stringify({ mode: baseline ? 'baseline' : 'after', metrics, errors }, null, 2));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });

// The page has no "clear filters" control; reset through the same functions its controls call.
async function resetFilters(page) {
  await page.evaluate(() => {
    if (state.searchQuery) clearSearch();
    if (state.showOnlyStarred) toggleStarFilter();
    setFilter('all');
    setCategoryFilter('all');
  });
}

async function verify(page, output) {
  await verifyAccessibility(page);
  assert.equal(await page.locator('.pagination').count(), 1);
  const pager = page.getByRole('navigation', { name: 'Results pages', exact: true });
  await pager.getByRole('button', { name: 'Page 2', exact: true }).click();
  assert.equal(new URL(page.url()).searchParams.get('page'), '2');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'commits-container');
  await pager.getByRole('spinbutton').fill('12');
  await pager.getByRole('button', { name: 'Go', exact: true }).click();
  assert.equal(new URL(page.url()).searchParams.get('page'), '12');
  await page.reload();
  await page.waitForFunction(() => state.showMonthly && !state.monthlyLoading);
  assert.equal(await page.evaluate(() => state.currentPage), 12);
  assert.match(await pager.innerText(), /Page 12 of/);

  // Filter reset, correct facet counts, and disclosure continuity in a real DOM.
  await page.locator('[data-filter="updated"]').click();
  assert.equal(await page.evaluate(() => state.currentPage), 1);
  const detail = page.locator('.change-details').first();
  const identity = await detail.getAttribute('data-change-id');
  await detail.locator('summary').click();
  await pager.getByRole('button', { name: 'Next →', exact: true }).click();
  await pager.getByRole('button', { name: '← Previous', exact: true }).click();
  assert.equal(await page.locator('.change-details').first().getAttribute('data-change-id'), identity);
  assert.equal(await page.locator('.change-details').first().evaluate(el => el.open), true);
  await page.locator('.change-details').first().locator('summary').click();
  await pager.getByRole('button', { name: 'Next →', exact: true }).click();
  await pager.getByRole('button', { name: '← Previous', exact: true }).click();
  assert.equal(await page.locator('.change-details').first().evaluate(el => el.open), false);
  await resetFilters(page);
  await page.locator('[data-category="video"]').click();
  assert.equal(await page.evaluate(() => document.activeElement.dataset.category), 'video');
  await page.keyboard.press('/');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'search-input');
  await page.keyboard.type('github');
  await page.waitForFunction(() => state.searchQuery === 'github');
  await page.waitForTimeout(180); // Exercise the intentional 120 ms debounce.
  assert.equal(new URL(page.url()).searchParams.get('q'), 'github');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'search-input');
  await page.keyboard.press('Tab');
  assert.equal(await page.evaluate(() => document.activeElement.id), 'search-clear');
  await page.keyboard.press('Enter');
  assert.equal(await page.evaluate(() => state.searchQuery), '');
  await resetFilters(page);

  for (const width of [1920, 1280, 768, 390, 320]) {
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
    // Wide screens: the page is a centered column of at most 1120px with equal side margins.
    const column = await page.evaluate(() => document.body.getBoundingClientRect());
    assert.ok(column.width <= 1120, `page column too wide at ${width}: ${column.width}`);
    assert.ok(Math.abs(column.left - (layout.width - column.right)) < 2, `page column not centered at ${width}`);
    // Header is one row (title + actions); the update time sits unwrapped opposite the Historical toggle.
    // A hairline separates the filters from the list heading row at every width.
    const header = await page.evaluate(() => {
      const box = (selector) => document.querySelector(selector).getBoundingClientRect();
      const updated = document.querySelector('.last-updated');
      const borderTop = (selector) => getComputedStyle(document.querySelector(selector)).borderTopWidth;
      return {
        titleTop: box('header h1').top,
        titleBottom: box('header h1').bottom,
        actionsTop: box('.header-rss').top,
        actionsBottom: box('.header-rss').bottom,
        searchTop: box('.search-container').top,
        searchWidth: Math.round(box('.search-container').width),
        searchBeforeTheme: box('.search-container').right <= box('.theme-selector').left,
        categoryLabel: [...document.querySelector('.mobile-category').childNodes].some(node => node.nodeType === 3 && node.textContent.trim()),
        updatedInHeader: Boolean(updated.closest('header')),
        updatedLines: Math.round(updated.getBoundingClientRect().height / parseFloat(getComputedStyle(updated).lineHeight)),
        dividers: [borderTop('.commits')],
        toggleBesideUpdated: document.querySelector('.changes-header').contains(document.getElementById('monthly-toggle')),
        telegram: document.querySelector('.header-telegram') ? box('.header-telegram') : null,
      };
    });
    assert.ok(header.actionsTop < header.titleBottom && header.actionsBottom > header.titleTop, `header actions left the title row at ${width}: ${JSON.stringify(header)}`);
    // Search: 150px before the theme switcher on larger screens; full-width second header row on phones.
    if (width > 600) {
      assert.equal(header.searchWidth, 150, `header search width at ${width}`);
      assert.ok(header.searchBeforeTheme && header.searchTop < header.titleBottom, `search left the title row at ${width}`);
    } else {
      assert.ok(header.searchTop >= header.titleBottom, `phone search should sit below the title at ${width}`);
    }
    // Optional Telegram link: always on the title row beside the other icons, never by the search.
    if (header.telegram) {
      assert.ok(Math.abs(header.telegram.top - header.actionsTop) < 2, `Telegram link left the title row at ${width}`);
    }
    assert.equal(header.categoryLabel, false, 'category select has no visible label text');
    assert.equal(header.updatedInHeader, false, 'update time belongs beside the changes heading');
    assert.equal(header.updatedLines, 1, `update time wraps at ${width}`);
    assert.ok(header.toggleBesideUpdated, 'Historical toggle belongs in the list heading row');
    assert.deepEqual(header.dividers, ['1px'], `divider above the list heading row missing at ${width}`);
    if (width < 600) {
      assert.notEqual(layout.mobileCategory, 'none');
      await page.locator('#category-select').focus();
      await page.locator('#category-select').selectOption('video');
      assert.equal(await page.evaluate(() => document.activeElement.id), 'category-select');
      await resetFilters(page);
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

async function verifyAccessibility(page) {
  const unnamed = await page.locator('a[href], button, input:not([type="hidden"]), select, textarea, [role="button"], [role="link"]').evaluateAll(elements => elements
    .filter(el => {
      const style = getComputedStyle(el);
      return style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0 && !el.closest('[hidden], [aria-hidden="true"]') && !el.disabled;
    })
    .filter(el => {
      const labelledBy = el.getAttribute('aria-labelledby');
      const references = labelledBy && labelledBy.split(/\s+/).map(id => document.getElementById(id)?.textContent.trim()).filter(Boolean);
      return !(el.getAttribute('aria-label')?.trim() || references?.length || [...(el.labels || [])].some(label => label.textContent.trim()) || el.textContent.trim() || el.value?.trim() || el.alt?.trim() || el.title?.trim());
    })
    .map(el => `${el.tagName.toLowerCase()}#${el.id || el.className || ''}`));
  assert.deepEqual(unnamed, [], `controls without accessible names: ${unnamed.join(', ')}`);

  const currentUrl = page.url();
  await page.goto('http://fmhy.test/?starred=0');
  await page.locator('.link').first().waitFor();
  const tabStops = await page.evaluate(() => {
    const controls = [...document.querySelectorAll('a[href], button, input:not([type="hidden"]), select, textarea, details > summary:first-of-type, [tabindex]')]
      .filter(el => {
        const style = getComputedStyle(el);
        const closed = el.closest('details:not([open])');
        if (closed && !closed.querySelector(':scope > summary')?.contains(el)) return false;
        return el.tabIndex >= 0 && !el.disabled && style.display !== 'none' && style.visibility !== 'hidden' && el.getClientRects().length > 0 && !el.closest('[hidden], [aria-hidden="true"]');
      });
    controls.forEach((el, index) => { el.dataset.a11yTabIndex = String(index); });
    return { count: controls.length, positive: controls.filter(el => el.tabIndex > 0).map(el => el.id || el.tagName) };
  });
  assert.deepEqual(tabStops.positive, [], 'positive tabindex values can scramble focus order');
  for (let index = 0; index < tabStops.count; index++) {
    await page.keyboard.press('Tab');
    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      let visibleIndicator = false;
      for (let node = el; node && node !== document.body; node = node.parentElement) {
        const style = getComputedStyle(node);
        if ((style.outlineStyle !== 'none' && parseFloat(style.outlineWidth) > 0) || style.boxShadow !== 'none') {
          visibleIndicator = true;
          break;
        }
      }
      return { index: Number(el.dataset.a11yTabIndex), keyboardVisible: el.matches(':focus-visible'), visibleIndicator };
    });
    assert.equal(focused.index, index, `Tab order differs from document order at stop ${index}`);
    assert.ok(focused.keyboardVisible && focused.visibleIndicator, `focus indicator missing at stop ${index}`);
  }

  await page.goto(currentUrl);
  await page.waitForFunction(() => !state.monthlyLoading);
  for (const theme of ['light', 'dark']) {
    await page.selectOption('#theme-select', { label: theme === 'dark' ? 'Dark' : 'Light' });
    await page.waitForFunction(value => document.documentElement.dataset.theme === value, theme);
    assert.equal(await page.locator('#theme-label').innerText(), theme === 'dark' ? 'Dark' : 'Light');
    await page.waitForTimeout(350);
    await assertTextContrast(page, `${theme} theme settled`);

    await page.locator('[data-filter="updated"]').click();
    await assertTextContrast(page, `${theme} theme selected change filter`);
    await page.locator('[data-category="gaming"]').click();
    await assertTextContrast(page, `${theme} theme selected category`);
    await page.locator('[data-category="mobile"]').hover();
    await assertTextContrast(page, `${theme} theme category hover`);

    await resetFilters(page);
    const currentPage = page.locator('.pagination[aria-label="Results pages"] .page-btn[aria-current="page"]');
    await currentPage.hover();
    await assertTextContrast(page, `${theme} theme current page hover`);
    const otherPage = page.locator('.pagination[aria-label="Results pages"] .page-btn:not([aria-current="page"]):not(:disabled)').first();
    await otherPage.hover();
    await assertTextContrast(page, `${theme} theme other page hover`);
  }
}

async function assertTextContrast(page, label) {
  const failures = await page.evaluate(() => {
    const parse = value => {
      const match = value.match(/rgba?\(([^)]+)\)/);
      if (!match) return null;
      const parts = match[1].split(',').map(part => Number.parseFloat(part.trim()));
      return [parts[0], parts[1], parts[2], parts.length > 3 ? parts[3] : 1];
    };
    const blend = (top, bottom) => [0, 1, 2].map(index => top[index] * top[3] + bottom[index] * (1 - top[3])).concat(1);
    const luminance = color => {
      const channels = color.slice(0, 3).map(value => {
        value /= 255;
        return value <= 0.04045 ? value / 12.92 : ((value + 0.055) / 1.055) ** 2.4;
      });
      return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
    };
    const bodyBackground = parse(getComputedStyle(document.body).backgroundColor);
    return [...document.body.querySelectorAll('*')].flatMap(el => {
      if (![...el.childNodes].some(node => node.nodeType === Node.TEXT_NODE && node.textContent.trim()) || !el.getClientRects().length || el.closest('[hidden], [aria-hidden="true"], :disabled')) return [];
      const chain = [];
      for (let node = el; node && node !== document.body; node = node.parentElement) chain.push(node);
      let background = bodyBackground;
      let hasImage = false;
      for (const node of chain.reverse()) {
        const style = getComputedStyle(node);
        if (style.backgroundImage !== 'none') { hasImage = true; break; }
        const color = parse(style.backgroundColor);
        if (color) background = color[3] >= 1 ? color : blend(color, background);
      }
      if (hasImage) return [];
      const style = getComputedStyle(el);
      let foreground = parse(style.color);
      if (!foreground || !background) return [];
      let opacity = 1;
      for (let node = el; node && node !== document.body; node = node.parentElement) {
        const nodeStyle = getComputedStyle(node);
        if (nodeStyle.visibility === 'hidden') return [];
        opacity *= Number.parseFloat(nodeStyle.opacity);
      }
      if (opacity === 0) return [];
      foreground[3] *= opacity;
      foreground = foreground[3] >= 1 ? foreground : blend(foreground, background);
      const fontSize = Number.parseFloat(style.fontSize);
      const fontWeight = Number.parseInt(style.fontWeight, 10) || 400;
      const minimum = fontSize >= 24 || fontSize >= 18.66 && fontWeight >= 700 ? 3 : 4.5;
      const foregroundLuminance = luminance(foreground);
      const backgroundLuminance = luminance(background);
      const ratio = (Math.max(foregroundLuminance, backgroundLuminance) + 0.05) / (Math.min(foregroundLuminance, backgroundLuminance) + 0.05);
      return ratio + 0.01 < minimum ? [{ text: el.textContent.trim().slice(0, 40), className: el.className?.toString().slice(0, 40), ratio: Number(ratio.toFixed(2)), minimum }] : [];
    });
  });
  assert.deepEqual(failures, [], `${label} text contrast failures: ${JSON.stringify(failures.slice(0, 12))}`);
}
