from pathlib import Path

# --- app.py: install isolated drawing persistence routes ---
p=Path('app.py')
s=p.read_text()
s=s.replace('from robust_integration import install_robust_routes\n','from robust_integration import install_robust_routes\nfrom drawings_persistence import install_drawings_persistence\n',1)
s=s.replace('''robust_service = install_robust_routes(core)\n''','''robust_service = install_robust_routes(core)\n# Phase 8: token-protected, additive server persistence for manual chart drawings.\n# This does not mutate legacy/Robust/feed state.\ndrawings_store = install_drawings_persistence(core.app)\n''',1)
p.write_text(s)

# --- new isolated persistence module ---
Path('drawings_persistence.py').write_text(r'''# -*- coding: utf-8 -*-
"""Token-protected persistence for manual chart drawings.

Additive only: no signal, betting, feed, Telegram, Robust, or legacy state is touched.
Writes are atomic and revision-checked; bounded backups support manual restore.
"""
from __future__ import annotations

import hmac
import json
import math
import os
import re
import shutil
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path

from flask import jsonify, request

_ALLOWED_TYPES = {"trend", "ray", "hline", "vline", "rect", "fib"}
_ALLOWED_STYLES = {"solid", "dashed", "dotted"}
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_MAX_DRAWINGS = 500
_MAX_BODY_BYTES = 1024 * 1024
_MAX_FIB_LEVELS = 64


def _utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _finite(v):
    try:
        return math.isfinite(float(v))
    except (TypeError, ValueError):
        return False


def _sanitize_drawings(value):
    if not isinstance(value, list) or len(value) > _MAX_DRAWINGS:
        raise ValueError("drawings must be a list with at most 500 items")
    out = []
    for row in value:
        if not isinstance(row, dict):
            raise ValueError("invalid drawing")
        typ = str(row.get("type") or "")
        if typ not in _ALLOWED_TYPES:
            raise ValueError("invalid drawing type")
        pts_in = row.get("points")
        need = 1 if typ in {"hline", "vline"} else 2
        if not isinstance(pts_in, list) or len(pts_in) < need or len(pts_in) > 2:
            raise ValueError("invalid drawing points")
        pts = []
        for pt in pts_in[:need]:
            if not isinstance(pt, dict) or not _finite(pt.get("p")):
                raise ValueError("invalid point")
            t = pt.get("t")
            if t is not None:
                try:
                    t = int(t)
                except (TypeError, ValueError):
                    raise ValueError("invalid point time")
                if t < 1 or t > 10_000_000:
                    raise ValueError("invalid point time")
            lb = pt.get("lb")
            if lb is not None:
                lb = str(lb)[:96]
            pts.append({"p": float(pt["p"]), "t": t, "lb": lb})

        color = str(row.get("color") or "#2962ff")
        if not _HEX.match(color):
            color = "#2962ff"
        try:
            width = max(1, min(4, int(row.get("width") or 2)))
        except (TypeError, ValueError):
            width = 2
        style = str(row.get("style") or "solid")
        if style not in _ALLOWED_STYLES:
            style = "solid"

        clean = {
            "id": str(row.get("id") or "")[:96],
            "type": typ,
            "color": color,
            "width": width,
            "style": style,
            "locked": bool(row.get("locked")),
            "hidden": bool(row.get("hidden")),
            "extendLeft": bool(row.get("extendLeft")),
            "extendRight": bool(row.get("extendRight")),
            "points": pts,
        }
        if typ == "fib":
            lvls = row.get("fibLevels") or []
            if not isinstance(lvls, list) or len(lvls) > _MAX_FIB_LEVELS:
                raise ValueError("invalid fib levels")
            clean_lvls = []
            for x in lvls:
                if isinstance(x, (int, float)) and _finite(x):
                    clean_lvls.append({"value": float(x), "enabled": True})
                elif isinstance(x, dict) and _finite(x.get("value")):
                    clean_lvls.append({"value": float(x["value"]), "enabled": x.get("enabled") is not False})
            clean.update({
                "fibLevels": clean_lvls,
                "fibReverse": bool(row.get("fibReverse")),
                "fibLabelSide": "right" if row.get("fibLabelSide") == "right" else "left",
                "fibFill": max(0.0, min(0.25, float(row.get("fibFill") or 0.0))) if _finite(row.get("fibFill") or 0.0) else 0.0,
                "fibExtendRight": bool(row.get("fibExtendRight")),
            })
        out.append(clean)
    if len(json.dumps(out, separators=(",", ":")).encode("utf-8")) > _MAX_BODY_BYTES:
        raise ValueError("drawing payload too large")
    return out


class DrawingStore:
    def __init__(self):
        self.path = Path(os.environ.get("DRAWINGS_STATE_FILE", "drawings_state.json"))
        self.backup_dir = Path(os.environ.get("DRAWINGS_BACKUP_DIR", "drawings_backups"))
        try:
            self.max_backups = max(1, min(20, int(os.environ.get("DRAWINGS_MAX_BACKUPS", "10"))))
        except (TypeError, ValueError):
            self.max_backups = 10
        self.lock = threading.RLock()

    @property
    def token(self):
        return os.environ.get("DRAWINGS_SYNC_TOKEN", "")

    def authorized(self, req):
        token = self.token
        if not token:
            return None
        supplied = req.headers.get("X-Drawings-Token", "")
        auth = req.headers.get("Authorization", "")
        if not supplied and auth.lower().startswith("bearer "):
            supplied = auth[7:].strip()
        return hmac.compare_digest(str(supplied), str(token))

    def read(self):
        with self.lock:
            if not self.path.exists():
                return {"schema": 2, "revision": 0, "updated_at": None, "drawings": []}
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if not isinstance(data, dict):
                    raise ValueError
                return {
                    "schema": 2,
                    "revision": max(0, int(data.get("revision", 0))),
                    "updated_at": data.get("updated_at"),
                    "drawings": _sanitize_drawings(data.get("drawings", [])),
                }
            except Exception:
                return {"schema": 2, "revision": 0, "updated_at": None, "drawings": []}

    def _backup_current(self, current):
        if not self.path.exists() or int(current.get("revision", 0)) <= 0:
            return
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        target = self.backup_dir / f"drawings-r{int(current['revision']):08d}-{stamp}.json"
        shutil.copy2(self.path, target)
        files = sorted(self.backup_dir.glob("drawings-r*.json"), key=lambda x: x.stat().st_mtime, reverse=True)
        for old in files[self.max_backups:]:
            try:
                old.unlink()
            except OSError:
                pass

    def write(self, drawings, expected_revision):
        with self.lock:
            current = self.read()
            if int(expected_revision) != int(current["revision"]):
                return None, current
            clean = _sanitize_drawings(drawings)
            self._backup_current(current)
            state = {
                "schema": 2,
                "revision": int(current["revision"]) + 1,
                "updated_at": _utc_now(),
                "drawings": clean,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".drawings_state.", suffix=".tmp", dir=str(self.path.parent or Path('.')))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(state, f, ensure_ascii=False, separators=(",", ":"))
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, self.path)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
            return state, None

    def backups(self):
        with self.lock:
            if not self.backup_dir.exists():
                return []
            out = []
            for path in sorted(self.backup_dir.glob("drawings-r*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    out.append({
                        "revision": int(data.get("revision", 0)),
                        "updated_at": data.get("updated_at"),
                        "count": len(data.get("drawings", [])),
                        "file": path.name,
                    })
                except Exception:
                    continue
            return out[: self.max_backups]

    def restore_backup(self, revision, expected_revision):
        with self.lock:
            candidates = sorted(self.backup_dir.glob(f"drawings-r{int(revision):08d}-*.json"), reverse=True) if self.backup_dir.exists() else []
            if not candidates:
                return "missing", None
            try:
                old = json.loads(candidates[0].read_text(encoding="utf-8"))
                drawings = _sanitize_drawings(old.get("drawings", []))
            except Exception:
                return "invalid", None
            state, conflict = self.write(drawings, expected_revision)
            if conflict is not None:
                return "conflict", conflict
            return "ok", state


def install_drawings_persistence(app):
    store = DrawingStore()

    def auth_error():
        ok = store.authorized(request)
        if ok is None:
            return jsonify({"ok": False, "error": "DRAWINGS_SYNC_TOKEN is not configured"}), 503
        if not ok:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
        return None

    @app.get("/api/drawings")
    def drawings_get():
        err = auth_error()
        if err:
            return err
        state = store.read()
        return jsonify({"ok": True, **state})

    @app.put("/api/drawings")
    def drawings_put():
        err = auth_error()
        if err:
            return err
        if request.content_length and request.content_length > _MAX_BODY_BYTES * 2:
            return jsonify({"ok": False, "error": "payload too large"}), 413
        body = request.get_json(silent=True) or {}
        try:
            expected = int(body.get("expected_revision"))
            state, conflict = store.write(body.get("drawings", []), expected)
        except (TypeError, ValueError) as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        if conflict is not None:
            return jsonify({"ok": False, "error": "revision conflict", "revision": conflict["revision"], "updated_at": conflict["updated_at"]}), 409
        return jsonify({"ok": True, **state})

    @app.get("/api/drawings/backups")
    def drawings_backups():
        err = auth_error()
        if err:
            return err
        return jsonify({"ok": True, "backups": store.backups()})

    @app.post("/api/drawings/restore")
    def drawings_restore():
        err = auth_error()
        if err:
            return err
        body = request.get_json(silent=True) or {}
        try:
            revision = int(body.get("revision"))
            expected = int(body.get("expected_revision"))
        except (TypeError, ValueError):
            return jsonify({"ok": False, "error": "invalid revision"}), 400
        status, data = store.restore_backup(revision, expected)
        if status == "missing":
            return jsonify({"ok": False, "error": "backup not found"}), 404
        if status == "conflict":
            return jsonify({"ok": False, "error": "revision conflict", "revision": data["revision"]}), 409
        if status != "ok":
            return jsonify({"ok": False, "error": "backup invalid"}), 400
        return jsonify({"ok": True, **data})

    return store
''')

