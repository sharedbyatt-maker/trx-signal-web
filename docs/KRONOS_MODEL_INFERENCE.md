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

The page refreshes history/publication every two minutes, using the existing
`since` incremental API after its initial full load to avoid repeated large
history downloads. It supports historical
overlay selection, forecast on/off, replay, and close MAE
versus persistence for the selected snapshot. Only completed target candles
starting after generation are eligible. Current incomplete candles are excluded.
This is a continuous synthetic-walk forecast, not a next-round BIG probability.
The selected snapshot also reports an exact expected random-walk MAE and a
majority-direction baseline fitted only to its pre-origin rounds. Origin-to-target
direction counts exclude ties; these are not next-round classification accuracy.
Replay hides actual candles after the original origin. Purple area fill marks
the projection. Archive metrics aggregate up to 24 snapshots for the selected timeframe,
with completed/pending counts and baseline MAEs. Targets can overlap; these
are correlated observations, not independent accuracy trials. No measured predictive
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
- The corrected `trx web render` connection identifies service
  `srv-da8nivrtqb8s73aojamg` in the confirmed TRX Website workspace. Baseline live
  deployment `dep-dbj3p395efls73dk4gc0` runs the main commit above.
  The earlier browser/regression CI run passed on both Python versions. New
  Kronos-specific desktop/mobile E2E coverage and real inference CI are added;
  require their latest results before merge. Production deployment verification
  is still required after merge.

Rollback: revert this isolated change using a normal revert PR, disable the new
schedule, and retain the separate publication branch for audit. Do not alter
production databases or trading settings. Nothing imports PyTorch into Flask.

## Target inspection, summary and persisted reports

Kronos-only crosshair/tap inspection displays source-local target time, projected
close, completed actual close and absolute error. Already-started targets are
explicitly excluded; forming/future targets are pending. Replay never exposes
post-origin actual candle values in the inspector.

Summary cards distinguish scored versus pending targets of the selected forecast,
its generation age, and the approximate next hourly 5m run in Bangkok time.
The time shown is a schedule, not a guaranteed completion countdown.

The isolated inference job evaluates earlier immutable forecast snapshots before
new inference. `evaluation_ledger.json` retains finalized target records without
overwriting an existing ID; records expire from the active ledger after 30
Bangkok calendar days (hard cap 20000). Original forecast files remain unchanged.
Full source minute continuity from the origin through each target is required;
incomplete/gapped actual paths are not scored. Inputs after the origin are never
used to fit the majority baseline. Failed/missing snapshots do not become zero-error
samples. The active public `reports.json` contains daily sums and sample counts,
not the larger ledger; UI windows show today, 7 and 30 Bangkok calendar days.
Reports update on the hourly job, while the selected live comparison can advance
more frequently. Targets from overlapping forecasts remain correlated. Git history
continues to preserve prior versions; active retention is not a Git-history cap.


## Horizon reports and bounded historical walk-forward research

The retained pre-published evaluation ledger now reports next 1/3/6/12 candles separately. Old ledger points retain their measured values; horizon groups are derived from the immutable forecast target index. Window comparisons show baseline MAE minus model MAE in walk steps. Positive differences mean lower observed model error. The early-sample label remains until 30 distinct forecasts and 3 Bangkok calendar days are available; this is a display rule, not a statistical significance threshold. Overlapping targets are correlated at every sample size.

`research/kronos/backtest.py` freezes one history response, selects at most eight historical origins with non-overlapping 12-bar target windows, and gives the pinned genuine Kronos-mini model only 256 complete, contiguous OHLC bars ending at each cutoff. It uses the same predictor settings and preprocessing as live research, loading weights once per run. Source and target minute gaps exclude the origin. Metrics use the same persistence, exact expected random-walk absolute error, and pre-origin majority baselines. No model parameters or settings are selected from the results.

`backtest.json` is explicitly retrospective: predictions are computed now from historical prefixes, not published before those historical outcomes. It never enters the live forecast manifest or evaluation ledger. Each result records input cutoffs, final target times, model revision, and computation time. The latest bounded sample replaces the previous retrospective summary; it is never pooled with live forecasts or previous runs. Zero complete origins is shown honestly as insufficient source history. Failed backtest runs preserve the prior successful file, whose computation time remains visible, and fail the workflow. No production application import, DB mutation, or order API is involved.

