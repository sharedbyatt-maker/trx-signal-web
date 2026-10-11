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

## Admin restore and input safety audit

Default money settings do not identify a fresh install. If the engine has loaded
history, processed an issue or issued a stake, restoration applies money only
after the live source boundary. It retains local issued stakes and does not
import foreign monetary timelines over a running model. An inactive, unused
installation can still restore its original causal timeline. An offline active
engine must recover a live source before restoring money controls.

New exports use schema 2 and include `expected_control_revisions`. The dashboard
replaces these with the revisions it loaded for the target installation. Restore
checks both the chart revision and every included control revision inside the
SQLite transaction; a concurrent edit returns 409 without changing any group.
Reload saved controls before retrying. Direct API clients must supply target
revisions too. Schema 1 files remain readable; the dashboard adds the same
revision guards when restoring them. Delivery/template revisions never rewind
to an imported older revision.

Controls stay disabled during initial loading and Connected appears only after
all groups load. Log pagination keeps its server-derived disabled state after
operations. Non-ASCII CSRF tokens and malformed message channel/Unicode inputs
are rejected without a server error. Chart and private-state changes enforce
the same 2,000-event retention as other audit writers. A failed maintenance audit
write starts no action and leaves the job retryable instead of stuck queued.
CI exercises the complete Python and desktop/mobile browser suites on Python
3.12 and 3.14. No entry, skip, payout or progression rules change in this audit.

## B/S streak alerts

Telegram & Alerts includes a B/S Streak Alerts card within Delivery policy.
Use Save delivery policy to persist its enable switch, start count (1–100),
repeat mode (once, every additional round, or every N rounds), and BIG/SMALL side.
The interval is measured from the start count: start 8 with interval 2 sends at
8, 10, 12, and so on. Once mode sends only when the count equals the start count.
Switching sides resets the consecutive count naturally. Changes apply to new
completed rounds; saving never sends an alert or replays old rounds.

Defaults remain both sides, start 8, every additional round. Existing database
policies and old backups receive these defaults without losing existing switches.
Older API clients that omit streak settings keep the currently saved cadence.
The existing Telegram master, Market alerts, streak switch and quiet hours still
control delivery. Preview is authenticated and CSRF-protected, uses a sample and
the saved market.streak message template, and never contacts Telegram. Streak
settings change notification scheduling only; L1 and 12-Step rules are unchanged.


### TronGrid API key and verified live rounds

Data API → TronGrid connection accepts a write-only API key. `Test TronGrid` checks read-only mainnet blocks without saving or sending messages. `Verify & save TronGrid` verifies at least three recent live results before enabling backup or live mode. Blank key retains the encrypted key; `Disable & remove key` clears it. Revision conflicts require reload. Settings and keys are excluded from exported backups; audit records contain only mode, endpoint and key-present status.

Disabled remains the default. Backup mode uses TronGrid for bounded live tails only if the primary fails or its latest round is older than 80 seconds. Live mode explicitly selects TronGrid for live tails and fails closed on errors. Startup and 30-day snapshots continue using the primary feed: this feature does not independently backfill 30 days from blockchain APIs. An outage of more than eight minutes requires primary history recovery. Exact :54 block timestamps, strict hashes and overlapping rounds are checked; incomplete blocks never become invented results. L1 and 12-Step decision and settlement rules are untouched.

The adapter derives UTC daily round IDs (`YYYYMMDD10301` + minute index 0001–1440); display timestamps use `TRX_SOURCE_TIMEZONE` (Asia/Yangon by default). It reads only `/wallet/getblock`, never wallet writes. Use your own TronGrid key, quota and backoff. Reads are serialized and head polling is throttled to three seconds; a 403/429 cools down for 60 seconds. Free Render ephemeral storage can lose the key and encryption key on restart/deploy/sleep; re-entry may be required.

### Saved versus active API status

Data API → Live API status refreshes every 10 seconds without overwriting drafts. The authenticated `/api/admin/feed/status` endpoint shows saved provider mode, endpoint, revision and a masked last-four-character key hint separately from the last successful live fetch's provider, key hint, revision, issue and UTC fetch time. Short credentials are entirely hidden. Hints are excluded from audit events and backups. No full credential is returned, and status polling makes no upstream API calls.

Backup mode normally shows Primary API active / TronGrid standby. Saving live mode or a replacement key shows Switch pending until a successful fetch uses that revision. Failures and stale fetches never receive an Active badge; the last successful identity remains visible for diagnosis. Full history requests do not replace the live source indicator. Test results verify a draft only and do not imply that the engine has switched. Observability does not modify L1 or 12-Step strategy rules.

### Dashboard refresh reliability

The sync row shows the last complete status refresh, partial failures, and browser offline state. Status, live API identity and audit/delivery refreshes settle independently before the next poll is allowed; only a failed component gets a failed badge. Returning to a visible tab or reconnecting requests an immediate refresh, without replacing settings drafts. This indicator describes dashboard refreshes, while the feed health and live API badges describe the server's data source.

Maintenance buttons stay locked while an operation is pending or the maintenance job is queued/running. Backup restore stays disabled until chart, both strategy money settings, delivery policy and message revisions have loaded. Failed startup sections can be retried using Refresh data. HTML/non-JSON error responses produce readable errors without displaying upstream page contents. Strategy rules and engine execution are unchanged.

## Private imported Trade Results

Admin → Trade Results is an authenticated, CSRF-protected manual JSON journal for
past TRXChart results. It does not call TRXChart history/order APIs, store account
credentials, place orders, or change L1 / 12-Step strategy controls.

