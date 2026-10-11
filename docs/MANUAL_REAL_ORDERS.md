# Manual real orders

The ZIP's manual order feature is integrated into Trade Results in the private
admin dashboard. It uses the known `POST https://trxchart.com/api/bet` endpoint.
It is explicitly labelled **REAL** and never invoked by the signal engines.
Demo order placement is unavailable; selecting Demo history disables the buttons.
No alternate demo endpoint is inferred from the history endpoints.

Orders remain disabled unless the server has `TRX_ORDER_ENABLED=1`. With orders
enabled, connect TRXChart, select Real history, enter a whole-number MMK amount,
approve use of real funds, then confirm BIG or SMALL. Consent clears after every
submitted attempt. Login and CSRF protections apply to the endpoint.

| Environment variable | Default |
| --- | --- |
| `TRX_ORDER_ENABLED` | disabled |
| `TRX_ORDER_MAX_AMOUNT` | 100 MMK |
| `TRX_ORDER_DAILY_MAX_COUNT` | 30 attempts |
| `TRX_ORDER_DAILY_MAX_TOTAL` | 3,000 MMK |
| `TRX_ORDER_MIN_INTERVAL_SEC` | 30 seconds |

Limits count all reserved attempts, including rejected and uncertain results.
The calendar day is Asia/Bangkok (UTC+7); cooldown also spans midnight. Limits,
timestamps and request IDs are stored in `instance/admin.sqlite3` (or the configured
`ADMIN_DB_PATH`) and survive worker restarts while that database survives. A
transaction reserves the attempt and writes its audit event before POST. It
prevents simultaneous services sharing this database from exceeding those limits.
A crash after reservation leaves an uncertain attempt, never an automatic retry.
The ledger retains 90 days; request IDs are deduplicated within that retention.
This local ledger is not an account-wide limit across separate installations.
The general admin backup does not export the order ledger. Ephemeral filesystem
loss or deletion of the database also loses these limits; use persistent storage
when restart persistence is required across host redeployments.

Each submission has a UUID request ID. Repeating the same ID returns the saved
outcome without posting again; reusing an ID with another amount or side fails.
Only HTTP 200 JSON with boolean `success: true` and no error is accepted. Empty,
malformed, oversized, ambiguous, timeout and server-error responses remain
`unknown`. Provider response text and tokens are not exposed in UI/audit events.
The HTTP body is bounded to 64 KiB. Requests are not retried or redirected.
An accepted response confirms submission, not settlement or a winning outcome.

History sync/account login and manual orders share the session-operation lock to
avoid concurrent token rotation. Token lookup failure before reservation does
not consume limits. Orders never alter chart signals, ladders, TP/SL policies or
automatic strategy execution. The displayed journal targets remain reporting
targets; the manual order caps above are separate server limits.

On Windows use `run_local.bat` for normal operation with orders disabled.
`run_local_orders_enabled.bat` explicitly enables real orders. `tzdata` is included
for journal timezones, and the order calendar itself uses a fixed UTC+7 offset.
No Telegram credentials, instance database, virtual environment or ZIP git pointer
are committed. Do not place live orders merely to test this integration; the
Python and browser regression fixtures use fake provider responses.