Hourly publication runs the bounded backtest outside Render after genuine current inference. Publication stages the optional `backtest.json` alongside existing snapshots and reports without changing their original bytes. The backtest is currently 5m only. UI tables show sample counts and errors, not next-round win rates or promised predictive accuracy.


## One-minute research support

Kronos now publishes genuine 1m snapshots as well as the existing 5m snapshots. `batch.py` runs 1m inference on every scheduled job, freezing a separate read-only response for each model invocation, and refreshes 5m only when its newest forecast is at least 55 minutes old. Hourly research runs first; 1m inference freezes a fresh response last, so slow backtests do not delay its publication. Both have 12 forecast candles and separate status files. A failure in one timeframe preserves the other timeframe's result. The existing `backtest.json` remains the 5m retrospective summary; `backtest-1m.json` is separate. Both bounded retrospective summaries refresh hourly.

The cron requests a job at minutes 2,7,12,...57, the shortest five-minute interval supported by GitHub Actions. Runner scheduling and GitHub raw-file delivery may be delayed; this is not a guaranteed every-minute prediction service. A 1m candle timeframe does not promise a new model run every minute, an actionable next-round BIG/SMALL signal, or measured trading profitability. Already-started targets remain excluded, and expired horizons show Historical/Stale instead of Current.

The Kronos viewer polls incremental round history every 30 seconds, prevents overlapping refreshes, and adds a 30-second cache key only to mutable publication metadata. Immutable forecast URLs keep their identity. The 1m view is preferred when both timeframes are published; manually selecting 5m still works. Reports filter by the selected timeframe and label delayed measurements. Each timeframe retains up to 720 active snapshots and 20,000 measured targets within the 30 Bangkok-day cutoff; high-frequency 1m data can hit those caps sooner. Git history preserves prior immutable forecast bytes. These independent caps prevent fast 1m publications from displacing the 5m archive.

No main chart, L1, 12-step, admin, order endpoint or production model dependency is changed.


## Plain-language prediction and result view

The Kronos-only Burmese guide presents a pending target and the latest completed target above the chart. Forecast and actual values are origin-relative cumulative walk changes, so arrows refer to the entire path from the original anchor to that target; they are not per-round betting wins. A zero numerical error is labelled an exact value match. Matching nonzero signs with nonzero error is labelled matching direction with a different value. Opposite nonzero signs are labelled a direction mismatch. Ties are described as value differences, without inventing a win/loss rule or arbitrary closeness threshold.

The target list uses the same completion, contiguous-source, and generation-time eligibility gates as the existing evaluator. Pending values have no actual/error, already-started targets remain excluded, missing-source targets remain unavailable, and replay hides subsequent actual values and errors. It resets when the timeframe or forecast is unavailable. Freshness notices distinguish old forecasts, stale feeds and pending outcomes. Bangkok target times identify exactly which candle is being compared. Daily report prose explains the selected window, pooled counts, average absolute error, persistence comparison, and publication lag independently of the selected live forecast. No model, forecasting cadence, ledger, report data, evaluation metric, trade API or non-Kronos implementation changes.

## Dedicated automatic publication timer

The initial combined CI/inference workflow was active and push/manual runs succeeded, but no `schedule` event runs had been observed. A configured cron alone did not prove that recurring publication was operating. Register a separate `Kronos automatic updates` entry with explicit minutes 2,7,12,...57. It calls the existing inference/publisher through `workflow_call`, retaining the same model, freshness checks, independent 1m/5m statuses, immutable snapshots, reports and publication lock. The original workflow no longer owns a timer, avoiding two recurring schedules. The dedicated entry also runs once on changes to its own file on main, validating the reusable call without restarting Render.

Caller contents-write permission matches the existing publisher's permission. No new credential, action-write permission, secret inheritance, external scheduler, paid resource or self-dispatch loop is introduced. Only the called workflow owns publication concurrency to avoid caller/callee deadlocks. PR calls continue to skip publication, and the scheduled/default-branch call publishes normally.

Verify recurrence using the dedicated entry's actual `event: schedule` runs and subsequent forecast generation timestamps. A successful push/manual run only validates execution, not the timer. GitHub can delay/drop scheduled events; if no timer-originated runs occur after registration, recurring operation remains unverified and must be reported as such. Do not describe this as a guaranteed five-minute or every-minute prediction service.
