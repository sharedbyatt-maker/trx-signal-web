from pathlib import Path

s = Path("static/js/chart.js").read_text()
assert "function parseWallClock(item)" in s
assert "function timeframeBucket(item, tfMinutes, fallbackIndex)" in s
assert "bucketMinute = tf >= 60 ? 0 : Math.floor(wc.minute / tf) * tf" in s
assert "const bucketSlots = new Map()" in s
assert "bucketSlots.get(bucket.key)" in s
assert "labelMap.set(fk, slot + 1)" in s
assert "Math.floor(idx / group)" not in s
assert "legacySlot = Math.floor(fallbackIndex / tf)" in s

# Boundary examples for the same wall-clock bucketing rule.
def bucket(ts, tf):
    date, clock = ts.split(" ")
    hh, mm, *_ = map(int, clock.split(":"))
    bm = 0 if tf >= 60 else (mm // tf) * tf
    return f"{date} {hh:02d}:{bm:02d}"

assert bucket("2026-09-13 12:02:10", 5) == "2026-09-13 12:00"
assert bucket("2026-09-13 12:05:00", 5) == "2026-09-13 12:05"
assert bucket("2026-09-13 12:29:59", 15) == "2026-09-13 12:15"
assert bucket("2026-09-13 12:45:01", 15) == "2026-09-13 12:45"
assert bucket("2026-09-13 12:59:59", 60) == "2026-09-13 12:00"
assert bucket("2026-09-13 13:00:00", 60) == "2026-09-13 13:00"
for f in ["decision.py", "l1_capital.py", "app_core.py"]:
    assert Path(f).exists()
print("True Timeframe Aggregation contract OK")
