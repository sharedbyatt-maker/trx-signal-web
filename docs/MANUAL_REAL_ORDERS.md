# Manual real orders

The ZIP's manual order feature is integrated into the dedicated Trade menu in the private
admin dashboard. It uses the known `POST https://trxchart.com/api/bet` endpoint.
It is explicitly labelled **REAL** and never invoked by the signal engines.
Demo order placement is unavailable. The Results report mode never changes Trade’s REAL order mode.
No alternate demo endpoint is inferred from the history endpoints.

Manual orders are enabled by default with no local amount, daily count, daily
total or spacing cap. Open Trade, connect TRXChart, enter a positive
whole-number MMK amount, then confirm BIG or SMALL. The extra consent checkbox
has been removed; each order still requires its own real-money confirmation.
Login, CSRF, connected-session and request-ID checks remain in place.

The dashboard's **Enable all manual orders** button persistently enables orders
and removes all four local caps, including older environment settings. **Disable
manual orders** disables them. These settings use the same SQLite database and
revision checks as other private admin settings; they survive worker restarts.
Provider wallet balance and provider rules still determine whether an order is
accepted. No order is sent when either permission button is used.

| Environment variable | Default |
| --- | --- |
| `TRX_ORDER_ENABLED` | `1` (enabled) |
| `TRX_ORDER_MAX_AMOUNT` | `0` (unlimited) |
| `TRX_ORDER_DAILY_MAX_COUNT` | `0` (unlimited) |
| `TRX_ORDER_DAILY_MAX_TOTAL` | `0` (unlimited) |
| `TRX_ORDER_MIN_INTERVAL_SEC` | `0` (no spacing requirement) |

Explicit environment caps remain available unless overridden by the dashboard.
**Total Amount** reads the provider's verified `GET /api/user/info` balance
with a fresh API token, after history sync. It shows the REAL account balance in MMK,
with its update time. It never uses cumulative stakes or journal profit/loss.
If the provider does not report a recognized balance, the card shows unavailable;
a previous balance is labelled as last known when it cannot be refreshed.
Balance/session metadata stays encrypted in private account storage and is
available only to authenticated admins. Order outcomes wake the history worker
to refresh history and balance; this never retries an order.

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

On Windows `run_local.bat` uses the same enabled default; an explicit
`TRX_ORDER_ENABLED=0` can disable it. `run_local_orders_enabled.bat` explicitly
enables real orders. `tzdata` is included
for journal timezones, and the order calendar itself uses a fixed UTC+7 offset.
No Telegram credentials, instance database, virtual environment or ZIP git pointer
are committed. Do not place live orders merely to test this integration; the
Python and browser regression fixtures use fake provider responses.


## Trade workspace and confirmed results

Trade contains Total Amount, editable amount presets, BIG / SMALL, account
connection and recent REAL activity. Presets only edit the amount. Order permissions
are inside a collapsed disclosure. Trade Results contains date/mode filters,
daily summary and a WIN / LOSS / Pending history filter; reporting settings and
import/export tools are collapsed separately.

Trade view heartbeats activate two-second read-only REAL history checks.
Accepted or uncertain manual orders keep this fast path active for three minutes
after leaving Trade. REAL results commit before wallet work; wallet reads use a
separate fifteen-second cadence and Demo is excluded from the fast path. A cached
API token avoids repeated page fetches; a 401/403 permits one read-only token
refresh. Fast-path failures retry at 4/8/15 seconds, never minutes. Idle full-mode
sync remains once per minute with bounded backoff. These checks never repeat an order.
Notifications require a provider-confirmed settlement, so their timing depends
on provider publication and server/browser availability.

New REAL settlements are persisted atomically with the encrypted history and
exposed by authenticated GET `/api/admin/trade-feed`. The first sync is a silent
baseline. Pending-to-settled changes and later confirmed trades create bounded,
monotonic events; Demo and imported historical results do not produce alerts.
The dashboard polls this local feed every second across admin pages, including
while another admin action is busy, with
an opaque stream/cursor for reload deduplication. Optional desktop notifications
require an explicit user click and browser permission; they appear while the
open dashboard tab is in the background. This is not a push service after the
browser is closed. Alerts cover REAL account results, including activity placed
elsewhere; no unverified match to an internal order request ID is claimed.


Your orders appears immediately as WAIT before the POST response, then reads the
durable request ledger on every feed update. Provider acceptance is not a WIN.
Only an explicit provider order ID with matching side and stake, or an accepted
receipt with a verified round and side, links a settlement. A round-only match
does not assert a payout. Without a receipt, the card directs the user to verified
account activity instead of guessing by amount/time. Rejected requests show
REJECTED; unavailable responses show UNCERTAIN and are never automatically retried.
The connection panel is above the order controls, exposes Phone / Email and
Password whenever disconnected or unhealthy, and offers Connect / reconnect
account without first deleting the existing session. Connection status and LIVE
use provider sync timestamps; successful local feed reads do not reset freshness.
Pending draw placeholders are treated as unpublished numbers. Conflicting old
settled records are held unchanged with a warning while unrelated valid records
continue updating; strict manual import validation remains unchanged.

## Manual refresh and focused reports

Trade and Trade Results have labelled refresh icon buttons with a loading state.
They queue authenticated, CSRF-protected history reads and reload saved results
without retrying or creating orders. REAL refresh activates the fast path and
requests a wallet update; Demo refresh requests one full-mode read even while
Trade fast polling is active. A queued source read is not called complete until
the selected mode timestamp advances. Offline accounts can reload saved history.
Refresh preserves report date/mode, search filters and unsaved target drafts.

REAL Trade Results also maintains fast source watching; committed journal revision
changes refresh the visible report without waiting ten seconds. Results now shows
settled-only win rate, separate order/stake totals and issue/side search with a
record count and clear-filter action. Provider account orders label unpublished
results WAIT. The submission ledger remains distinct: old unlinked requests are
CHECK HISTORY, excluded from active WAIT counts, and provide Find in Results.
Empty submission panels and repeated healthy-account help are hidden; optional
account tools are collapsed. Background freshness ages quietly while refresh
actions and settlement alerts retain accessible status messages.