# --- .gitignore runtime files ---
p=Path('.gitignore')
s=p.read_text()
if 'drawings_state.json' not in s:
    s += '\n\n# Manual Drawing Persistence v2 runtime state\ndrawings_state.json\n.drawings_state.*.tmp\ndrawings_backups/\n'
p.write_text(s)

# --- draw.js frontend persistence v2 ---
p=Path('static/js/draw.js')
s=p.read_text()
s=s.replace('''  const PREF_KEY = "trx_draw_v2_prefs";\n''','''  const PREF_KEY = "trx_draw_v2_prefs";\n  const SYNC_TOKEN_KEY = "trx_draw_sync_token";\n''',1)
s=s.replace('''  let magnet = true;\n''','''  let magnet = true;\n  let serverRevision = null, serverConflict = false, serverSyncTimer = null, syncStatusEl = null;\n''',1)

old=r'''  function save() {
    try {
      const rows = drawings.map((d) => ({
        id: d.id, type: d.type, color: d.color, width: d.width, style: d.style,
        locked: !!d.locked, hidden: !!d.hidden, extendLeft: !!d.extendLeft,
        extendRight: !!d.extendRight,
        fibLevels: d.type === "fib" ? normalizeFibLevels(d.fibLevels) : undefined,
        fibReverse: d.type === "fib" ? !!d.fibReverse : undefined,
        fibLabelSide: d.type === "fib" ? d.fibLabelSide : undefined,
        fibFill: d.type === "fib" ? d.fibFill : undefined,
        fibExtendRight: d.type === "fib" ? !!d.fibExtendRight : undefined,
        points: d.points.map((p) => ({ p: p.p, lb: p.lb || labelOf(p.t), t: p.t })),
      }));
      localStorage.setItem(STORE_KEY, JSON.stringify(rows));
    } catch (_e) {}
  }
'''
new=r'''  function serializeDrawings() {
    return drawings.map((d) => ({
      id: d.id, type: d.type, color: d.color, width: d.width, style: d.style,
      locked: !!d.locked, hidden: !!d.hidden, extendLeft: !!d.extendLeft,
      extendRight: !!d.extendRight,
      fibLevels: d.type === "fib" ? normalizeFibLevels(d.fibLevels) : undefined,
      fibReverse: d.type === "fib" ? !!d.fibReverse : undefined,
      fibLabelSide: d.type === "fib" ? d.fibLabelSide : undefined,
      fibFill: d.type === "fib" ? d.fibFill : undefined,
      fibExtendRight: d.type === "fib" ? !!d.fibExtendRight : undefined,
      points: d.points.map((p) => ({ p: p.p, lb: p.lb || labelOf(p.t), t: p.t })),
    }));
  }
  function saveLocal() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(serializeDrawings())); } catch (_e) {}
  }
  function save() { saveLocal(); queueServerSave(); }
'''
if old not in s: raise SystemExit('save block not found')
s=s.replace(old,new,1)

