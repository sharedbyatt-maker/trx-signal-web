# -*- coding: utf-8 -*-
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
