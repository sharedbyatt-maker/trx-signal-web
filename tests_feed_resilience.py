import os
import time

os.environ["TRX_NO_ENGINE"] = "1"

import requests
import app


class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {"data": []}
    def json(self):
        return self._payload


def run():
    original = app._original_session_get
    grace = app.FEED_GRACE_SEC
    try:
        calls = {"n": 0}
        good = FakeResponse(200, {"data": [{"issueNumber": "1", "number": 5}]})

        def flaky(url, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                return good
            raise requests.ReadTimeout("temporary")

        app._original_session_get = flaky
        url = app.core.URL_DATA + "?limit=50"
        first = app._resilient_session_get(url, timeout=6)
        second = app._resilient_session_get(url, timeout=6)
        assert first is good and second is good

        # Tail timeout gets capped to latency-sensitive tuple.
        seen = {}
        def capture(url, *args, **kwargs):
            seen["timeout"] = kwargs.get("timeout")
            return good
        app._original_session_get = capture
        app._resilient_session_get(url, timeout=99)
        assert seen["timeout"] == (2.5, app.FEED_TAIL_READ_TIMEOUT)

        # Once grace expires, a real outage must surface instead of hiding forever.
        with app._feed_cache_lock:
            app._feed_cache[url] = (time.monotonic() - grace - 1, good)
        app._original_session_get = lambda *a, **k: (_ for _ in ()).throw(requests.ReadTimeout("down"))
        try:
            app._resilient_session_get(url, timeout=6)
            raise AssertionError("expired cache should not mask outage")
        except requests.ReadTimeout:
            pass

        print("FEED RESILIENCE TESTS: ALL PASSED")
    finally:
        app._original_session_get = original


if __name__ == "__main__":
    run()
