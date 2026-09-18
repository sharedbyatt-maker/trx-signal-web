const { test, expect } = require('@playwright/test');

async function waitForChart(page) {
  await page.goto('/');
  await expect(page.locator('#conn-txt')).toHaveText('LIVE');
  await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
}

function watchRuntimeErrors(page) {
  const errors = [];
  page.on('pageerror', (err) => errors.push(`pageerror: ${err.message}`));
  page.on('console', (msg) => {
    if (msg.type() !== 'error') return;
    const text = msg.text();
    if (/ResizeObserver loop/i.test(text)) return;
    errors.push(`console: ${text}`);
  });
  return errors;
}

test('loads the real chart UI without browser runtime errors', async ({ page }) => {
  const errors = watchRuntimeErrors(page);
  await waitForChart(page);
  await expect(page.locator('#lg-tf')).toHaveText('1m');
  await expect(page.locator('#lg-ohlc')).not.toHaveText('');
  await expect(page.locator('#ctx-rsi30')).toContainText('L');
  await expect(page.locator('#history-range-select')).toHaveValue('10');
  await page.waitForTimeout(700);
  expect(errors).toEqual([]);
});

test('switches true timeframes and keeps the chart alive', async ({ page }) => {
  await waitForChart(page);
  for (const [g, label] of [['5', '5m'], ['15', '15m'], ['60', '1h'], ['1', '1m']]) {
    await page.locator(`.tf-btn[data-g="${g}"]`).click();
    await expect(page.locator('#lg-tf')).toHaveText(label);
    await expect(page.locator(`.tf-btn[data-g="${g}"]`)).toHaveClass(/active/);
    await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
  }
});

test('chart clearly discloses synthetic model and HLC stochastic', async ({ page }) => {
  await waitForChart(page);
  await expect(page.locator('#chart-model-note')).toContainText('NOT TRX MARKET PRICE');
  await page.locator('#ind-toggle-btn').click();
  await page.locator('#stoch-toggle').check();
  await expect(page.locator('#stoch-pane')).not.toHaveClass(/off/);
  await expect(page.locator('#stoch-pane')).toContainText('STOCH H/L/C 14·3·3');
});

test('history range presets expose the full-history navigation controls', async ({ page }) => {
  await waitForChart(page);
  await expect(page.locator('#chart-meta')).not.toHaveText('loading…');
  for (const d of ['3', '1', '10']) {
    await page.locator('#history-range-select').selectOption(d);
    await expect(page.locator('#history-range-select')).toHaveValue(d);
    await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
  }
});

test('indicator controls independently open and toggle panes', async ({ page }) => {
  await waitForChart(page);
  await expect(page.locator('#ind-bar')).toHaveClass(/collapsed/);
  await page.locator('#ind-toggle-btn').click();
  await expect(page.locator('#ind-bar')).not.toHaveClass(/collapsed/);

  await expect(page.locator('#sma-toggle')).not.toBeChecked();
  await page.locator('#sma-toggle').check();
  await expect(page.locator('#sma-toggle')).toBeChecked();

  await page.locator('#macd-toggle').check();
  await expect(page.locator('#macd-pane')).toBeVisible();
  await page.locator('#stoch-toggle').check();
  await expect(page.locator('#stoch-pane')).toBeVisible();

  await page.locator('#rsi-toggle').uncheck();
  await expect(page.locator('#rsi-pane')).toBeHidden();
  await page.locator('#rsi-toggle').check();
  await expect(page.locator('#rsi-pane')).toBeVisible();
});

test('crosshair interaction updates chart legends', async ({ page }) => {
  await waitForChart(page);
  const chart = page.locator('#tv-chart');
  const box = await chart.boundingBox();
  expect(box).toBeTruthy();
  await page.mouse.move(box.x + box.width * 0.55, box.y + box.height * 0.45);
  await expect(page.locator('#lg-time')).not.toHaveText('');
  await expect(page.locator('#lg-ohlc')).not.toHaveText('');
  await expect(page.locator('#lg-rsi')).not.toHaveText('');
});

