import os
os.environ["TRX_NO_ENGINE"] = "1"

from datetime import datetime, timedelta
from pathlib import Path

import app_core
import app


def _row(day, i=1):
    issue = day.strftime("%Y%m%d") + f"000000{i:03d}"
    return {"issue": issue, "day_int": int(day.strftime("%Y%m%d"))}


def test_trim_full_history_keeps_ten_calendar_days():
    start = datetime(2026, 9, 1)
    rows = [_row(start + timedelta(days=i)) for i in range(14)]
    out = app_core.trim_full_history(rows, 10)
    assert len(out) == 10
    assert out[0]["day_int"] == 20260905
    assert out[-1]["day_int"] == 20260914


def test_boot_requests_explicit_deep_history_limit():
    src = Path("app_core.py").read_text(encoding="utf-8")
    assert 'URL_DATA + f"?limit={MAX_FULL_ROWS}"' in src
    assert 'timeout_sec = 30 if not have_full else 6' in src


def test_large_history_requests_are_not_live_tail():
    assert app._is_live_tail_url(app_core.URL_DATA + "?limit=50")
    assert app._is_live_tail_url(app_core.URL_DATA + "?limit=500")
    assert not app._is_live_tail_url(app_core.URL_DATA + "?limit=30000")
    assert not app._is_live_tail_url(app_core.URL_DATA + "?limit=45200")


def test_frontend_has_10day_range_and_authoritative_merge():
    js = Path("static/js/app.js").read_text(encoding="utf-8")
    chart = Path("static/js/chart.js").read_text(encoding="utf-8")
    html = Path("templates/index.html").read_text(encoding="utf-8")
    assert '(b || []).forEach((r) => m.set(r.issue, r));' in js
    assert 'fullRows = force ? mergeRows([], inc)' in js
    assert 'setHistoryRange(days = 1)' in chart
    assert '1440 / Math.max(1, group)' in chart
    assert 'data-days="10"' in html
    assert 'id="chart-meta"' in html
