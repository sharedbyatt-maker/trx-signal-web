import os
import threading
import time

bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
workers = 1          # engine thread တစ်ခုပဲ ရှိရမယ် (duplicate polling မဖြစ်အောင်)
threads = 4
timeout = 120
accesslog = "-"

# Imports in a preloaded master must never start background threads: fork does
# not carry those threads into the request worker. Start them after worker init.
raw_env = ["TRX_NO_ENGINE=1"]


def _log_runtime(worker, application):
    # No credentials, endpoint URLs, positions or request bodies enter this log.
    resources = application._process_resources()
    worker.log.info("TRX runtime rss_mb=%s peak_rss_mb=%s open_fds=%s engine_alive=%s telegram_alive=%s",
                    resources['rss_mb'], resources['peak_rss_mb'], resources['open_fds'],
                    application.core._engine_thread.is_alive(),
                    application.core._tg_thread.is_alive())


def post_worker_init(worker):
    import app as application

    # A replacement worker must read changes saved since the master imported
    # the application, rather than inherit the master's old control caches.
    application.admin_store.cached = application.admin_store.read()
    application.admin_store.refresh_controls()
    os.environ.pop("TRX_NO_ENGINE", None)
    application.core.start_engine()
    application.l1_capital_service.start()
    _log_runtime(worker, application)

    def diagnostics():
        while True:
            time.sleep(60)
            _log_runtime(worker, application)

    threading.Thread(target=diagnostics, name="runtime-diagnostics", daemon=True).start()

