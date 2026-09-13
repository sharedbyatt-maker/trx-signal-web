import os
import tempfile
from pathlib import Path
from flask import Flask
from drawings_persistence import install_drawings_persistence

with tempfile.TemporaryDirectory() as td:
    os.environ["DRAWINGS_SYNC_TOKEN"]="secret-token"
    os.environ["DRAWINGS_STATE_FILE"]=str(Path(td)/"drawings_state.json")
    os.environ["DRAWINGS_BACKUP_DIR"]=str(Path(td)/"backups")
    app=Flask(__name__); store=install_drawings_persistence(app); c=app.test_client()
    assert c.get("/api/drawings").status_code==401
    h={"X-Drawings-Token":"secret-token"}
    r=c.get("/api/drawings",headers=h); assert r.status_code==200 and r.json["revision"]==0
    row={"id":"a","type":"trend","color":"#2962ff","width":2,"style":"solid","points":[{"p":100,"t":1,"lb":"1001"},{"p":102,"t":2,"lb":"1002"}]}
    r=c.put("/api/drawings",headers=h,json={"expected_revision":0,"drawings":[row]}); assert r.status_code==200 and r.json["revision"]==1
    assert Path(os.environ["DRAWINGS_STATE_FILE"]).exists()
    r=c.put("/api/drawings",headers=h,json={"expected_revision":0,"drawings":[]}); assert r.status_code==409
    r=c.put("/api/drawings",headers=h,json={"expected_revision":1,"drawings":[]}); assert r.status_code==200 and r.json["revision"]==2
    b=c.get("/api/drawings/backups",headers=h); assert b.status_code==200 and any(x["revision"]==1 for x in b.json["backups"])
    rr=c.post("/api/drawings/restore",headers=h,json={"revision":1,"expected_revision":2}); assert rr.status_code==200 and rr.json["revision"]==3 and len(rr.json["drawings"])==1

s=Path("static/js/draw.js").read_text()
for x in ["SYNC_TOKEN_KEY","serializeDrawings()","queueServerSave()","async function pullServer","async function pushServer","function exportDrawings","function importDrawings","async function restoreBackup","buildPersistenceToolbar()"]: assert x in s,x
assert ("CONFLICT · PULL" in s) or ("CONFLICT · TAP SYNC" in s)
app_s=Path("app.py").read_text(); assert "install_drawings_persistence" in app_s
ign=Path(".gitignore").read_text(); assert "drawings_state.json" in ign and "drawings_backups/" in ign
print("Drawing Persistence v2 contract OK")