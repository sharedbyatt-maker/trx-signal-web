# Private Admin Dashboard

Open `/admin` and sign in with the private initial password supplied to the owner. The repository contains only its salted password hash in `admin_bootstrap.json`. An `ADMIN_PASSWORD_HASH` environment value overrides that hash. Generate overrides with Werkzeug `generate_password_hash`; never commit plaintext credentials.

## Available controls

- System: feed freshness, update time, engine and Telegram worker status, queue pressure, latest error, row count and maintenance result.
- Chart: timeframe, visible range selection and indicator defaults on the next page load. All 30 days remain loaded. Visitors can still change their current view.
- Alerts: Telegram delivery gate (checked at enqueue and worker dispatch), global browser alert gate (updated by normal state polling), and a deliberate Telegram connection test. Telegram credentials stay on the server.
- Reports: today’s L1 summary and latest 100 retained trades, date-selectable 12-Step daily report and history, latest 200 signal entries and retained 12-Step signal log. These are existing model records, not an expanded historical trade database.
- Maintenance: engine-owned 30-day snapshot refresh, feed/RSI response cache refresh and backtest invalidation, backup export and revision-checked restore, audit and delivery history.

A refresh merges source rows chronologically without rewinding `last_issue`, resetting pending signals, changing pending stakes or entry rules, or replaying old notifications. No auto betting, engine pause/restart, or entry-rule editing is exposed.

## Storage

SQLite defaults to `instance/admin.sqlite3`. `ADMIN_DB_PATH` can point to existing persistent storage; `ADMIN_PERSISTENT_STORAGE=1` suppresses the free-hosting notice only when persistence has actually been provisioned. Render free local storage can reset on deployment, platform restart or idle spin-down. Export before redeployment and restore afterwards. Backup contains validated chart/alert settings and the latest audit/delivery events (up to 2,000, trimmed to leave space for monetary history; restore accepts up to 8 MB), excluding credentials, sessions, and trading records. It is not a substitute for a persistent production database. Existing report persistence is unchanged.

Settings survive process restarts on the same filesystem. A new deployment can restore the original chart/Telegram defaults; use the backup if that happens. Keep the access file private. `ADMIN_SESSION_SECRET` can optionally provide a stable secret; otherwise sessions expire on process restart. Sessions last up to eight hours, use HttpOnly and Strict SameSite cookies, and are Secure on Render. Explicit `ADMIN_COOKIE_SECURE=1` is supported for other HTTPS hosting. All private mutations require CSRF verification. Login is limited to five failed attempts per client address in five minutes.

## Validation

Python tests cover unauthenticated API rejection, CSRF, logout, login limiting, settings validation/revision conflicts, SQLite restart persistence, backup/restore validation and maintenance preconditions. Browser tests exercise the actual login/settings APIs with deterministic fixture engine data on desktop and mobile, confirm public chart defaults, and restore fixture settings afterwards. Fixture credentials exist only in the E2E mock server.

## Strategy money controls

The sidebar separates monitoring, chart defaults, both strategies, delivery, reports, maintenance and audit. Each strategy shows immutable descriptions, entry/reset/skip rules and original defaults, alongside editable current bankroll, base bet, TP, SL and a three-tier × four-step multiplier ladder. L1 also controls its withdrawal milestone. Default L1 is bankroll 100,000 / base 500 / TP 5,000 / SL 50,000. Original 12-Step uses the configured legacy bankroll 50,000 / base 200 and has no dedicated TP or SL (0 means disabled). The first multiplier stays 1×, the ladder cannot decrease, and amounts are validated server-side. Restore defaults creates a draft; saving applies it.

Money changes are stamped after the latest known/processing source issue under the engine lock. Already-issued pending stakes are not mutated. L1 records causal setting revisions and published stakes, so replay cannot reprice prior settlements when settings change. New 12-Step initial and continuation stakes use the source issue's ladder; settlement uses the original pending stake. Bankroll and daily TP/SL produce manual observe-only guidance. Signals keep running and payout/entry/skip/reset rules remain fixed. Public strategy details and risk banners update through existing polling.

Delivery settings include master Telegram / browser switches, separate L1 / 12-Step / market gates, message type gates and quiet hours in Asia/Bangkok. Policy is checked when enqueueing and again at dispatch. `Check bot connection` uses getMe without sending; `Send test message` deliberately checks chat delivery and bypasses granular policy while respecting the master switch. Bot tokens are write only; optional overrides are encrypted with a local Fernet key (0600 permissions), and the UI only exposes masked destination/status. Removing an override restores server configuration. No tokens appear in events, backups or responses.

Backups additionally carry money timelines, issued L1 stakes and delivery policy. Credentials and encryption keys are excluded. A fresh install can restore causal monetary history; an active install applies restored money after its live source boundary. Export before redeploying on ephemeral hosting. Set Telegram credentials in deployment environment variables for durable configuration. The console does not provision persistent storage itself.

## Message studio and audit hardening
Telegram templates are editable independently for 3 channels × 8 message types. The default `{original}` retains existing formatting. Supported variables: `{original}`, `{body}`, `{title}`, `{engine}`, `{category}`. Preview uses labeled sample values and never sends a message. Original engine details are appended when neither original nor body is included. Oversized rendered templates fall back to the original message; plain text avoids markup injection. Routing, stakes and strategy rules are independent of template text. Templates are revision protected and included in backups; old backups without templates remain supported.

