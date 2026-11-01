# Kronos chart integrity review

The review covers only the isolated Kronos chart, inference adapter and its
tests. The main chart, L1, 12-step, admin, source APIs and trading engines are
outside this change. No additional prediction libraries are installed.

## Corrected behavior

- A delayed response for a previous timeframe cannot replace the current view.
- The selected archived forecast, imported JSON and replay mode survive the
  30-second read-only history refresh. **Latest forecast** explicitly returns
  to following new publications.
- Replay refresh never draws subsequent actual candles while awaiting the
  publication download, and hides current-forecast outcome counts.
- A failed/rejected forecast clears its projection, outcome counts and replay
  control; it cannot leave the previous forecast looking usable. History and
  report downloads are independent, so reports can load without a current
  snapshot. A report refresh failure retains the last measured report with a
  visible delay notice.
- Missing source data is distinct from a target whose outcome is still pending.
- Live inference rejects missing/duplicate source minutes within its recent
  input window, including gaps hidden inside an aggregated 5m candle. It does
  not edit any existing forecast when validation fails.
- Immutable forecast JSON is cached in bounded browser memory instead of
  downloading the same archive on each refresh. Network requests have a
  15-second timeout. Forecasts are still evaluated against newly received rounds.
- Chart labels, inspection, forecast selection labels and result cards use
  Bangkok (UTC+07:00). Source parsing and synthetic-walk aggregation remain
  Asia/Yangon; the underlying UTC candle timestamps are unchanged.
- The configured next run opportunity is anchored to the last forecast. Once
  overdue, it stays overdue rather than continually advancing to another
  future slot. Unsupported 15m/1h automatic inference is labelled explicitly.

## Validation and limits

Regression coverage includes response races, archive/replay refresh, imported
JSON during a publication outage, unavailable-state cleanup, source gaps and
the overdue schedule calculation. Browser scenarios exercise the same behavior
on desktop and mobile. These fixtures are UI/data-integrity checks and are never
published as model results.

The workflow is configured for five-minute opportunities, but a configured cron
and successful manual run do not prove recurring scheduled execution. GitHub's
schedule-event history must be checked separately. The chart now makes this
distinction visible; refreshing the page does not start inference.

Kronos remains experimental on a cumulative BIG/SMALL walk, not a market-price
series. Close MAE and origin-to-target direction are not next-round win rates.
No accuracy improvement is claimed by these integrity fixes.
