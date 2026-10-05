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

SQLite defaults to `instance/admin.sqlite3`. `ADMIN_DB_PATH` can point to existing persistent storage; `ADMIN_PERSISTENT_STORAGE=1` suppresses the free-hosting notice only when persistence has actually been provisioned. Render free local storage can reset on deployment or replacement. Export before redeployment and restore afterwards. Backup contains validated chart/alert settings and the latest audit/delivery events (up to 2,000, bounded below the 1 MB restore limit), excluding credentials, sessions, and trading records. It is not a substitute for a persistent production database. Existing report persistence is unchanged.

Settings survive process restarts on the same filesystem. A new deployment can restore the original chart/Telegram defaults; use the backup if that happens. Keep the access file private. `ADMIN_SESSION_SECRET` can optionally provide a stable secret; otherwise sessions expire on process restart. Sessions last up to eight hours, use HttpOnly and Strict SameSite cookies, and are Secure on Render. Explicit `ADMIN_COOKIE_SECURE=1` is supported for other HTTPS hosting. All private mutations require CSRF verification. Login is limited to five failed attempts per client address in five minutes.

## Validation

Python tests cover unauthenticated API rejection, CSRF, logout, login limiting, settings validation/revision conflicts, SQLite restart persistence, backup/restore validation and maintenance preconditions. Browser tests exercise the actual login/settings APIs with deterministic fixture engine data on desktop and mobile, confirm public chart defaults, and restore fixture settings afterwards. Fixture credentials exist only in the E2E mock server.

## Strategy money controls

The sidebar separates monitoring, chart defaults, both strategies, delivery, reports, maintenance and audit. Each strategy shows immutable descriptions, entry/reset/skip rules and original defaults, alongside editable current bankroll, base bet, TP, SL and a three-tier × four-step multiplier ladder. L1 also controls its withdrawal milestone. Default L1 is bankroll 100,000 / base 500 / TP 5,000 / SL 50,000. Original 12-Step uses the configured legacy bankroll 50,000 / base 200 and has no dedicated TP or SL (0 means disabled). The first multiplier stays 1×, the ladder cannot decrease, and amounts are validated server-side. Restore defaults creates a draft; saving applies it.

Money changes are stamped after the latest known/processing source issue under the engine lock. Already-issued pending stakes are not mutated. L1 records causal setting revisions and published stakes, so replay cannot reprice prior settlements when settings change. New 12-Step initial and continuation stakes use the source issue's ladder; settlement uses the original pending stake. Bankroll and daily TP/SL produce manual observe-only guidance. Signals keep running and payout/entry/skip/reset rules remain fixed. Public strategy details and risk banners update through existing polling.

Delivery settings include master Telegram / browser switches, separate L1 / 12-Step / market gates, message type gates and quiet hours in Asia/Bangkok. Policy is checked when enqueueing and again at dispatch. `Check bot connection` uses getMe without sending; `Send test message` deliberately checks chat delivery and bypasses granular policy while respecting the master switch. Bot tokens are write only; optional overrides are encrypted with a local Fernet key (0600 permissions), and the UI only exposes masked destination/status. Removing an override restores server configuration. No tokens appear in events, backups or responses.

Backups additionally carry money timelines, issued L1 stakes and delivery policy. Credentials and encryption keys are excluded. A fresh install can restore causal monetary history; an active install applies restored money after its live source boundary. Export before redeploying on ephemeral hosting. Set Telegram credentials in deployment environment variables for durable configuration. The console does not provision persistent storage itself.
