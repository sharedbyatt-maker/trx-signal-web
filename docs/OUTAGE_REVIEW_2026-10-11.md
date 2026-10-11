# October 10–11 availability review

Times below are Asia/Bangkok (UTC+7).

## Verified evidence

UptimeRobot monitored `HEAD /` every five minutes. Its incident began with a
503 at 23:14:41, was confirmed by multiple North American locations at
23:15:26, and resolved at 08:03:55. Application logs show successful public
API requests through 23:05:47 and `HEAD /` returning 200 at 23:09:36. The
process started again at 08:01:29; no application logs were returned for
00:00–07:59. These facts do not identify the platform's reason for stopping
or ceasing to route to the old instance.

Render's latest recorded memory-failure events were October 7. There was no
October 10–11 memory-failure event or application traceback in the inspected
views. Monthly usage was 201.55/750 hours and 2.07/5 GB bandwidth. Absence of
an event is not proof that no resource or platform failure occurred.

At inspection, public state reported `data_source=primary`, not `trongrid`.
The old instance logged primary-feed recovery and a ReadTimeout. Neither fact
proves that changing an API caused the website-level 503.

## Code-path experiments

In an isolated engine, injected upstream timeout, 401, 429 and 503 responses
all reached retry logic. Public `/` GET and HEAD and `/api/state` remained 200;
`/api/health` correctly reported unhealthy feed status as 503. The monitored
root route renders HTML and does not call the external feed. The targeted
feed, TronGrid and native SQLite lifetime tests passed (25 tests).

## Recovery improvements

The service previously ran `python app.py` (the Flask development server),
with an empty Render health-check path (TCP checks only). The health-check path
was changed to `/` to check actual HTTP responsiveness independently of feed
availability. Do not replace it with the feed-dependent `/api/health`: external
API outages should not cause restart loops or reset local state.

The production command is `gunicorn --config gunicorn.conf.py app:app`.
Gunicorn must not start engines in a preloaded master: background threads do
not survive fork. The config sets `TRX_NO_ENGINE=1` before imports and starts
the existing engines in `post_worker_init`, removing that flag only in the
worker. It retains one worker/four request threads. Replacement workers reload
settings/control caches from SQLite before engine startup, so preload cannot
reintroduce the master's older saved controls. An integration test checks both
preload modes and kills a fixture worker to verify that the replacement
worker serves requests with engine/Telegram threads running. The fixture sends
no external API or Telegram requests.

No L1/12-Step decision, stake, settlement, history or notification rule changes
are included. These are availability improvements, not a proven retrospective
root-cause repair or an always-on guarantee for Render Free. Ephemeral database
settings/credentials can still be lost on platform replacement/deploy/spin-down.

Sources: https://render.com/docs/health-checks,
https://render.com/docs/free,
https://flask.palletsprojects.com/en/stable/deploying/.
