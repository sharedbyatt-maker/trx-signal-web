from pathlib import Path

# ---- backend hardening -----------------------------------------------------
p=Path('drawings_persistence.py')
s=p.read_text()

s=s.replace('_MAX_FIB_LEVELS = 64\n', '_MAX_FIB_LEVELS = 64\n_MAX_FUTURE_OFFSET = 10000\n', 1)

old='''            lb = pt.get("lb")\n            if lb is not None:\n                lb = str(lb)[:96]\n            pts.append({"p": float(pt["p"]), "t": t, "lb": lb})\n'''
new='''            lb = pt.get("lb")\n            if lb is not None:\n                lb = str(lb)[:96]\n            anchor_lb = pt.get("anchorLb")\n            if anchor_lb is not None:\n                anchor_lb = str(anchor_lb)[:96]\n            offset = pt.get("offset")\n            if offset is not None:\n                try:\n                    offset = int(offset)\n                except (TypeError, ValueError):\n                    raise ValueError("invalid future offset")\n                if offset < 0 or offset > _MAX_FUTURE_OFFSET:\n                    raise ValueError("invalid future offset")\n            pts.append({"p": float(pt["p"]), "t": t, "lb": lb, "anchorLb": anchor_lb, "offset": offset})\n'''
if old not in s: raise SystemExit('point sanitizer anchor missing')
s=s.replace(old,new,1)

old='''        self.lock = threading.RLock()\n\n    @property\n    def token(self):\n'''
new='''        self.lock = threading.RLock()\n        self.last_recovery = None\n        self.last_quarantine = None\n\n    @property\n    def token(self):\n'''
if old not in s: raise SystemExit('store init anchor missing')
s=s.replace(old,new,1)

start=s.index('    def read(self):\n')
end=s.index('    def _backup_current(self, current):\n', start)
replacement='''    def _read_state_file(self, path):\n        data = json.loads(Path(path).read_text(encoding="utf-8"))\n        if not isinstance(data, dict):\n            raise ValueError("drawing state must be an object")\n        return {\n            "schema": 2,\n            "revision": max(0, int(data.get("revision", 0))),\n            "updated_at": data.get("updated_at"),\n            "drawings": _sanitize_drawings(data.get("drawings", [])),\n        }\n\n    def _quarantine_corrupt(self):\n        if not self.path.exists():\n            return None\n        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")\n        target = self.path.with_name(f"{self.path.name}.corrupt.{stamp}")\n        try:\n            os.replace(self.path, target)\n            self.last_quarantine = str(target)\n            return target\n        except OSError:\n            return None\n\n    def _latest_valid_backup(self):\n        if not self.backup_dir.exists():\n            return None, None\n        files = sorted(self.backup_dir.glob("drawings-r*.json"), key=lambda x: x.stat().st_mtime, reverse=True)\n        for path in files:\n            try:\n                return path, self._read_state_file(path)\n            except Exception:\n                continue\n        return None, None\n\n    def _atomic_write_state(self, state):\n        self.path.parent.mkdir(parents=True, exist_ok=True)\n        fd, tmp_name = tempfile.mkstemp(prefix=".drawings_state.", suffix=".tmp", dir=str(self.path.parent or Path('.')))\n        try:\n            with os.fdopen(fd, "w", encoding="utf-8") as f:\n                json.dump(state, f, ensure_ascii=False, separators=(",", ":"))\n                f.flush()\n                os.fsync(f.fileno())\n            os.replace(tmp_name, self.path)\n        finally:\n            if os.path.exists(tmp_name):\n                os.unlink(tmp_name)\n\n    def storage_info(self):\n        durable = str(os.environ.get("DRAWINGS_STORAGE_DURABLE", "")).lower() in {"1", "true", "yes", "on"}\n        return {\n            "mode": "durable" if durable else "host-filesystem",\n            "durable_declared": durable,\n            "recovered_from_backup": self.last_recovery,\n            "quarantined_corrupt_file": self.last_quarantine,\n        }\n\n    def read(self):\n        with self.lock:\n            if not self.path.exists():\n                return {"schema": 2, "revision": 0, "updated_at": None, "drawings": []}\n            try:\n                return self._read_state_file(self.path)\n            except Exception:\n                quarantined = self._quarantine_corrupt()\n                backup_path, recovered = self._latest_valid_backup()\n                if recovered is not None:\n                    # Preserve the recovered revision exactly; the next normal write\n                    # will advance it, while the corrupt original remains quarantined.\n                    self._atomic_write_state(recovered)\n                    self.last_recovery = backup_path.name if backup_path else "backup"\n                    return recovered\n                self.last_recovery = "no-valid-backup"\n                return {"schema": 2, "revision": 0, "updated_at": None, "drawings": [], "recovery_required": bool(quarantined)}\n\n'''
s=s[:start]+replacement+s[end:]

