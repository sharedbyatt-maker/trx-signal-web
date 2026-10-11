import os

bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
workers = 1          # engine thread တစ်ခုပဲ ရှိရမယ် (duplicate polling မဖြစ်အောင်)
threads = 4
timeout = 120
accesslog = "-"

# Imports in a preloaded master must never start background threads: fork does
# not carry those threads into the request worker. Start them after worker init.
raw_env = ["TRX_NO_ENGINE=1"]


def post_worker_init(worker):
    import app as application

    os.environ.pop("TRX_NO_ENGINE", None)
    application.core.start_engine()
    application.l1_capital_service.start()