test('S/R control remains synchronized with the indicator checkbox', async ({ page }) => {
  await waitForChart(page);
  await page.locator('#ind-toggle-btn').click();
  await expect(page.locator('#sr-toggle')).not.toBeChecked();
  await expect(page.locator('#sr-find-btn')).not.toHaveClass(/active/);

  await page.locator('#sr-toggle').check();
  await expect(page.locator('#sr-find-btn')).toHaveClass(/active/);
  await page.locator('#sr-toggle').uncheck();
  await expect(page.locator('#sr-find-btn')).not.toHaveClass(/active/);
});

test('manual drawing is persisted locally across reload', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Precise canvas drawing is covered on desktop; mobile has layout/touch smoke coverage.');
  await waitForChart(page);
  await page.locator('#dt-toggle-btn').click();
  await expect(page.locator('#draw-tools')).not.toHaveClass(/collapsed/);
  await page.locator('[data-tool="hline"]').click();

  const chart = page.locator('#tv-chart');
  const box = await chart.boundingBox();
  expect(box).toBeTruthy();
  await page.mouse.click(box.x + box.width * 0.52, box.y + box.height * 0.44);

  await expect.poll(async () => page.evaluate(() => {
    try { return JSON.parse(localStorage.getItem('trx_drawings_v3') || '[]').length; }
    catch (_) { return 0; }
  })).toBeGreaterThan(0);

  const before = await page.evaluate(() => JSON.parse(localStorage.getItem('trx_drawings_v3') || '[]').length);
  await page.reload();
  await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
  const after = await page.evaluate(() => JSON.parse(localStorage.getItem('trx_drawings_v3') || '[]').length);
  expect(after).toBe(before);
});

test('mobile layout keeps primary chart controls usable', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'Mobile-only layout smoke test.');
  await waitForChart(page);
  await expect(page.locator('#chart-card')).toBeVisible();
  await expect(page.locator('.chart-toolbar')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  expect(overflow).toBeFalsy();
});


test('digit distribution is removed and desktop chart gets analysis space', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Desktop-only chart workspace assertion.');
  await page.goto('/');
  await expect(page.locator('#digit-grid')).toHaveCount(0);
  await expect(page.getByText('DIGIT DISTRIBUTION · LAST 100')).toHaveCount(0);
  const chart = page.locator('#tv-chart');
  await expect(chart).toBeVisible();
  const desktopBox = await chart.boundingBox();
  expect(desktopBox.height).toBeGreaterThanOrEqual(540);
});

test('mobile chart remains usable after digit panel removal', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'Mobile-only chart workspace assertion.');
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(page.locator('#digit-grid')).toHaveCount(0);
  const chart = page.locator('#tv-chart');
  await expect(chart).toBeVisible();
  const box = await chart.boundingBox();
  expect(box.width).toBeLessThanOrEqual(390);
  expect(box.height).toBeGreaterThanOrEqual(390);
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1);
  expect(overflow).toBeTruthy();
});


test('UI polish keeps focus status singular and readable', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('#focus-bar')).toBeVisible();
  await expect(page.locator('#focus-connection')).toBeVisible();
  await expect(page.locator('header #conn-txt')).toBeHidden();
  const dailyLabel = page.locator('.daily12-grid small').first();
  await expect(dailyLabel).toBeVisible();
  const size = await dailyLabel.evaluate((el) => parseFloat(getComputedStyle(el).fontSize));
  expect(size).toBeGreaterThanOrEqual(9);
});

test('drawing tool exposes active and drag feedback classes', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Precise drawing interaction is desktop-only.');
  await waitForChart(page);
  await page.locator('#dt-toggle-btn').click();
  await page.locator('.dt-btn[data-tool="trend"]').click();
  await expect(page.locator('.dt-btn[data-tool="trend"]')).toHaveClass(/active/);
  await expect(page.locator('#tv-chart')).toHaveClass(/drawing-active/);
});


test('focus countdown is clearly distinguished from wall clock and chart note is removed', async ({ page }) => {
  await page.goto('/');
  await expect(page.locator('.focus-countdown > span')).toHaveText('NEXT IN');
  await expect(page.locator('#focus-next')).toContainText(/~?\d+:\d{2}|—/);
  await expect(page.locator('#chart-model-note')).toHaveCount(0);
  await expect(page.locator('#chart-card .card-title')).toHaveText('CHART');
});
