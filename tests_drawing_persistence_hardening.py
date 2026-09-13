from pathlib import Path
import json, os, tempfile

server=Path("drawings_persistence.py").read_text()
client=Path("static/js/draw.js").read_text()
for token in [
    "anchorLb", "_MAX_FUTURE_OFFSET", "_quarantine_corrupt", "_latest_valid_backup",
    "DRAWINGS_STORAGE_DURABLE", "quarantined_corrupt_file", "recovered_from_backup",
]: assert token in server, token
for token in [
    "SAFETY_BACKUP_KEY", "sanitizeClientRows", "mergeRowsPreservingLocal", "serializePoint",
    "anchorLb", "offset", "CONFLICT · TAP SYNC", "DIFF · TAP SYNC", "LOCAL BKP",
    "before-import", "before-conflict-merge",
]: assert token in client, token
assert 'points: d.points.map(serializePoint)' in client
assert 'p.anchorLb != null && map.has(p.anchorLb)' in client

# Backend corrupt-state recovery should quarantine evidence and recover newest valid backup.
with tempfile.TemporaryDirectory() as td:
    os.environ["DRAWINGS_STATE_FILE"] = str(Path(td)/"state.json")
    os.environ["DRAWINGS_BACKUP_DIR"] = str(Path(td)/"backups")
    from drawings_persistence import DrawingStore
    st=DrawingStore(); st.backup_dir.mkdir(parents=True)
    valid={"schema":2,"revision":7,"updated_at":"2026-09-13T00:00:00+00:00","drawings":[]}
    (st.backup_dir/"drawings-r00000007-test.json").write_text(json.dumps(valid))
    st.path.write_text("{broken json")
    got=st.read()
    assert got["revision"]==7
    assert st.last_recovery
    assert st.last_quarantine and Path(st.last_quarantine).exists()
    assert st.path.exists()
print("Drawing Persistence Hardening tests: ALL PASSED")
