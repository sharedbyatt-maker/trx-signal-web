const { test, expect } = require('@playwright/test');

async function waitForChart(page) {
  await page.goto('/');
  await expect(page.locator('#tv-chart canvas').first()).toBeVisible({ timeout: 15000 });
  await expect(page.locator('#chart-meta')).not.toHaveText('loading…', { timeout: 15000 });
}

test('loads the real chart UI without browser runtime errors', async ({ page }) => {
  const errors = [];
  page.on('pageerror', (err) => errors.push(err.message));
  await waitForChart(page);
  await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
  await expect(page.locator('#chart-meta')).toContainText('10D');
  expect(errors).toEqual([]);
});

test('switches true timeframes and keeps the chart alive', async ({ page }) => {
  await waitForChart(page);
  for (const [g, label] of [['5','5m'], ['15','15m'], ['60','1h'], ['1','1m']]) {
    await page.locator(`.tf-btn[data-g="${g}"]`).click();
    await expect(page.locator('#lg-tf')).toHaveText(label);
    await expect(page.locator('#tv-chart canvas').first()).toBeVisible();
  }
});

test('chart clearly discloses synthetic model and HLC stochastic', async ({ page }) => {
  await waitForChart(page);
  await expect(page.locator('#chart-model-note')).toContainText('NOT TRX MARKET PRICE');
  await expect(page.locator('#stoch-pane')).toContainText('STOCH H/L/C');
});

test('history range presets expose the full-history navigation controls', async ({ page }) => {
  await waitForChart(page);
  await expect(page.locator('.hist-range-btn[data-days="10"]')).toBeVisible();
  await expect(page.locator('.hist-range-btn[data-days="10"]')).toHaveClass(/active/);
  await page.locator('.hist-range-btn[data-days="3"]').click();
  await expect(page.locator('.hist-range-btn[data-days="3"]')).toHaveClass(/active/);
  await page.locator('.hist-range-btn[data-days="10"]').click();
  await expect(page.locator('.hist-range-btn[data-days="10"]')).toHaveClass(/active/);
});

test('indicator controls independently open and toggle panes', async ({ page }) => {
  await waitForChart(page);
  await page.locator('#ind-toggle-btn').click();
  await expect(page.locator('#ind-bar')).not.toHaveClass(/collapsed/);
  await page.locator('#macd-toggle').check();
  await expect(page.locator('#macd-pane')).not.toHaveClass(/off/);
  await page.locator('#stoch-toggle').check();
  await expect(page.locator('#stoch-pane')).not.toHaveClass(/off/);
  await page.locator('#rsi-toggle').uncheck();
  await expect(page.locator('#rsi-pane')).toHaveClass(/off/);
});

test('crosshair interaction updates chart legends', async ({ page }) => {
  await waitForChart(page);
  const canvas = page.locator('#tv-chart canvas').first();
  const box = await canvas.boundingBox();
  await page.mouse.move(box.x + box.width * 0.65, box.y + box.height * 0.45);
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
  await page.locator('.dt-btn[data-tool="hline"]').click();
  const canvas = page.locator('#tv-chart canvas').first();
  const box = await canvas.boundingBox();
  await page.mouse.click(box.x + box.width * 0.55, box.y + box.height * 0.45);
  await page.waitForTimeout(250);
  const before = await page.evaluate(() => localStorage.getItem('trx_drawings_v2'));
  expect(before).toBeTruthy();
  await page.reload();
  await expect(page.locator('#tv-chart canvas').first()).toBeVisible({ timeout: 15000 });
  const after = await page.evaluate(() => localStorage.getItem('trx_drawings_v2'));
  expect(after).toBe(before);
});

test('mobile layout keeps primary chart controls usable', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'Mobile-only layout assertion.');
  await waitForChart(page);
  await expect(page.locator('#chart-card')).toBeVisible();
  await expect(page.locator('.chart-toolbar')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  expect(overflow).toBeFalsy();
});
