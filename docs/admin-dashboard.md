# Private Admin Dashboard

Open `/admin` and sign in with the private initial password supplied to the owner. The repository contains only its salted password hash in `admin_bootstrap.json`. An `ADMIN_PASSWORD_HASH` environment value overrides that hash. Generate overrides with Werkzeug `generate_password_hash`; never commit plaintext credentials.

## Available controls

- System: feed freshness, update time, engine and Telegram worker status, queue pressure, latest error, row count and maintenance result.
- Chart: timeframe, visible range selection and indicator defaults on the next page load. All 30 days remain loaded. Visitors can still change their current view.
- Alerts: Telegram delivery gate (checked at enqueue and worker dispatch), global browser alert gate (updated by normal state polling), and a deliberate Telegram connection test. Telegram credentials stay on the server.
- Reports: today’s L1 summary and latest 100 retained trades, date-selectable 12-Step daily report and history, latest 200 signal entries and retained 12-Step signal log. These are existing model records, not an expanded historical trade database.
- Maintenance: engine-owned 30-day snapshot refresh, feed/RSI response cache refresh and backtest invalidation, backup export and revision-checked restore, audit and delivery history.

A refresh merges source rows chronologically without rewinding `last_issue`, resetting pending signals, changing bankroll/risk rules, or replaying old notifications. No auto betting, engine pause/restart, or strategy editing is exposed.

## Storage

SQLite defaults to `instance/admin.sqlite3`. `ADMIN_DB_PATH` can point to existing persistent storage; `ADMIN_PERSISTENT_STORAGE=1` suppresses the free-hosting notice only when persistence has actually been provisioned. Render free local storage can reset on deployment or replacement. Export before redeployment and restore afterwards. Backup contains validated chart/alert settings and the latest 2,000 audit/delivery events, excluding credentials, sessions, and trading records. It is not a substitute for a persistent production database. Existing report persistence is unchanged.

Settings survive process restarts on the same filesystem. A new deployment can restore the original chart/Telegram defaults; use the backup if that happens. Keep the access file private. `ADMIN_SESSION_SECRET` can optionally provide a stable secret; otherwise sessions expire on process restart. Sessions last up to eight hours, use HttpOnly and Strict SameSite cookies, and are Secure on Render. Explicit `ADMIN_COOKIE_SECURE=1` is supported for other HTTPS hosting. All private mutations require CSRF verification. Login is limited to five failed attempts per client address in five minutes.

## Validation

Python tests cover unauthenticated API rejection, CSRF, logout, login limiting, settings validation/revision conflicts, SQLite restart persistence, backup/restore validation and maintenance preconditions. Browser tests exercise the actual login/settings APIs with deterministic fixture engine data on desktop and mobile, confirm public chart defaults, and restore fixture settings afterwards. Fixture credentials exist only in the E2E mock server.
