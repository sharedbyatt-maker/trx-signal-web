# Repeated Render memory failures

Render Events confirmed repeated `Ran out of memory (used over 512MB)` instance
failures on October 7, 2026, including 10:08, 10:18, 10:28, 12:19, 12:28,
12:51, 12:59, 13:09 and 13:19 in Asia/Bangkok. UptimeRobot screenshots show
five-minute HTTP checks and prolonged 503 incidents. This is evidence of
memory crashes, not proof of ordinary idle spin-down. The supplied billing
snapshot shows 123.38/750 free hours and 1.5/5 GB bandwidth, below those quotas.

## Reproduced resource retention and repair

AdminStore and EngineCheckpoint used SQLite connection context managers as if
they closed the underlying connections. They only commit or roll back; native
connections, file descriptors and page caches can remain until cyclic garbage
collection. Continuous feed configuration reads exercise this path without
anyone opening the website.

A local Python 3.12 test performed 1,000 private settings reads with cyclic GC
disabled to reproduce delayed reclamation. Before the fix, it retained 1,000
open descriptors/connections and increased peak RSS by approximately 149 MB.
After the fix, the same probe retained zero descriptors/connections and had no
measurable peak RSS increase. This isolates a concrete memory retention defect;
it does not establish that every historical OOM had only this cause.

Both connection factories now preserve commit/rollback behavior and always
close in a finally block. Tests retain references and disable GC to ensure
release does not depend on runtime collection timing. `/api/health` also reports
current/peak process RSS and descriptor count on Linux, with null values when
the diagnostics are unavailable. This allows observation without paid metrics.

## Preserved behavior and limits

No L1/12-Step rule, stake, settlement, indicator, history window, delivery policy,
credential or hosting-plan change is included. Free Render can still spin down
after 15 minutes without incoming traffic or restart for platform reasons.
Existing five-minute monitoring is not a guarantee of availability.

Sources: [Python SQLite context managers](https://docs.python.org/3/library/sqlite3.html#how-to-use-the-connection-context-manager),
[Render Free](https://render.com/docs/free),
[Render health checks](https://render.com/docs/health-checks).
