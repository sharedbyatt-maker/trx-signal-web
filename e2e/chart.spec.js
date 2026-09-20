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
  await expect(page.locator('#rsi-pane')).toBeVisible();
  await expect(page.locator('#context-card')).toHaveCount(0);
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

test('chart supports HLC stochastic', async ({ page }) => {
  await waitForChart(page);
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

test('L1 CAPITAL card and focus status render without Robust remnants', async ({ page }, testInfo) => {
  const errors = watchRuntimeErrors(page);
  await page.goto('/');
  const card = page.locator('#l1-capital-card');
  await expect(card).toBeVisible();
  await expect(page.locator('#focus-l1')).toContainText('L1 CAPITAL');
  await expect(page.locator('#l1-status')).toHaveText('BIG');
  await expect(page.locator('#l1-target-issue')).toContainText('03019999');
  await expect(page.locator('#l1-stake')).toHaveText('6,250 MMK');
  await expect(page.locator('#l1-tier')).toHaveText('T2');
  await expect(page.locator('#l1-step')).toHaveText('S1');
  await expect(page.locator('#l1-pnl')).toHaveText('+7,730 MMK');
  await expect(page.locator('#l1-risk')).toContainText('OBSERVE ONLY');
  await expect(page.getByText('ROBUST SIGNAL ENGINE')).toHaveCount(0);
  if (testInfo.project.name.includes('mobile')) {
    const box = await card.boundingBox();
    expect(box).toBeTruthy();
    expect(box.width).toBeLessThanOrEqual(412);
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
    expect(overflow).toBeFalsy();
  }
  await page.waitForTimeout(300);
  expect(errors).toEqual([]);
});

test('sidebar order and L1 daily report calculations match existing API state', async ({ page }) => {
  const errors = watchRuntimeErrors(page);
  await page.goto('/');
  const cards = page.locator('.side-stack > section');
  await expect(cards).toHaveCount(4);
  await expect(cards.nth(0)).toHaveAttribute('id', 'l1-capital-card');
  await expect(cards.nth(1)).toHaveAttribute('id', 'l1-report-card');
  await expect(cards.nth(2)).toHaveAttribute('id', 'stake-card');
  await expect(cards.nth(3)).toHaveAttribute('id', 'daily12-card');
  await expect(page.locator('#context-card')).toHaveCount(0);
  await expect(page.getByText('MARKET CONTEXT')).toHaveCount(0);
  await expect(page.getByText('ROBUST SIGNAL ENGINE')).toHaveCount(0);

  await expect(page.locator('#l1r-bets')).toHaveText('5');
  await expect(page.locator('#l1r-wr')).toHaveText('60.0%');
  await expect(page.locator('#l1r-pnl')).toHaveText('+7,730 MMK');
  await expect(page.locator('#l1r-staked')).toHaveText('23,250 MMK');
  await expect(page.locator('#l1r-wl')).toHaveText('3 / 2');
  await expect(page.locator('#l1r-depth')).toHaveText('T2-S2');
  await expect(page.locator('#l1r-withdraw')).toHaveText('42,600 / 50,000');
  await expect(page.locator('#l1r-withdraw-bar')).toHaveCSS('width', /.+/);
  const progress = await page.locator('#l1r-withdraw-bar').evaluate(el => parseFloat(el.style.width));
  expect(progress).toBeCloseTo(85.2, 1);
  await expect(page.locator('#l1r-total')).toHaveText('MODEL TOTAL +92,600 MMK');
  await expect(page.locator('#l1r-last')).toHaveText('LAST WIN · T1-S4 · 3,000');
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  expect(overflow).toBeFalsy();
  const reportOverflow = await page.locator('#l1-report-card').evaluate(el => el.scrollWidth > el.clientWidth + 1);
  expect(reportOverflow).toBeFalsy();
  await page.waitForTimeout(300);
  expect(errors).toEqual([]);
});

test('withdrawal progress targets the next 50,000 milestone at boundary values', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Calculation boundaries are viewport-independent and covered once on desktop.');
  const cases = [
    [0, 0, '0 / 50,000', 0],
    [49999, 0, '49,999 / 50,000', 99.998],
    [50000, 1, '0 / 50,000', 0],
    [50001, 1, '1 / 50,000', 0.002],
    [92600, 1, '42,600 / 50,000', 85.2],
    [100000, 2, '0 / 50,000', 0],
  ];
  let current = cases[0];
  await page.route('**/api/l1-capital', async route => {
    const response = await route.fetch();
    const body = await response.json();
    body.model_total_pnl = current[0];
    body.withdraw_milestones_reached = current[1];
    await route.fulfill({response, json: body});
  });
  for (const item of cases) {
    current = item;
    await page.goto('/');
    await expect(page.locator('#l1r-withdraw')).toHaveText(item[2]);
    const width = await page.locator('#l1r-withdraw-bar').evaluate(el => parseFloat(el.style.width));
    expect(width).toBeCloseTo(item[3], 2);
  }
});


test('digit distribution is removed and desktop chart stays balanced', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Desktop-only chart workspace assertion.');
  await page.goto('/');
  await expect(page.locator('#digit-grid')).toHaveCount(0);
  await expect(page.getByText('DIGIT DISTRIBUTION · LAST 100')).toHaveCount(0);
  const chart = page.locator('#tv-chart');
  await expect(chart).toBeVisible();
  const desktopBox = await chart.boundingBox();
  expect(desktopBox.height).toBeGreaterThanOrEqual(500);
  expect(desktopBox.height).toBeLessThanOrEqual(650);
  const sideBox = await page.locator('.side-stack').boundingBox();
  expect(sideBox.height).toBeGreaterThan(desktopBox.height);
  await expect(page.locator('#rsi-pane')).toBeVisible();
  await expect(page.locator('.chart-toolbar')).toBeVisible();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2);
  expect(overflow).toBeFalsy();
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
  await expect(page.locator('#chart-card > .card-title')).toHaveCount(0);
});