Restore now commits chart settings, controls, monetary boundaries, issued stake imports and events in one transaction under the engine boundary lock. Failed restores leave every group unchanged. Active installations still apply money changes only to future source issues. Delivery workers survive unexpected failures, validate Telegram success responses, bound long flood waits, and discard signals older than 55 seconds before dispatch/retry. A corrupt credential override blocks delivery rather than silently changing destinations, and can be replaced or removed.

Audit and delivery history use independent server filters and cursors across 2,000 retained events. The UI preserves drafts across navigation, shows unsaved groups, saves chart/master switches independently, and exports the currently loaded model report as JSON. Local SQLite/files remain ephemeral on free Render deployments; export backups before redeploying.

## Password and feed controls
Password changes require the current password and 12–128 character confirmation, are rate limited, store only a Werkzeug hash, invalidate all sessions and sign out the changing session. Private state is excluded from backups/audit values. Authentication revisions persist in the local SQLite file across process restarts. On free Render deployments, platform restarts or idle spin-downs, ephemeral state can reset to the server/bootstrap password; durable storage is required for permanent overrides.

Data API Connection supports public, bearer, dedicated header and query key authentication. Only HTTPS public hosts on port 443 without embedded credentials/query strings are accepted. Keys are write-only and encrypted in private state. Candidate endpoints must return compatible TRX JSON history with at least 14 valid rounds, at least 3 matching recent issues and no conflicting result digits; candidates behind the live source are rejected. Checks use a separate fetch path without altering active feed health. Saves use revision guards, queue a deep history refresh, preserve already issued stakes and discard responses fetched under an old connection revision. Tail recovery and RSI history requests use the selected endpoint/authentication. Redirects are disabled and network errors do not expose key-bearing URLs. Corrupt configuration can be replaced from the dashboard. Future providers with different game IDs or response shapes require an adapter; arbitrary APIs are not interchangeable.

Easy message editing is now the default: heading, opening text and closing text, with original engine facts included automatically. Auto preview uses a recent matching original engine message when available, otherwise a labeled sample with the current base stake. Advanced placeholder templates remain compatible. Saving locks input fields briefly to avoid overwriting concurrent drafts. Password/API/Telegram credential overrides are excluded from ordinary backups and remain ephemeral on free hosting.

## Strategy-preserving correctness and restart recovery

The RSI period, 32/68 entry thresholds, confirmation, L1 R02/R03/R05/R06,
three-tier/four-step progression, configured money settings, payout and manual
TP/SL behavior remain unchanged. On complete history, L1 outputs are checked
against golden results from commit 1286466. Missing exact target issues now have
no settlement; later results cannot substitute for the missing round. Skip
durations count provider issues, including the midnight calendar rollover.

Confluence backtests now use the existing live trailing-window digit RSI and
the same rounded decision score. Chart/12-Step/L1 Wilder RSI is unchanged.
Historical backtest metrics can change because they now describe live decisions.
API checks use signed timestamp age to reject future rounds; displayed delays
remain nonnegative.

The existing single engine saves its completed issue, pending stake, ladder,
risk counters and matching 12-Step daily ledger in one atomic SQLite checkpoint.
By default this table lives in `ADMIN_DB_PATH`; `TRX_RUNTIME_DB_PATH` optionally
selects a separate SQLite file. Startup resumes only a valid matching policy
checkpoint. Catch-up settles only exact issues, suppresses historical alerts,
and does not reprice recovered pending stakes. A corrupt or incompatible
checkpoint blocks engine startup; a checkpoint-write failure stops the engine
and exposes unhealthy status instead of silently losing recovery progress.

The dashboard JSON backup deliberately excludes the runtime checkpoint and
credentials. Use a full database backup for engine recovery. Telegram delivery
is still a separate network side effect, so a crash does not guarantee exactly
once notification delivery. CSV logs are not an atomic account ledger.

L1 replay results are reused while the published history, next target and money
revision/issued ledger are unchanged. Freshness is still checked on every read;
new history publications and corrections invalidate the cache. Unchanged
notification keys no longer rewrite the L1 runtime file every half second.

### Deployment and rollback

1. Keep Gunicorn at one worker. `requirements.txt` uses tested Python constraints;
   CI installs the committed JavaScript lockfile with `npm ci`.
2. Before the first upgrade, choose a time with no open 12-Step/legacy target.
   The old process has no checkpoint, so its in-memory pending state cannot be
   recovered automatically by the first deployment. Later restarts can resume
   checkpoints created by this version.
3. Export the dashboard backup and take a SQLite online backup (using Python's
   `sqlite3.Connection.backup` or the SQLite backup command). Do not copy a live
   database file alone. Store its matching `.key` and `.credentials` files
   privately; the JSON export does not contain them.
4. Provision durable storage externally and point `ADMIN_DB_PATH` at that mount.
   Set `ADMIN_PERSISTENT_STORAGE=1` only after verifying that the mount survives
   a restart. Set a stable `ADMIN_SESSION_SECRET` and HTTPS secure cookies.
   Local report/CSV/L1 dedupe files retain their documented hosting limits.
5. Check `/api/health`, an exact target settlement, repeated unchanged-source
   polling, and a controlled restart. Verify that the pending stake and daily
   count survive without duplicate settlement before accepting the rollout.
6. For rollback, stop the process and restore the matching pre-upgrade database
   and private vault files with the prior release. The prior code cannot resume
   the new checkpoint table; roll back at a boundary without an open target.

This change does not provision a persistent disk or change the live host's
configuration. It adds the recovery mechanism, tested cache optimization and
repeatable deployment procedure without changing the strategy presets.