In your own signed-in TRXChart browser, open Developer Tools → Network, open
History, and copy the history response JSON only (never request headers, cookies
or tokens). Paste it or choose a JSON file, explicitly select Real/Demo, and choose
the source timezone for timestamps without an offset. The accepted input is an
array or `{"success":true,"list":[...]}`. Each record requires full `addTime`,
17-digit string `issueNumber`, `selectType` big/small, positive `amount`, and `state`
(-1 pending, 0 loss, 1 win). Wins require gross return `profitAmount`; the net
result is gross return minus stake. Losses subtract stake. Pending results do not
contribute to P/L. Amounts support two decimal places and are stored as integer
minor units. Offset-bearing timestamps retain their explicit timezone.

Report dates use the saved calendar-day timezone (default Bangkok). They are not
rolling 24-hour windows. Real and Demo are separate. Daily TP/SL are independent
journal targets: status is shown when imported settled net P/L reaches a target;
zero disables that target. Targets neither stop the external account nor change
strategy rules. The coverage warning is always shown: imported results may be an
incomplete day, particularly when the upstream history response is size-limited.

Stable upstream order IDs enable deduplication and pending → settled updates.
Without an ID, identity uses timestamp + full issue + side + stake; ambiguous
same-time identical orders in one file are rejected rather than silently lost.
Re-importing the same file is idempotent. Conflicting settled results or changed
order details reject the whole import. Up to 5,000 records total are retained;
summary covers all selected-day records, while the table displays the latest 500.

The journal is encrypted using the existing admin vault key and optimistic
SQLite revisions. Audit events contain counts/actions, not financial records.
Private journal data is excluded from the general settings backup and public
terminal. Export Real and Demo separately with the journal export button.
Exports contain private financial history; keep them safe. Re-import restores
records but does not apply exported targets: save those separately. On Render
Free, local storage and its vault key can reset during restart/deploy; export
beforehand. This is a manual import workflow, not automatic account sync.

## Read-only browser history sync

Trade Results now offers a connection bookmark. Save its generated URL as a
bookmark, run it on the signed-in `https://trxchart.com` tab, accept the connection
in the private sync window, and open Terminal → History once. The bridge captures
that history request's authentication in the TRXChart tab only, then makes GET
requests to `/api/bet/history?size=500` and `/api/demo/history?size=500` once a
minute. It does not login again, place orders or send authentication headers,
cookies or passwords to this application. The existing provider session is used;
logout, closed tabs, browser suspension or an expired admin session pauses sync.
This is browser-assisted sync, not a 24-hour server account connection.

Only whitelisted history fields are transferred. Large JSON integer issue/order
IDs are converted to strings before parsing to preserve their exact value.
The receiver requires explicit acceptance, the exact provider origin, matching
opener window and a random connection nonce. Saves remain admin-authenticated,
CSRF-protected, encrypted, and atomic against current journal state. No CORS,
password, or strategy protections are relaxed. A successful empty Demo history is
accepted without clearing Real records. Duplicate snapshots are idempotent;
pending orders can settle. Conflicting settled results reject the snapshot.

History retrieval is limited to the latest 500 records per mode. It does not
verify full-day coverage, archive unlimited history, or make Render Free local
storage persistent. Export both modes before platform replacement/deploy. The
public terminal never receives private history. Visible Trade Results refreshes
saved rows every ten seconds without replacing target drafts. Manual import
preserves the selected report date instead of switching to today.

Verified on October 11 via the signed-in provider's history UI and client code:
Real uses `/api/bet/history`, Demo uses `/api/demo/history`, both return a successful
`list` containing full `addTime`, issue, stake, payout and state. Production sync
still requires the user to activate the connection bookmark in their browser;
local fixtures validate transport, settlement, credentials isolation and exact IDs.

Connection setup now offers a draggable bookmark on desktop, with a copy-URL fallback for mobile. Clicking the generated link inside the admin page only shows setup guidance; it does not execute provider code. Real/Demo status cards show each mode’s last successful saved sync, and mark updates older than 150 seconds as paused/delayed. Recent data is not a claim that the browser connection remains active.

## Server account history sync

Protected GET `/api/admin/trxchart-account/check` checks the fixed provider login page without sending account credentials. Provider failures report only a fixed stage label and HTTP status, never response bodies, session values or submitted credentials. HTTP 403 is treated as provider unavailability, not proof of an expired account. Page token parsing supports bounded dotted tokens as well as the original opaque format.

Trade Results now provides a private Connect TRXChart form as the primary path. It uses the provider’s observed POST `/api/auth/login` payload (`phone`, `password`, optional `twofa`), cookie session, and page-injected `X-API-Token`. Passwords and 2FA are used once and never persisted. Session cookies and the API token are encrypted in private storage, excluded from public responses, logs and general backups. This is a full account session, not a provider-issued read-only scope; explicit consent is required before connection. Provider login can invalidate other 6Lottery/Telegram/TRXChart sessions.

The isolated worker fetches the page token, checks `/api/session-alive`, and reads Real and Demo history at 60-second intervals with capped exponential retry backoff. Both histories validate before one journal merge, preserving daily targets and exact large identifiers. The transport allowlist permits only login and read-only GETs; order endpoints and redirects are forbidden. Expired sessions stop syncing without automatic re-login. Disconnect removes server credentials and invalidates in-flight imports through a revision lease, preserving journal records. A different account cannot reuse an already linked journal.

The worker starts after Gunicorn fork and is separate from L1/12-Step and the public feed. It works with browser tabs closed while the server remains running. Render Free can sleep and lose local storage; this is not a guarantee of permanent or 24-hour account connectivity. After expiry or storage reset users reconnect. Browser bookmark sync remains an advanced fallback. Live provider connection still requires the user’s explicit form consent and credential entry; fixture tests do not prove a live account has connected.
