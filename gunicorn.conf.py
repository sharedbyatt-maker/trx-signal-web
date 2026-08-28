import os

bind = "0.0.0.0:" + os.environ.get("PORT", "10000")
workers = 1          # engine thread တစ်ခုပဲ ရှိရမယ် (duplicate polling မဖြစ်အောင်)
threads = 4
timeout = 120
accesslog = "-"
