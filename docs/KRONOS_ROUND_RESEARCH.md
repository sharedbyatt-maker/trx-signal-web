# Kronos round research page (phase 1)
Route: /kronos. A new Main Chart toolbar link opens this independent, read-only research page.

## Confirmed source
Reads /api/history from the existing TRX BIG/SMALL feed. Does not add another API or change the engine, settlement, administration, or real orders.

The chart transforms BIG (number 5–9) into +1 and SMALL (0–4) into -1 cumulative walk steps, with base level 100, then buckets by source timestamps for 1m/5m/15m/1h. This is NOT a TRX/USDT market price chart. Gaps, missing minutes, duplicated issues, and alternate upstream timing must be considered when benchmarking.

## AI status
The website does NOT perform Kronos model inference. No fabricated accuracy/confidence values. An explicitly loaded JSON snapshot is displayed only when its schema, source, model, timeframe and latest origin issue pass validation. This is an interface contract for future offline evaluation, not proof of a trained model.

Snapshot example (illustrative only; not a prediction):
```json
{"schema":"kronos-round-snapshot-v1","data_source":"big-small-walk","model":"Kronos-small","timeframe_minutes":1,"origin_issue":"REPLACE_WITH_LATEST_ISSUE","forecast_close":[101,102]}
```
Never publish synthetic example as model output. Genuine snapshots must come from a later offline Kronos inference and causally valid walk-forward experiment. Model may have no predictive value on this out-of-distribution sequence. Benchmark vs majority, persistence, random and confidence bounds. Keep business/financial decisions separate.

## Safety and rollout
No PyTorch, Hugging Face downloads, new hosting, cron jobs, or background processes in Render. Never expose a public inference endpoint in phase 1. Existing Flask app and test suites remain the release gate.