old2=r'''  function restore() {
    if (!api || !api.labels) return;
    restored = true;
    const map = labelIndexMap();
    try {
      const raw = JSON.parse(localStorage.getItem(STORE_KEY) || "[]");
      drawings = [];
      raw.forEach((row) => {
        const pts = [];
        (row.points || []).forEach((p) => {
          let t = null;
          if (p.lb != null && map.has(p.lb)) t = map.get(p.lb);
          else if (p.t != null) t = p.t;
          pts.push({ t, p: p.p, lb: p.lb != null ? p.lb : null });
        });
        if (pts.length >= needPoints(row.type)) drawings.push(defaults({
          ...row, id: row.id || uid(), color: row.color || "#2962ff",
          points: pts.slice(0, needPoints(row.type)),
        }));
      });
    } catch (_e) { drawings = []; }
    updatePanel();
  }
'''
new2=r'''  function replaceFromRows(raw) {
    const map = labelIndexMap(); drawings = [];
    (Array.isArray(raw) ? raw : []).forEach((row) => {
      const pts = [];
      (row.points || []).forEach((p) => {
        let t = null;
        if (p.lb != null && map.has(p.lb)) t = map.get(p.lb);
        else if (p.t != null) t = p.t;
        pts.push({ t, p: Number(p.p), lb: p.lb != null ? p.lb : null });
      });
      if (pts.length >= needPoints(row.type)) drawings.push(defaults({
        ...row, id: row.id || uid(), color: row.color || "#2962ff",
        points: pts.slice(0, needPoints(row.type)),
      }));
    });
    selectedId = null; updatePanel(); redraw();
  }
  function restore() {
    if (!api || !api.labels) return;
    restored = true;
    try { replaceFromRows(JSON.parse(localStorage.getItem(STORE_KEY) || "[]")); }
    catch (_e) { drawings = []; }
    updatePanel();
    if (syncToken()) pullServer(false);
  }

  function syncToken() { try { return localStorage.getItem(SYNC_TOKEN_KEY) || ""; } catch (_e) { return ""; } }
  function setSyncToken(v) { try { if(v)localStorage.setItem(SYNC_TOKEN_KEY,v);else localStorage.removeItem(SYNC_TOKEN_KEY); } catch(_e){} }
  function authHeaders(extra={}) { const t=syncToken(); return {...extra,...(t?{"X-Drawings-Token":t}:{})}; }
  function setSyncStatus(txt,bad=false) { if(syncStatusEl){syncStatusEl.textContent=txt;syncStatusEl.style.color=bad?"#f23645":"#9aa0aa";} }
  function queueServerSave() {
    if (!syncToken() || serverRevision == null || serverConflict) return;
    clearTimeout(serverSyncTimer); serverSyncTimer=setTimeout(()=>pushServer(),900);
  }
  async function pushServer() {
    if (!syncToken() || serverRevision == null || serverConflict) return false;
    setSyncStatus("SYNCING…");
    try {
      const r=await fetch("/api/drawings",{method:"PUT",headers:authHeaders({"Content-Type":"application/json"}),body:JSON.stringify({expected_revision:serverRevision,drawings:serializeDrawings()})});
      const j=await r.json().catch(()=>({}));
      if(r.status===401){setSyncToken("");serverRevision=null;setSyncStatus("AUTH NEEDED",true);return false;}
      if(r.status===409){serverConflict=true;setSyncStatus("CONFLICT · PULL",true);return false;}
      if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);
      serverRevision=Number(j.revision);serverConflict=false;setSyncStatus(`SYNCED r${serverRevision}`);return true;
    } catch(e){setSyncStatus("LOCAL · SERVER ERROR",true);return false;}
  }
  async function pullServer(interactive=true) {
    if(!syncToken()&&interactive){const t=window.prompt("Drawing Sync Token");if(!t)return false;setSyncToken(t.trim());}
    if(!syncToken())return false;setSyncStatus("LOADING…");
    try{
      const r=await fetch("/api/drawings",{headers:authHeaders()});const j=await r.json().catch(()=>({}));
      if(r.status===401){setSyncToken("");serverRevision=null;setSyncStatus("AUTH NEEDED",true);return false;}
      if(r.status===503){serverRevision=null;setSyncStatus("SERVER SYNC DISABLED",true);return false;}
      if(!r.ok)throw new Error(j.error||`HTTP ${r.status}`);
      serverRevision=Number(j.revision||0);serverConflict=false;
      if(Array.isArray(j.drawings)&&j.drawings.length){replaceFromRows(j.drawings);saveLocal();setSyncStatus(`PULLED r${serverRevision}`);}
      else if(drawings.length){setSyncStatus("SERVER EMPTY · UPLOADING");await pushServer();}
      else setSyncStatus(`SYNCED r${serverRevision}`);
      return true;
    }catch(e){setSyncStatus("LOCAL · SERVER ERROR",true);return false;}
  }
  function exportDrawings(){
    const payload={schema:2,exported_at:new Date().toISOString(),drawings:serializeDrawings()};
    const blob=new Blob([JSON.stringify(payload,null,2)],{type:"application/json"});const a=document.createElement("a");a.href=URL.createObjectURL(blob);a.download=`trx-drawings-${new Date().toISOString().slice(0,10)}.json`;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),1000);
  }
  function importDrawings(){
    const inp=document.createElement("input");inp.type="file";inp.accept="application/json,.json";inp.onchange=()=>{const f=inp.files&&inp.files[0];if(!f)return;const rd=new FileReader();rd.onload=()=>{try{const j=JSON.parse(String(rd.result||"{}"));const rows=Array.isArray(j)?j:j.drawings;if(!Array.isArray(rows))throw new Error();replaceFromRows(rows);save();setSyncStatus("IMPORTED · SAVED");}catch(_e){window.alert("Invalid drawing backup file");}};rd.readAsText(f);};inp.click();
  }
  async function restoreBackup(){
    if(!syncToken()){const t=window.prompt("Drawing Sync Token");if(!t)return;setSyncToken(t.trim());}
    try{const r=await fetch("/api/drawings/backups",{headers:authHeaders()});const j=await r.json();if(!r.ok)throw new Error();const list=j.backups||[];if(!list.length){window.alert("No server backups yet");return;}const msg=list.map(x=>`r${x.revision} · ${x.count} drawings · ${x.updated_at||""}`).join("\n");const v=window.prompt(`Restore which revision?\n\n${msg}`);if(v==null)return;const rev=Number(String(v).replace(/^r/i,""));if(!Number.isInteger(rev))return;const rr=await fetch("/api/drawings/restore",{method:"POST",headers:authHeaders({"Content-Type":"application/json"}),body:JSON.stringify({revision:rev,expected_revision:serverRevision})});const jj=await rr.json();if(!rr.ok)throw new Error(jj.error||"restore failed");serverRevision=Number(jj.revision);serverConflict=false;replaceFromRows(jj.drawings||[]);saveLocal();setSyncStatus(`RESTORED → r${serverRevision}`);}catch(e){setSyncStatus("RESTORE FAILED",true);}
  }
  function buildPersistenceToolbar(){
    const host=$("draw-tools");if(!host)return;const sep=document.createElement("span");sep.className="dt-sep";host.appendChild(sep);
    const mk=(txt,title,fn)=>{const b=document.createElement("button");b.type="button";b.className="dt-btn txt";b.textContent=txt;b.title=title;b.addEventListener("click",fn);host.appendChild(b);return b;};
    mk("SYNC","Connect/pull server drawings",()=>pullServer(true));mk("EXPORT","Download drawing backup",exportDrawings);mk("IMPORT","Import drawing backup",importDrawings);mk("BACKUPS","Restore a server backup",restoreBackup);
    syncStatusEl=document.createElement("span");syncStatusEl.style.cssText="font:10px Consolas,monospace;color:#9aa0aa;padding:0 4px";syncStatusEl.textContent=syncToken()?"SYNC READY":"LOCAL ONLY";host.appendChild(syncStatusEl);
  }
'''
if old2 not in s: raise SystemExit('restore block not found')
s=s.replace(old2,new2,1)

