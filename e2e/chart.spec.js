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
  await expect(page.locator('#history-range-select')).toHaveValue('30');
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
  for (const d of ['3', '1', '10', '30']) {
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

test('H/SS support-resistance study can be toggled and is scoped to 5m', async ({ page }) => {
  const errors = watchRuntimeErrors(page);
  await waitForChart(page);
  await page.locator('#ind-toggle-btn').click();
  const study = page.locator('#hss-toggle');
  await expect(study).not.toBeChecked();
  await expect(page.locator('label:has(#hss-toggle)')).toHaveAttribute('title', /5m grouped BIG\/SMALL candles/);
  await study.check();
  await page.locator('.tf-btn[data-g="5"]').click();
  await expect(page.locator('#lg-tf')).toHaveText('5m');
  await expect(study).toBeChecked();
  await page.locator('.tf-btn[data-g="1"]').click();
  await expect(page.locator('#lg-tf')).toHaveText('1m');
  await expect(study).toBeChecked();
  await page.waitForTimeout(200);
  expect(errors).toEqual([]);
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
  await expect(page.locator('#l1-target-issue')).toContainText('00000361');
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
  await expect(page.locator('.secondary-grid')).toHaveCount(0);
  await expect(page.locator('#context-card')).toHaveCount(0);
  await expect(page.locator('#context-tab')).toHaveText('MARKET CONTEXT');
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
  expect(desktopBox.height).toBeGreaterThanOrEqual(320);
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

test('L1 clears target stake and focus status when feed becomes stale', async ({ page }) => {
  let stale = false;
  await page.route('**/api/l1-capital', async route => {
    await route.fulfill({json: stale
      ? {ready: false, stale: true, feed_status: 'STALE', pending: null}
      : {ready: true, pending: {target: 'BIG', issue: '20260913000000361', stake: 6250, tier: 2, step: 1}, trades: []}});
  });
  await page.goto('/');
  await expect(page.locator('#l1-stake')).toHaveText('6,250 MMK');
  stale = true;
  await expect(page.locator('#l1-status')).toHaveText('STALE');
  await expect(page.locator('#l1-stake')).toHaveText('—');
  await expect(page.locator('#l1-tier')).toHaveText('—');
  await expect(page.locator('#l1-step')).toHaveText('—');
  await expect(page.locator('#l1-target-issue')).toContainText('NO VALID SIGNAL');
  await expect(page.locator('#focus-l1')).toContainText('STALE');
});

test('L1 clears actionable display on API network failure and recovers', async ({ page }) => {
  let fail = false;
  await page.route('**/api/l1-capital', async route => {
    if (fail) return route.abort();
    await route.fulfill({json: {ready: true, pending: {target: 'SMALL', issue: '20260913000000361', stake: 500, tier: 1, step: 1}, trades: []}});
  });
  await page.goto('/');
  await expect(page.locator('#l1-status')).toHaveText('SMALL');
  fail = true;
  await expect(page.locator('#l1-status')).toHaveText('OFFLINE');
  await expect(page.locator('#l1-stake')).toHaveText('—');
  fail = false;
  await expect(page.locator('#l1-status')).toHaveText('SMALL');
  await expect(page.locator('#l1-stake')).toHaveText('500 MMK');
});

test('L1 daily report uses full daily summary beyond the 100 trade tail', async ({ page }) => {
  await page.route('**/api/l1-capital', async route => {
    await route.fulfill({json: {
      ready: true, pending: null, today: '2026-10-02', today_pnl: 95040,
      daily_summary: {bets: 198, wins: 198, losses: 0, win_rate: 100, staked: 99000, pnl: 95040, max_tier: 1, max_step: 1},
      trades: Array.from({length: 100}, () => ({time: '2026-10-02 12:00:00', won: true, stake: 500, tier: 1, step: 1})),
    }});
  });
  await page.goto('/');
  await expect(page.locator('#l1r-bets')).toHaveText('198');
  await expect(page.locator('#l1r-wl')).toHaveText('198 / 0');
  await expect(page.locator('#l1r-staked')).toHaveText('99,000 MMK');
  await expect(page.locator('#l1r-pnl')).toHaveText('+95,040 MMK');
});

test('source delay is independent of viewer timezone', async ({ browser, baseURL }) => {
  for (const timezoneId of ['UTC', 'Asia/Bangkok']) {
    const context = await browser.newContext({timezoneId, baseURL});
    const page = await context.newPage();
    await page.clock.setFixedTime(new Date('2026-10-02T12:00:10Z'));
    await page.route('**/api/history*', route => route.fulfill({json: {
      history: [['20261002103010720', 8, '2026-10-02 18:29:54']],
      last_time: '2026-10-02 18:29:54', last_time_utc: '2026-10-02T11:59:54+00:00', meta: {days: 10},
    }}));
    await page.route('**/api/latest', route => route.fulfill({json: {round: null}}));
    await page.goto('/');
    await expect(page.locator('#ctb-next')).toHaveText('NEXT ISSUE ETA: ~0:44');
    const sourceTime = await page.evaluate(() => sourceEpoch('2026-10-02 18:29:54'));
    expect(sourceTime).toBe(Date.parse('2026-10-02T11:59:54Z'));
    await context.close();
  }
});

test('focus frame stays fully below the sticky header while scrolling and resizing', async ({ page }, testInfo) => {
  await waitForChart(page);
  for (const viewport of [{width:1920,height:921}, {width:1366,height:768}, {width:980,height:720}, {width:390,height:844}]) {
    await page.setViewportSize(viewport);
    await page.evaluate(() => window.scrollTo(0, 350));
    await expect.poll(() => page.evaluate(() => {
      const header = document.querySelector('header');
      const bar = document.querySelector('#focus-bar');
      const expected = getComputedStyle(header).position === 'sticky' ? header.getBoundingClientRect().bottom : 0;
      return Math.abs(bar.getBoundingClientRect().top - expected);
    })).toBeLessThanOrEqual(1);
    const visible = await page.locator('#focus-l1').evaluate(el => {
      const box = el.getBoundingClientRect();
      return !!document.elementFromPoint(box.x + box.width / 2, box.y + 2)?.closest('#focus-bar');
    });
    expect(visible).toBeTruthy();
    await testInfo.attach('focus-scroll-' + viewport.width, {body: await page.screenshot(), contentType:'image/png'});
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
  }
  // Simulate wrapping/font scaling changing the header after layout.
  await page.setViewportSize({width:1366,height:768});
  await page.locator('header').evaluate(el => el.style.minHeight = '104px');
  await expect.poll(() => page.evaluate(() => Math.abs(
    document.querySelector('#focus-bar').getBoundingClientRect().top - document.querySelector('header').getBoundingClientRect().bottom
  ))).toBeLessThanOrEqual(1);
});

test('large desktop chart and RSI remain reachable with all signals in the sidebar', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Desktop workspace measurement.');
  for (const viewport of [{width:1920,height:921}, {width:1366,height:768}, {width:1355,height:936}]) {
    await page.setViewportSize(viewport);
    await waitForChart(page);
    await testInfo.attach('workspace-' + viewport.width, {body: await page.screenshot(), contentType:'image/png'});
    const rsi = await page.locator('#rsi-pane').boundingBox();
    expect((await page.locator('#tv-chart').boundingBox()).height).toBeGreaterThanOrEqual(500);
    await page.locator('#rsi-pane').scrollIntoViewIfNeeded();
    await expect(page.locator('#rsi-pane')).toBeInViewport();
    const signal = await page.locator('#stake-card').boundingBox();
    const report = await page.locator('#daily12-card').boundingBox();
    expect(Math.abs(signal.x - report.x)).toBeLessThanOrEqual(1);
    expect(report.y).toBeGreaterThan(signal.y + signal.height);
    expect(signal.width).toBeLessThanOrEqual(viewport.width * .28);
    expect(report.width).toBeLessThanOrEqual(viewport.width * .28);
  }
});

test('drawing cursor instructions stay hidden until drawing tools are opened', async ({ page }) => {
  await waitForChart(page);
  await expect(page.locator('.draw-hint')).toBeHidden();
  await page.locator('#dt-toggle-btn').click();
  await expect(page.locator('.draw-hint')).toBeVisible();
});

test('risk remains distinct from feed state and rules are available on demand', async ({ page }) => {
  await waitForChart(page);
  await expect(page.locator('#l1-risk')).toHaveClass(/is-observe/);
  await expect(page.locator('#focus-connection b')).toHaveText('LIVE');
  await expect(page.locator('#l1-status')).toBeHidden();
  await expect(page.locator('#l1-frozen-rules')).toBeHidden();
  await page.locator('#l1-capital-card .terminal-details summary').click();
  await expect(page.locator('#l1-frozen-rules')).toContainText('Skip R02/R03/R05/R06');
});

test('last result uses the viewer clock with a labelled timezone and elapsed age', async ({ browser, baseURL }) => {
  for (const [timezoneId, clock, label] of [['UTC','11:59:54','UTC+00:00'], ['Asia/Bangkok','18:59:54','UTC+07:00']]) {
    const context = await browser.newContext({timezoneId, baseURL});
    const page = await context.newPage();
    await page.clock.setFixedTime(new Date('2026-10-02T12:00:10Z'));
    await page.route('**/api/history*', route => route.fulfill({json:{history:[['20261002103010720',8,'2026-10-02 18:29:54']],last_time:'2026-10-02 18:29:54',last_time_utc:'2026-10-02T11:59:54+00:00',meta:{days:10}}}));
    await page.route('**/api/latest', route => route.fulfill({json:{round:null}}));
    await page.goto('/');
    await expect(page.locator('#ctb-last')).toHaveText(clock);
    await expect(page.locator('#lg-time')).toContainText(clock.slice(0,5));
    await expect(page.locator('#ctb-zone')).toContainText(label);
    await expect(page.locator('#ctb-age')).toHaveText('AGE: 16s');
    await context.close();
  }
});

test('narrow mobile focus identifies both engines and timing values are not clipped', async ({ page }, testInfo) => {
  test.skip(!testInfo.project.name.includes('mobile'), 'Narrow mobile readability.');
  await page.setViewportSize({width:390,height:844});
  await waitForChart(page);
  await expect(page.locator('#focus-l1 > span:not(.focus-state-icon)')).toBeVisible();
  await expect(page.locator('#focus-step > span:not(.focus-state-icon)')).toBeVisible();
  await expect(page.locator('#focus-connection b')).toBeVisible();
  const clipped = await page.locator('.chart-time-bar .ctb-item').evaluateAll(items => items.some(el => el.scrollWidth > el.clientWidth + 1));
  expect(clipped).toBeFalsy();
  await page.evaluate(() => window.scrollTo(0, 350));
  await testInfo.attach('mobile-labelled-focus', {body:await page.screenshot(),contentType:'image/png'});
});

test('approved wide chart and market panel stay beside four compact sidebar cards', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Desktop layout.');
  for (const viewport of [{width:1920,height:1080}, {width:1366,height:768}, {width:1355,height:936}]) {
    await page.setViewportSize(viewport);
    await waitForChart(page);
    const chart = await page.locator('#chart-card').boundingBox();
    const signal = await page.locator('#l1-capital-card').boundingBox();
    expect(signal.x).toBeGreaterThan(chart.x + chart.width);
    expect(chart.width / (chart.width + signal.width)).toBeGreaterThanOrEqual(.72);
    expect((await page.locator('#tv-chart').boundingBox()).height).toBeGreaterThanOrEqual(500);
    await page.locator('#market-card').scrollIntoViewIfNeeded();
    await expect(page.locator('#market-card')).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBeTruthy();
    await testInfo.attach('approved-layout-' + viewport.width, {body:await page.screenshot(),contentType:'image/png'});
  }
});

test('oversized chart workspace scrolls normally to keep all controls reachable', async ({ page }, testInfo) => {
  test.skip(testInfo.project.name.includes('mobile'), 'Desktop sticky fallback.');
  await page.setViewportSize({width:1366,height:650});
  await waitForChart(page);
  await page.locator('#ind-toggle-btn').click();
  await page.locator('#macd-toggle').check();
  await page.locator('#stoch-toggle').check();
  await expect(page.locator('.primary-stack')).toHaveCSS('position','static');
  await page.locator('#chart-time-bar').scrollIntoViewIfNeeded();
  await expect(page.locator('#chart-time-bar')).toBeInViewport();
});