old='''            self.path.parent.mkdir(parents=True, exist_ok=True)\n            fd, tmp_name = tempfile.mkstemp(prefix=".drawings_state.", suffix=".tmp", dir=str(self.path.parent or Path('.')))\n            try:\n                with os.fdopen(fd, "w", encoding="utf-8") as f:\n                    json.dump(state, f, ensure_ascii=False, separators=(",", ":"))\n                    f.flush()\n                    os.fsync(f.fileno())\n                os.replace(tmp_name, self.path)\n            finally:\n                if os.path.exists(tmp_name):\n                    os.unlink(tmp_name)\n            return state, None\n'''
new='''            self._atomic_write_state(state)\n            return state, None\n'''
if old not in s: raise SystemExit('write atomic block missing')
s=s.replace(old,new,1)

old='''        state = store.read()\n        return jsonify({"ok": True, **state})\n'''
new='''        state = store.read()\n        return jsonify({"ok": True, **state, "storage": store.storage_info()})\n'''
if old not in s: raise SystemExit('GET route block missing')
s=s.replace(old,new,1)

old='''        return jsonify({"ok": True, **state})\n\n    @app.get("/api/drawings/backups")\n'''
new='''        return jsonify({"ok": True, **state, "storage": store.storage_info()})\n\n    @app.get("/api/drawings/backups")\n'''
if old not in s: raise SystemExit('PUT response block missing')
s=s.replace(old,new,1)

p.write_text(s)

# ---- client hardening ------------------------------------------------------
p=Path('static/js/draw.js')
s=p.read_text()

s=s.replace('''  const SYNC_TOKEN_KEY = "trx_draw_sync_token";\n''','''  const SYNC_TOKEN_KEY = "trx_draw_sync_token";\n  const SAFETY_BACKUP_KEY = "trx_drawings_safety_backup_v1";\n  const MAX_CLIENT_DRAWINGS = 500;\n''',1)

