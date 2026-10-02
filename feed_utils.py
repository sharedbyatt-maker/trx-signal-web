"""TRX issue/calendar and source timestamp helpers shared by live observers."""
import os
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo


def next_issue_number(issue):
    raw = str(issue or "")
    if not raw.isdigit():
        return "NEXT"
    # TRXChart: YYYYMMDD + 10301 + four-digit daily round (0001..1440).
    if len(raw) == 17 and raw[8:13] == "10301" and int(raw[-4:]) == 1440:
        day = datetime.strptime(raw[:8], "%Y%m%d") + timedelta(days=1)
        return day.strftime("%Y%m%d") + raw[8:13] + "0001"
    return str(int(raw) + 1)


def source_time_utc(value):
    try:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=ZoneInfo(os.environ.get("TRX_SOURCE_TIMEZONE", "Asia/Yangon")))
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def feed_delay_seconds(value, now=None):
    dt = source_time_utc(value)
    if dt is None:
        return None
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise ValueError("feed delay requires a timezone-aware clock")
    return max(0, int((current.astimezone(timezone.utc) - dt).total_seconds()))


def source_time_iso(value):
    dt = source_time_utc(value)
    return dt.isoformat() if dt else None
