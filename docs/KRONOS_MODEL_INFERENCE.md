# Kronos BIG/SMALL real-model inference (experimental)
This is an actual inference adapter for the official `shiyu-coder/Kronos` model, NOT a predictive-accuracy guarantee. BIG/SMALL synthetic-walk candles are out-of-distribution for Kronos, and can behave randomly.

## Windows / CPU one-time setup
Python 3.10–3.12 recommended. From an ordinary terminal:
```powershell
git clone https://github.com/shiyu-coder/Kronos.git D:\\app\\Kronos
py -3.12 -m venv .venv-kronos
.venv-kronos\\Scripts\\python -m pip install --upgrade pip
.venv-kronos\\Scripts\\python -m pip install torch pandas numpy einops huggingface_hub safetensors tqdm
```
The first run needs internet to download free open weights from Hugging Face. With 8 GB RAM start with `--model mini`; small is optional.
```powershell
.venv-kronos\\Scripts\\python research/kronos/forecast.py --kronos-dir D:\\app\\Kronos --history-url "https://trx-signal-web.onrender.com/api/history?days=30" --model mini --timeframe 1 --horizon 12 --output static/data/kronos_latest.json
```
The website will automatically fetch `/static/data/kronos_latest.json` **when that file is included in a deployed commit**. Uploading local files does not change Render. Snapshot origin must exactly match the latest round in the viewer or it will be rejected as stale; snapshots become stale quickly. For realtime one-click predictions a running CPU service or scheduled compute/deploy pipeline is required. Do NOT put heavy PyTorch in the existing free Render web process.

## Safety and validation
The existing server and trade system are unchanged. This tool never places orders. Model output is not a backtested signal; compare predictions against held-out future results, majority, persistence and random baselines first. Do not claim accuracy or confidence until measured. Verify feed freshness and timestamp grouping before using forecasts.

## Isolated scheduled publication (implementation pending production verification)

The additive workflow `kronos-inference.yml` runs hourly at minute 17 UTC on
standard public GitHub Ubuntu runners. It runs CPU inference outside Gunicorn
and publishes to `kronos-forecasts`, not `main`. Render does not rebuild on each
forecast. The Kronos page reads that branch's public raw JSON directly.
Only 5m output is scheduled initially (12 forecast bars). Other timeframes show
an explicit unavailable state until real output exists. Windows can remain off.

GitHub standard public runner compute is free; this is best-effort scheduling,
not a one-minute service or availability guarantee. Schedules can be delayed or
dropped, and public schedules stop after 60 days of repository inactivity. The
small model cache stays within the default 10 GB cache allowance. No paid
Render worker/cron or commercial API is provisioned. Other free web services
that sleep, lose local files, or lack a reliable scheduler do not improve this
architecture without adding another dependency. This comparison is limited to
GitHub and Render; no claim is made that every free provider was benchmarked.

References checked 2026-11-01:
- https://docs.github.com/en/billing/concepts/product-billing/github-actions
- https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule
- https://render.com/docs/free

### Publication and recovery

`pipeline.py` freezes existing API input, checks source age (at most 5 minutes,
no more than 1 minute into the future), runs inference in a child process with a
15-minute timeout, and atomically writes output. Conflicting duplicate rounds
and timestamp reversals are rejected. Source-local timestamps are explicitly
Asia/Yangon, matching the existing API helper; APIs themselves are unchanged.
If the deployment overrides `TRX_SOURCE_TIMEZONE`, confirm the actual timezone
before enabling this workflow.

Concurrency serializes publication. An origin/timeframe already in the manifest
is skipped. Original forecast JSON is never edited. Up to 720 snapshots remain
in the working tree; older snapshots remain in branch Git history. Git history
therefore still grows: this is bounded active output, not bounded repository
history. A failed inference writes a separate failure status and preserves the
last successful manifest. The next scheduled run retries automatically.

The model and tokenizer revisions for mini are pinned in `forecast.py`; the
workflow pins official code to `67b630e67f6a18c9e9be918d9b4337c960db1e9a`.
Snapshots record revisions, torch version, seed, input SHA256, generation time,
origin candle and relative deltas. Relative deltas prevent moving 10000-round
history windows from silently shifting old forecast levels. The origin candle
may be partially observed: input ends at its original round, and evaluation
excludes all target buckets that already started by generation time.

### Evaluation scope

The page supports historical overlay selection, forecast on/off, and close MAE
versus persistence for the selected snapshot. Only completed target candles
starting after generation are eligible. Current incomplete candles are excluded.
This is a continuous synthetic-walk forecast, not a next-round BIG probability.
Random/majority baselines, aggregate walk-forward reporting, interactive replay,
and a shaded forecast zone are **not implemented yet**. No measured predictive
advantage is claimed. Public JSON metadata is an audit trail, not a cryptographic
proof of model provenance.

### Actual local verification

- Genuine official Kronos-mini CPU inference succeeded on read-only production
  history using Python 3.12 / torch 2.15.0+cpu.
- Warm-cache run: 256 input bars, 12 forecast bars, 2.745 seconds wall time,
  378028 KiB maximum child RSS. A smaller initial cold/download run took 15.935
  seconds inside the generator. These are local measurements, not GitHub runner
  timings or schedule guarantees.
- Existing pytest baseline: 374 passed. Kronos adapter/safety tests: 8 passed.
- `node tests_kronos_ui.js`: rebasing, historical evaluation, toggle and missing
  manifest checks passed using a mocked chart, not a real browser.
- Chromium installation returned a truncated/non-ZIP download. Real Playwright
  desktop/mobile QA remains required.
- Main at audit: `c9604568c553461a09bc13129f977f64dbb1b920`.
  Existing main CI run 41232746136 succeeded. Live `/kronos` and `/api/history`
  returned HTTP 200. This does not establish deployment SHA or complete UI health.
- The connected Render account did not contain this service; the owner identified
  a different account. Deployment identity and rollback capability are unverified.
  Do not merge/deploy until that baseline, full CI and real browser QA are verified.

Rollback: revert this isolated change using a normal revert PR, disable the new
schedule, and retain the separate publication branch for audit. Do not alter
production databases or trading settings. Nothing imports PyTorch into Flask.