anchor='''  function labelOf(t) {\n    return api && api.fulls && api.fulls[t - 1] ? api.fulls[t - 1] : null;\n  }\n'''
insert='''  function labelOf(t) {\n    return api && api.fulls && api.fulls[t - 1] ? api.fulls[t - 1] : null;\n  }\n  function serializePoint(p) {\n    const lb = p.lb || labelOf(p.t);\n    const n = api && Array.isArray(api.fulls) ? api.fulls.length : 0;\n    const anchorLb = !lb && n > 0 && p.t != null && p.t > n ? api.fulls[n - 1] : null;\n    const offset = anchorLb ? Math.max(0, Math.round(Number(p.t) - n)) : null;\n    return { p: Number(p.p), lb: lb || null, t: p.t, anchorLb: anchorLb || null, offset };\n  }\n  function rowsSignature(rows) {\n    try { return JSON.stringify(rows || []); } catch (_e) { return ""; }\n  }\n  function backupLocalSnapshot(reason) {\n    try {\n      localStorage.setItem(SAFETY_BACKUP_KEY, JSON.stringify({schema:2,reason,created_at:new Date().toISOString(),drawings:serializeDrawings()}));\n    } catch (_e) {}\n  }\n  function sanitizeClientRows(value) {\n    if (!Array.isArray(value) || value.length > MAX_CLIENT_DRAWINGS) throw new Error("Invalid drawing list");\n    const allowed = new Set(["trend","ray","hline","vline","rect","fib"]);\n    return value.map((row) => {\n      if (!row || typeof row !== "object" || !allowed.has(row.type)) throw new Error("Invalid drawing type");\n      const need = needPoints(row.type);\n      if (!Array.isArray(row.points) || row.points.length < need || row.points.length > 2) throw new Error("Invalid drawing points");\n      const points = row.points.slice(0, need).map((pt) => {\n        if (!pt || !Number.isFinite(Number(pt.p))) throw new Error("Invalid drawing point");\n        const t = pt.t == null ? null : Number(pt.t);\n        if (t != null && (!Number.isInteger(t) || t < 1 || t > 10000000)) throw new Error("Invalid drawing time");\n        const offset = pt.offset == null ? null : Number(pt.offset);\n        if (offset != null && (!Number.isInteger(offset) || offset < 0 || offset > 10000)) throw new Error("Invalid future offset");\n        return {p:Number(pt.p),t,lb:pt.lb==null?null:String(pt.lb).slice(0,96),anchorLb:pt.anchorLb==null?null:String(pt.anchorLb).slice(0,96),offset};\n      });\n      const out={...row,id:String(row.id||"").slice(0,96),type:row.type,points};\n      if(row.type==="fib" && row.fibLevels!=null && (!Array.isArray(row.fibLevels) || row.fibLevels.length>64)) throw new Error("Invalid Fibonacci levels");\n      return out;\n    });\n  }\n  function mergeRowsPreservingLocal(serverRows, localRows) {\n    const merged = sanitizeClientRows(serverRows).map((x)=>JSON.parse(JSON.stringify(x)));\n    const byId = new Map(merged.map((x,i)=>[x.id,i]));\n    sanitizeClientRows(localRows).forEach((local) => {\n      const idx = local.id ? byId.get(local.id) : null;\n      if (idx == null) { merged.push(local); if(local.id)byId.set(local.id,merged.length-1); return; }\n      if (rowsSignature(merged[idx]) === rowsSignature(local)) return;\n      // Preserve both versions on a same-id conflict: local keeps the canonical id,\n      // server copy is retained under a new id so neither device's edit disappears.\n      const serverCopy={...merged[idx],id:`${merged[idx].id||"drawing"}-srv-${uid()}`};\n      merged[idx]=local; merged.push(serverCopy);\n    });\n    if (merged.length > MAX_CLIENT_DRAWINGS) throw new Error("Merged drawing limit exceeded");\n    return merged;\n  }\n'''
if anchor not in s: raise SystemExit('labelOf anchor missing')
s=s.replace(anchor,insert,1)

old='''      points: d.points.map((p) => ({ p: p.p, lb: p.lb || labelOf(p.t), t: p.t })),\n'''
new='''      points: d.points.map(serializePoint),\n'''
if old not in s: raise SystemExit('serialize points block missing')
s=s.replace(old,new,1)

old='''  function replaceFromRows(raw) {\n    const map = labelIndexMap(); drawings = [];\n    (Array.isArray(raw) ? raw : []).forEach((row) => {\n'''
new='''  function replaceFromRows(raw) {\n    const map = labelIndexMap(); drawings = [];\n    sanitizeClientRows(raw).forEach((row) => {\n'''
if old not in s: raise SystemExit('replaceFromRows header missing')
s=s.replace(old,new,1)