s=s.replace('''    hintEl=document.createElement("div");hintEl.className="draw-hint";hintEl.textContent=HINTS.cursor;wrapEl.appendChild(hintEl);buildPanel();bindEvents();resize();\n''','''    hintEl=document.createElement("div");hintEl.className="draw-hint";hintEl.textContent=HINTS.cursor;wrapEl.appendChild(hintEl);buildPanel();buildPersistenceToolbar();bindEvents();resize();\n''',1)
s=s.replace('''  return {onData,redraw,undo,clearAll,_dbg:()=>({tool,apiReady:!!api,count:drawings.length,selectedId,dragging:!!drag,placing:!!placing,magnet,''','''  return {onData,redraw,undo,clearAll,pullServer,pushServer,exportDrawings,_dbg:()=>({tool,apiReady:!!api,count:drawings.length,selectedId,dragging:!!drag,placing:!!placing,magnet,serverRevision,serverConflict,''',1)
p.write_text(s)

# --- tests ---
Path('tests_drawing_persistence_v2.py').write_text(r'''import os
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
for x in ["SYNC_TOKEN_KEY","serializeDrawings()","queueServerSave()","async function pullServer","async function pushServer","function exportDrawings","function importDrawings","async function restoreBackup","buildPersistenceToolbar()","CONFLICT · PULL"]: assert x in s,x
app_s=Path("app.py").read_text(); assert "install_drawings_persistence" in app_s
ign=Path(".gitignore").read_text(); assert "drawings_state.json" in ign and "drawings_backups/" in ign
print("Drawing Persistence v2 contract OK")
''')
