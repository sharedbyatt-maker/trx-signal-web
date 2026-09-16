const { test, expect } = require('@playwright/test');

async function waitForChart(page) {
  await page.goto('/');
  await expect(page.locator('#conn-txt')).toHaveText('LIVE');
  await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
  await expect(page.locator('#history .ball, #history > div').first()).toBeVisible();
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
  await expect(page.locator('.hist-range-btn[data-days="10"]')).toHaveClass(/active/);
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
    await page.locator(`.hist-range-btn[data-days="${d}"]`).click();
    await expect(page.locator(`.hist-range-btn[data-days="${d}"]`)).toHaveClass(/active/);
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