old='''        if (p.lb != null && map.has(p.lb)) t = map.get(p.lb);\n        else if (p.t != null) t = p.t;\n        pts.push({ t, p: Number(p.p), lb: p.lb != null ? p.lb : null });\n'''
new='''        if (p.lb != null && map.has(p.lb)) t = map.get(p.lb);\n        else if (p.anchorLb != null && map.has(p.anchorLb) && Number.isInteger(Number(p.offset))) t = map.get(p.anchorLb) + Number(p.offset);\n        else if (p.t != null) t = p.t;\n        pts.push({ t, p: Number(p.p), lb: p.lb != null ? p.lb : null, anchorLb:p.anchorLb||null, offset:p.offset==null?null:Number(p.offset) });\n'''
if old not in s: raise SystemExit('point restore block missing')
s=s.replace(old,new,1)

start=s.index('  async function pushServer() {\n')
end=s.index('  function exportDrawings(){\n',start)
newblock='''  async function pushServer() {\n    if (!syncToken() || serverRevision == null || serverConflict) return false;\n    setSyncStatus("SYNCING…");\n    try {\n      const r=await fetch("/api/drawings",{method:"PUT",headers:authHeaders({"Content-Type":"application/json"}),body:JSON.stringify({expected_revision:serverRevision,drawings:serializeDrawings()})});\n      const j=await r.json().catch(()=>({}));\n      if(r.status===401){setSyncToken("");serverRevision=null;setSyncStatus("AUTH NEEDED",true);return false;}\n      if(r.status===409){backupLocalSnapshot("revision-conflict");serverConflict=true;setSyncStatus("CONFLICT · TAP SYNC",true);return false;}\n      if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);\n      serverRevision=Number(j.revision);serverConflict=false;setSyncStatus(`SYNCED r${serverRevision}`);return true;\n    } catch(e){setSyncStatus("LOCAL · SERVER ERROR",true);return false;}\n  }\n  async function pullServer(interactive=true) {\n    if(!syncToken()&&interactive){const t=window.prompt("Drawing Sync Token");if(!t)return false;setSyncToken(t.trim());}\n    if(!syncToken())return false;setSyncStatus("LOADING…");\n    try{\n      const r=await fetch("/api/drawings",{headers:authHeaders()});const j=await r.json().catch(()=>({}));\n      if(r.status===401){setSyncToken("");serverRevision=null;setSyncStatus("AUTH NEEDED",true);return false;}\n      if(r.status===503){serverRevision=null;setSyncStatus("SERVER SYNC DISABLED",true);return false;}\n      if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);\n      const remote=sanitizeClientRows(j.drawings||[]), local=serializeDrawings();\n      const remoteRev=Number(j.revision||0), same=rowsSignature(remote)===rowsSignature(local);\n      const storage=j.storage||{};\n      if(storage.recovered_from_backup) setSyncStatus(`RECOVERED ${storage.recovered_from_backup}`);\n      if(storage.mode==="host-filesystem" && syncStatusEl) syncStatusEl.title="Server drawings use host filesystem; configure persistent storage and DRAWINGS_STORAGE_DURABLE=1 for redeploy durability.";\n\n      if(serverConflict){\n        backupLocalSnapshot("before-conflict-merge");\n        if(!interactive){serverRevision=remoteRev;setSyncStatus("CONFLICT · TAP SYNC",true);return false;}\n        if(!window.confirm("Server drawings changed on another device. Merge both versions? Cancel keeps your local drawings unchanged.")){serverRevision=remoteRev;setSyncStatus("CONFLICT PRESERVED",true);return false;}\n        const merged=mergeRowsPreservingLocal(remote,local);\n        serverRevision=remoteRev;serverConflict=false;replaceFromRows(merged);saveLocal();\n        setSyncStatus("MERGED · SAVING…");return await pushServer();\n      }\n\n      if(remote.length && local.length && !same){\n        backupLocalSnapshot("server-diff-detected");\n        serverRevision=remoteRev;serverConflict=true;\n        if(!interactive){setSyncStatus("DIFF · TAP SYNC",true);return false;}\n        if(!window.confirm("Local and server drawings differ. Merge both safely? Cancel keeps local drawings unchanged.")){setSyncStatus("DIFF PRESERVED",true);return false;}\n        const merged=mergeRowsPreservingLocal(remote,local);serverConflict=false;replaceFromRows(merged);saveLocal();return await pushServer();\n      }\n\n      serverRevision=remoteRev;serverConflict=false;\n      if(remote.length){replaceFromRows(remote);saveLocal();setSyncStatus(`PULLED r${serverRevision}`);}\n      else if(local.length){setSyncStatus("SERVER EMPTY · UPLOADING");await pushServer();}\n      else setSyncStatus(`SYNCED r${serverRevision}`);\n      return true;\n    }catch(e){setSyncStatus("LOCAL · SERVER ERROR",true);return false;}\n  }\n'''
s=s[:start]+newblock+s[end:]

