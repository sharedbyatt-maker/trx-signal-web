# TRX Signal Web maintenance instructions

These instructions apply to the entire repository. The owner wants the existing product preserved across maintainers and ChatGPT accounts. Treat existing features and UI as approved. Change only the parts the owner explicitly requests. A request to review or analyze is read-only.

## Approved baseline

- Source and verified live Render revision on 2026-11-08: [f2e09fb31625a41a16913e84df8df1d8ff2de56a](https://github.com/sharedbyatt-maker/trx-signal-web/tree/f2e09fb31625a41a16913e84df8df1d8ff2de56a). Default branch: `main`.
- [Live site](https://trx-signal-web.onrender.com/), [Kronos chart](https://trx-signal-web.onrender.com/kronos), [Admin](https://trx-signal-web.onrender.com/admin), [Render service](https://dashboard.render.com/web/srv-da8nivrtqb8s73aojamg). Verify the current live revision before future deploy work.
- User terminal: preserve desktop/mobile layout, navigation, Burmese copy, chart timeframes and history, indicators, drawing tools and persistence, market context, signal history, L1 Capital, 12-step and daily reports.
- Kronos: preserve the separate research chart, 1m and 5m, prediction candles and line toggle, valid candle handling, latest/archive and replay controls, source/forecast status, reports and baselines. Preserve the `kronos-forecasts` branch and the separate publication workflows. Keep research output isolated from live decisions and order placement.
- Admin: preserve login and CSRF, chart and notification controls, feed and Telegram settings, strategy controls, audit, backup/restore, TRXChart account/history sync, REAL/DEMO journal separation, manual REAL order confirmations and duplicate-request safeguards.
- Baseline source records the approved implementation, including HTML, CSS, JS, server code and tests. Live credentials, private account data and runtime records are outside this Git baseline. Keep those out of Git.

## Before and after a change

1. Read the current branch, live revision when relevant, and the related tests. Use the baseline as a reference and preserve later owner-approved changes too.
2. Keep the diff within the requested scope. Preserve unrelated UI, routes, defaults, data formats, behavior and deployments. Ask the owner before an unavoidable change outside scope.
3. Use a separate branch and a focused PR for future application changes. Use the closest existing regression tests. For UI changes, compare the affected flow on desktop and mobile. Run the relevant GitHub CI checks and inspect the final diff before requesting merge.
4. Treat merging, deploying, resetting storage, changing hosting or touching production credentials as separate actions that require owner authorization. For docs-only commits, use `[skip render]` to avoid a Render deploy.
5. In the handoff, state what changed, what was verified, and whether it reached production. Update this baseline only when the owner approves a new baseline.
