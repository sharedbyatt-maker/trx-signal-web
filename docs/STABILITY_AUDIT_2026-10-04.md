# TRX Signal Web stability audit — 4 October 2026

Scope: current production dashboard, feed recovery, public APIs, chart/history updates, signal presentation, daily reports, manual drawings, notifications, and desktop/mobile interaction. This release fixes stability before any further visual redesign.

## Reproduced defects and fixes

| Area | Reproduction / previous behavior | Fix |
| --- | --- | --- |
| State freshness | Stop the publisher for 100 seconds while its last flag is LIVE; `/api/state` still exposes an armed target. | Age API reads with the existing 80-second freshness policy and remove pending targets from the public copy. Internal engine settlement state remains intact. |
| Health endpoint | Same stalled publisher can still return HTTP 200 / LIVE. | Recompute result age for each health read; stale data returns 503 / STALE. |
| Daily report engine | Offline state still publishes an active pending target through the daily report API. | Hide unavailable pending targets and publish the actual unavailable status. |
| Daily report date | Provider round date is tomorrow relative to the UTC host calendar. | Choose the current round calendar date; reject invalid explicit dates with 400. |
| Feed parser | An object or infinite value in one result raises TypeError/OverflowError and drops the whole poll. | Discard invalid rows while retaining valid ones; reject empty/invalid payloads instead of silently retaining LIVE. |
| Feed reconnection | A failed request followed by a successful unchanged round remains disconnected until another issue arrives. | Restore transport connectivity on a valid response without reprocessing settlements. |
| API caching | Live APIs omit explicit no-store response headers. | All API responses now prohibit caching. |
| Drawing validation | JSON arrays and infinite revision values cause HTTP 500. | Return controlled 400 errors. |
| Telegram error exposure | A simulated Requests exception containing the bot URL appears in the public test response. | Return only an error class/status; never echo the bot URL or upstream body. |
| State/history polling | A history fetch can delay initial state and occupy the state polling loop. Hung state/latest/daily requests lack a complete-request deadline. | Render state independently of history; serialize history fetches; bound requests including body parsing; resume after timeout. |
| Sidebar and focus targets | A stale state or completed fast-path target disappears from Context but remains armed in sidebar/focus. | Apply the same freshness and exact-current-target checks to all signal surfaces; expire cached displays on a timer. |
| Manual drawing sync | Concurrent autosaves use the same expected revision and conflict with their own prior save. | Serialize writes and queue the latest local changes after the current revision finishes; bound sync/restore requests. |
| Signal alerts | The bell preference and notification functions are present, but no current signal calls them. | Restore opt-in alerts for valid current L1/12-Step targets with per-engine issue deduplication. |
| Offline countdown | The next-issue countdown keeps extrapolating after feed/state failure. | Hide the estimate while current feed state is unavailable. |
| Browser restrictions | Disabled localStorage throws during sound setup/clicks. | Guard preference access; release temporary audio contexts; catch notification permission failures. |
| Daily report outage | A report fetch failure silently retains its old status. | Expose failed updates and retain the last loaded settled history. |

## Validation

- Eight new backend regressions were demonstrated failing against the preceding release before fixes.
- Python discovered tests, all existing standalone regression scripts, chart integrity checks, and request timeout/abort/recovery checks are run.
- Browser tests cover both desktop and mobile: slow history, hung state recovery, stale/offline clearing and recovery, fast-path target expiry, denied storage, serialized drawing writes, and report failures, and opt-in alert deduplication.
- Existing browser coverage continues to exercise real chart controls, timeframes, indicator panes, crosshair, S/R, drawing edits/persistence, compact Context, filters, pagination, and layout bounds.
- CI and production acceptance results are recorded in the release PR.

## Preserved behavior

No changes to `l1_capital.py`, `decision.py`, strategy constants, RSI calculations, skip rules, stake ladders, payout rules, or settlement decisions. Changes within `app_core.py` concern transport/input handling and public reporting only. Manual execution remains manual. No redesign or chart size reduction is included.

## Operational limits

Render free hosting and the upstream provider can still have outages. Report ledgers/runtime notification keys use the host filesystem, so a redeploy can discard them unless durable storage is configured; browser drawing exports/local backups remain available. This release does not provision paid infrastructure or claim permanent storage. Loaded history has finite coverage and is not a complete account ledger. A passing audit demonstrates the tested behavior; it is not a guarantee that no future bug can occur.