old='''  function importDrawings(){\n    const inp=document.createElement("input");inp.type="file";inp.accept="application/json,.json";inp.onchange=()=>{const f=inp.files&&inp.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{try{const j=JSON.parse(String(rd.result||"{}"));const rows=Array.isArray(j)?j:j.drawings;if(!Array.isArray(rows))throw new Error();replaceFromRows(rows);save();setSyncStatus("IMPORTED · SAVED");}catch(_e){window.alert("Invalid drawing backup file");}};rd.readAsText(f);};inp.click();\n  }\n'''
new='''  function importDrawings(){\n    const inp=document.createElement("input");inp.type="file";inp.accept="application/json,.json";inp.onchange=()=>{const f=inp.files&&inp.files[0];if(!f)return;if(f.size>1024*1024){window.alert("Drawing backup is too large");return;}const rd=new FileReader();rd.onload=()=>{try{const j=JSON.parse(String(rd.result||"{}"));const rows=sanitizeClientRows(Array.isArray(j)?j:j.drawings);backupLocalSnapshot("before-import");replaceFromRows(rows);save();setSyncStatus("IMPORTED · SAVED");}catch(_e){window.alert("Invalid drawing backup file");}};rd.readAsText(f);};inp.click();\n  }\n  function restoreLocalSafetyBackup(){\n    try{const raw=localStorage.getItem(SAFETY_BACKUP_KEY);if(!raw){window.alert("No local safety backup yet");return;}const j=JSON.parse(raw);const rows=sanitizeClientRows(j.drawings||[]);if(!window.confirm(`Restore local safety backup from ${j.created_at||"unknown time"}? Current drawings will be backed up first.`))return;backupLocalSnapshot("before-local-recovery");replaceFromRows(rows);saveLocal();serverConflict=true;setSyncStatus("LOCAL BACKUP RESTORED · SYNC REVIEW",true);}catch(_e){window.alert("Local safety backup is invalid");}\n  }\n'''
if old not in s: raise SystemExit('import function anchor missing')
s=s.replace(old,new,1)

old='''    mk("SYNC","Connect/pull server drawings",()=>pullServer(true));mk("EXPORT","Download drawing backup",exportDrawings);mk("IMPORT","Import drawing backup",importDrawings);mk("BACKUPS","Restore a server backup",restoreBackup);\n'''
new='''    mk("SYNC","Connect/pull/merge server drawings",()=>pullServer(true));mk("EXPORT","Download drawing backup",exportDrawings);mk("IMPORT","Import validated drawing backup",importDrawings);mk("BACKUPS","Restore a server backup",restoreBackup);mk("LOCAL BKP","Restore latest local safety backup",restoreLocalSafetyBackup);\n'''
if old not in s: raise SystemExit('toolbar persistence buttons missing')
s=s.replace(old,new,1)

p.write_text(s)

# ---- focused tests ---------------------------------------------------------
Path('tests_drawing_persistence_hardening.py').write_text(r'''from pathlib import Path
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
''')
