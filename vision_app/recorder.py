"""Durable application-layer exploration receipts and bounded inspection."""
from __future__ import annotations

import hashlib
import math
import json
import os
import sqlite3
import tempfile
import time
import uuid
from contextlib import contextmanager, closing
from pathlib import Path
from typing import Any

from vision_app.coordinator import OwnerCoordinator
from vision_app.metadata import metadata_transaction
from vision_app.store import FrameStore, StoreError, protect_new_frames

OPERATIONS = frozenset(("snapshot", "crop", "resize", "assets_register", "find",
                        "click", "swipe", "type", "key", "wait"))
SECRET_KEYS = {"text", "password", "token", "secret", "authorization", "api_key",
               "access_token", "refresh_token", "data", "base64"}
ANNOTATION_FIELDS = {"purpose", "state", "expected_postcondition", "observation",
                     "verification", "failure_reason", "insight", "next_step",
                     "completed_steps", "unresolved_issues"}

class RecorderError(ValueError):
    def __init__(self, message, *, code="RECORDER_ERROR", details=None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def annotation_schema():
    # Historical values were permissive except verification. Keep that compatibility
    # while naming every legal field and recommending text/list shapes.
    props = {k: {"description": "Semantic annotation; prefer text."}
             for k in sorted(ANNOTATION_FIELDS)}
    for k in ("completed_steps", "unresolved_issues"):
        props[k] = {"description": "Prefer an array of concise strings."}
    props["verification"] = {"type":"string","enum":["PASS","FAIL","UNKNOWN"],"default":"UNKNOWN"}
    return {"type":"object","properties":props,"additionalProperties":False,"minProperties":1}


def validate_annotation(annotation):
    if not isinstance(annotation, dict) or not annotation:
        raise RecorderError("Annotation must be a nonempty object",code="INVALID_ANNOTATION")
    unknown=set(annotation)-ANNOTATION_FIELDS
    if unknown:
        raise RecorderError("Invalid annotation fields: "+", ".join(sorted(unknown)),
                            code="INVALID_ANNOTATION",details={"unknown_fields":sorted(unknown),
                            "allowed_fields":sorted(ANNOTATION_FIELDS)})
    if annotation.get("verification","UNKNOWN") not in ("PASS","FAIL","UNKNOWN"):
        raise RecorderError("verification must be PASS, FAIL or UNKNOWN",code="INVALID_ANNOTATION",
                            details={"field":"verification","allowed":["PASS","FAIL","UNKNOWN"]})
    try:
        size=len(_json(annotation))
    except (TypeError,ValueError):
        raise RecorderError("Annotation must be valid JSON",code="INVALID_ANNOTATION") from None
    if size>8000:
        raise RecorderError("Annotation too large",code="INVALID_ANNOTATION",details={"max_serialized_chars":8000})



def _json(value):
    return json.dumps(value, ensure_ascii=True, allow_nan=False, default=str)


def _clean(value):
    if isinstance(value, dict):
        return {k: "[REDACTED]" if k.lower() in SECRET_KEYS else _clean(v)
                for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value[:100]] + ([{"omitted_items":len(value)-100}] if len(value)>100 else [])
    if isinstance(value, str):
        return value.encode("utf-16", "surrogatepass").decode("utf-16", "replace")[:4000]
    if isinstance(value, float) and not math.isfinite(value):
        return str(value)
    return value


def _id(prefix):
    return prefix + "_" + uuid.uuid4().hex


def _decode(row):
    result = dict(row)
    for key in ("inputs", "result", "error", "evidence", "annotation"):
        if key in result and result[key] is not None:
            result[key] = json.loads(result[key])
    return result


class Recorder:
    def __init__(self, store: FrameStore):
        self.store = store
        self.path = store.store_dir / "recorder.sqlite"
        with metadata_transaction(self.store), self.db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS sessions(
                session_id TEXT PRIMARY KEY, name TEXT NOT NULL, goal TEXT NOT NULL,
                device_id TEXT NOT NULL, workspace TEXT NOT NULL,
                created_at REAL NOT NULL, updated_at REAL NOT NULL, status TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS events(
                event_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions,
                sequence INTEGER NOT NULL, timestamp REAL NOT NULL, completed_at REAL,
                operation TEXT NOT NULL, device_id TEXT NOT NULL, status TEXT NOT NULL,
                inputs TEXT NOT NULL, result TEXT, error TEXT, evidence TEXT NOT NULL,
                UNIQUE(session_id, sequence));
            CREATE TABLE IF NOT EXISTS annotations(
                annotation_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions,
                event_id TEXT NOT NULL REFERENCES events, timestamp REAL NOT NULL,
                kind TEXT NOT NULL, annotation TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS event_filter ON events(session_id,operation,status,sequence);
            CREATE INDEX IF NOT EXISTS annotation_filter ON annotations(session_id,timestamp);
            CREATE TABLE IF NOT EXISTS evidence_revision(
                session_id TEXT PRIMARY KEY, generation INTEGER NOT NULL);
            """)
            for table, operation in (("sessions", "UPDATE"), ("events", "INSERT"),
                                     ("events", "UPDATE"), ("annotations", "INSERT")):
                db.execute(f"""
                    CREATE TRIGGER IF NOT EXISTS evidence_{table}_{operation}
                    AFTER {operation} ON {table}
                    BEGIN
                        INSERT INTO evidence_revision VALUES (NEW.session_id, 1)
                        ON CONFLICT(session_id) DO UPDATE SET generation=generation+1;
                    END
                """)

    @contextmanager
    def db(self):
        with closing(sqlite3.connect(self.path, timeout=120)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db

    def _session(self, db, sid):
        row = db.execute("SELECT * FROM sessions WHERE session_id=?", (sid,)).fetchone()
        if not row:
            raise RecorderError("Unknown session",code="SESSION_NOT_FOUND")
        return dict(row)

    def _create_session(self, db, name, goal, device):
        """Insert a session in a caller-owned transaction (also used by recovery)."""
        if not all(isinstance(x, str) and x.strip() and len(x) <= 4000 for x in (name, goal, device)):
            raise RecorderError("name, goal and device are required (max 4000 characters)")
        sid, now = _id("ses"), time.time()
        db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                   (sid, _clean(name), _clean(goal), _clean(device), str(self.store.store_dir), now, now, "active"))
        return self._session(db, sid)

    def start(self, name, goal, device):
        with metadata_transaction(self.store), self.db() as db:
            return self._create_session(db, name, goal, device)

    def status(self, sid):
        with self.db() as db:
            return self._session(db, sid)

    def evidence_revision(self, sid):
        with self.db() as db:
            row = db.execute("SELECT generation FROM evidence_revision WHERE session_id=?",
                             (sid,)).fetchone()
        return row[0] if row else 0

    def transition(self, sid, action):
        allowed = {"pause": ("active", "paused"), "resume": ("paused", "active"),
                   "stop": (("active", "paused"), "stopped")}
        before, after = allowed[action]
        with self._session_device(sid), metadata_transaction(self.store), self.db() as db:
            session = self._session(db, sid)
            if session["status"] not in ((before,) if isinstance(before, str) else before):
                raise RecorderError("Invalid session transition")
            db.execute("UPDATE sessions SET status=?,updated_at=? WHERE session_id=?",
                       (after, time.time(), sid))
        return self.status(sid)

    @staticmethod
    def _page(limit, after):
        if not isinstance(limit, int) or not 1 <= limit <= 50 or not isinstance(after, int) or after < 0:
            raise RecorderError("limit must be 1..50 and after must be a nonnegative integer")

    def list_sessions(self, limit=20, after=0):
        self._page(limit, after)
        with self.db() as db:
            rows = db.execute("SELECT rowid AS cursor,* FROM sessions WHERE rowid>? ORDER BY rowid LIMIT ?",
                              (after, limit+1)).fetchall()
        return self._paged(rows, limit, "cursor")

    @staticmethod
    def _paged(rows, limit, key):
        items = [_decode(r) for r in rows[:limit]]
        return {"items": items, "next_cursor": items[-1][key] if len(rows) > limit else None}

    def _pin(self, fid, device, evidence):
        if not fid or not isinstance(fid, str):
            return
        with metadata_transaction(self.store):
            try:
                frame = self.store.get_frame(fid)
            except StoreError:
                return  # Original service reports missing/invalid reference.
            if frame.device_id != device:
                raise RecorderError("Frame device differs from session",code="SESSION_SCOPE_MISMATCH")
            if not self.store.resolve_image_path(frame.image_path).is_file():
                return
            self.store.set_protected(fid)
        if fid not in evidence["frames"]:
            evidence["frames"].append(fid)

    def _asset(self, name, device, evidence):
        from vision_app.assets import AssetRegistry
        if not name or not isinstance(name, str):
            return
        try:
            # One committed alias: metadata and bytes are never a mixed pair.
            registry = AssetRegistry(self.store.store_dir)
            asset, data, revision_id = registry.snapshot(name)
        except StoreError:
            return
        if asset.device_id is not None and asset.device_id != device:
            raise RecorderError("Asset source device differs from session",code="SESSION_SCOPE_MISMATCH")
        self._pin(asset.source_frame_id, device, evidence)
        src = Path(asset.image_path)
        if not src.resolve().is_relative_to((self.store.store_dir / "assets").resolve()):
            return
        digest = hashlib.sha256(data).hexdigest()
        item = {**asset.to_dict(), "sha256": digest,
                "retained_path": self._retain_bytes(digest, data)}
        if revision_id is not None:
            item["asset_revision_id"] = revision_id
        if item not in evidence["assets"]:
            evidence["assets"].append(item)

    def _retain_bytes(self, digest, data):
        dest = self.store.store_dir / "recorded_assets" / (digest + ".png")
        dest.parent.mkdir(exist_ok=True)
        if not dest.exists():
            with tempfile.TemporaryDirectory(prefix=".retaining_", dir=dest.parent) as staging:
                from vision_app.store import _atomic_write_bytes
                candidate = Path(staging) / dest.name
                _atomic_write_bytes(candidate, data)
                with metadata_transaction(self.store):
                    if not dest.exists():
                        os.replace(candidate, dest)
        if hashlib.sha256(dest.read_bytes()).hexdigest() != digest:
            raise RecorderError("Retained asset bytes do not match digest",code="STORE_ERROR")
        return str(dest.relative_to(self.store.store_dir))

    def retain_asset_revision(self, revision_id, device, evidence, *, session_id=None):
        """C03 seam: pin one exact immutable revision and retain its digest.

        Scope is device-wide or exactly the given session; never a global alias.
        Returns the evidence item appended for the same event.
        """
        from vision_app.asset_revisions import AssetRevisionStore
        revisions = AssetRevisionStore(self.store.store_dir, frame_store=self.store)
        with revisions.pin(revision_id, device=device, session_id=session_id) as pinned:
            return self._retain_pinned_asset(pinned, device, evidence)

    def _retain_pinned_asset(self, pinned, device, evidence):
        rev = pinned.revision
        self._pin(rev["source_frame_id"], device, evidence)
        item = {**rev, "sha256": rev["png_sha256"],
                "retained_path": self._retain_bytes(rev["png_sha256"], pinned.png_bytes)}
        if item not in evidence["assets"]:
            evidence["assets"].append(item)
        return item

    def _ref(self, rid, device, evidence):
        from vision_app.assets import RefRegistry
        if not rid or not isinstance(rid, str):
            return
        try:
            ref = RefRegistry(self.store.store_dir).get(rid)
        except StoreError:
            return
        if ref.device_id != device:
            raise RecorderError("Reference device differs from session",code="SESSION_SCOPE_MISMATCH")
        self._pin(ref.frame_id, device, evidence)
        if rid not in evidence["references"]:
            evidence["references"].append(rid)

    def _relations(self, value, device, evidence):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in ("frame", "frame_id", "source_frame_id", "parent_id", "baseline", "baseline_frame_id"):
                    self._pin(v, device, evidence)
                elif k in ("ref", "ref_id"):
                    self._ref(v, device, evidence)
                if isinstance(v, (dict, list)):
                    self._relations(v, device, evidence)
        elif isinstance(value, list):
            for item in value:
                self._relations(item, device, evidence)

    def execute(self, sid, operation, inputs, invoke):
        """Invoke once; payload is normalized adapter JSON, never MCP image content."""
        with self._session_device(sid):
            return self._execute_locked(sid, operation, inputs, invoke, check_ref_session=True)

    @contextmanager
    def _session_device(self, sid, *, legacy=True):
        device = self.status(sid)["device_id"]
        coordinator = OwnerCoordinator(self.store)
        with coordinator.device_owner(device, legacy=legacy) as owner:
            if owner is None:
                raise RecorderError("Session device is busy", code="DEVICE_BUSY")
            with coordinator.recorded_device(owner):
                yield

    def _execute_locked(self, sid, operation, inputs, invoke, *,
                        pinned_asset=None, check_ref_session=False):
        from vision_app.assets import recorded_asset_snapshots
        with recorded_asset_snapshots(self.store):
            return self._execute_event(sid, operation, inputs, invoke, pinned_asset, check_ref_session)

    def _execute_event(self, sid, operation, inputs, invoke, pinned_asset, check_ref_session):
        eid, now = _id("evt"), time.time()
        evidence = {"frames": [], "assets": [], "references": []}
        with metadata_transaction(self.store), self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            session = self._session(db, sid)
            if session["status"] != "active":
                raise RecorderError("Session is not active",code="SESSION_INACTIVE")
            device = session["device_id"]
            seq = db.execute("SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE session_id=?",
                             (sid,)).fetchone()[0]
            db.execute("INSERT INTO events VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                       (eid, sid, seq, now, None, operation, device, "pending",
                        _json(_clean(inputs)), None, None, _json(evidence)))
        result, error, status = None, None, "failed"
        token = protect_new_frames.set(True)
        try:
            asset_revision_id = None
            if inputs.get("device") is not None and inputs["device"] != device:
                raise RecorderError("Operation device differs from session",code="SESSION_SCOPE_MISMATCH")
            if operation == "find" and inputs.get("max_results", 10) > 100:
                raise RecorderError("Recorded find max_results must be <= 100")
            if check_ref_session and operation == "click" and isinstance(inputs.get("ref"), str):
                from vision_app.epochs import DeviceEpochs
                epochs = DeviceEpochs(self.store)
                binding = epochs.ref_binding(inputs["ref"])
                stamp = epochs.ref_epoch(inputs["ref"])
                if (binding is not None and (binding["device"], binding["session_id"]) != (device, sid)
                        or stamp is not None and (stamp.device, stamp.session_id) != (device, sid)):
                    raise RecorderError("Reference belongs to a different session", code="SCOPE_MISMATCH")
                if binding is not None:
                    asset_revision_id = binding["revision_id"]
            self._relations(inputs, device, evidence)
            if pinned_asset is not None:
                self._retain_pinned_asset(pinned_asset, device, evidence)
            elif asset_revision_id is not None:
                self.retain_asset_revision(asset_revision_id, device, evidence, session_id=sid)
            if operation == "assets_register":
                self._asset(inputs.get("name"), device, evidence)
            if operation in ("find", "wait") and pinned_asset is None:
                self._asset(inputs.get("target") or inputs.get("image_target"), device, evidence)
            with metadata_transaction(self.store), self.db() as db:
                db.execute("UPDATE events SET evidence=? WHERE event_id=?",(_json(evidence),eid))
            result = invoke()
            error = result.get("error") if not result.get("ok", False) else None
            status = "success" if result.get("ok", False) else "failed"
            self._relations(result, device, evidence)
            if operation == "assets_register" and status == "success":
                self._asset(inputs.get("name"), device, evidence)
        except Exception as exc:
            error = {"code": getattr(exc, "code", type(exc).__name__), "message": str(exc)}
            result = {"ok": False, "error": error, "operation_result": None}
            from vision_app.waits import WaitFailure
            if operation == "wait" and isinstance(exc, WaitFailure):
                observation = exc.observation
                try:
                    self._relations(observation, device, evidence)
                    result["operation_result"] = observation
                except RecorderError as scope_error:
                    error = {"code":scope_error.code,"message":str(scope_error)}
                    result["error"] = error
            status = "failed"
        finally:
            protect_new_frames.reset(token)
        if error and "TIMEOUT" in str(error.get("code", "")).upper():
            status = "timeout"
        if operation == "type" and error:
            error = {"code": error.get("code"), "message": "[REDACTED type error]"}
            result = {"ok": False, "error": error}
        with metadata_transaction(self.store), self.db() as db:
            db.execute("UPDATE events SET completed_at=?,status=?,result=?,error=?,evidence=? WHERE event_id=?",
                       (time.time(), status, _json(_clean(result)), _json(_clean(error)),
                        _json(evidence), eid))
            db.execute("UPDATE sessions SET updated_at=? WHERE session_id=?", (time.time(), sid))
        return {**result, "event_id": eid, "session_id": sid, "sequence": seq}


    def events(self, sid, limit=20, after=0, operation=None, status=None):
        self._page(limit, after)
        with self.db() as db:
            self._session(db, sid)
            rows = db.execute("""SELECT * FROM events WHERE session_id=? AND sequence>?
                AND (? IS NULL OR operation=?) AND (? IS NULL OR status=?)
                ORDER BY sequence LIMIT ?""", (sid, after, operation, operation, status, status, limit+1)).fetchall()
        page = self._paged(rows, limit, "sequence")
        # The event detail endpoint provides full structured payload.
        for item in page["items"]:
            item.pop("inputs")
            item.pop("result")
        return page

    def event(self, sid, event_id):
        with self.db() as db:
            self._session(db, sid)
            row = db.execute("SELECT * FROM events WHERE session_id=? AND event_id=?", (sid,event_id)).fetchone()
        if not row:
            raise RecorderError("Event not found in session",code="EVENT_NOT_FOUND")
        return _decode(row)

    def annotate(self, sid, event_id, annotation, kind="annotation"):
        validate_annotation(annotation)
        aid = _id("ann")
        with metadata_transaction(self.store), self.db() as db:
            self.event(sid, event_id)
            db.execute("INSERT INTO annotations VALUES (?,?,?,?,?,?)",
                       (aid,sid,event_id,time.time(),kind,_json(_clean(annotation))))
        return {"annotation_id": aid, "event_id": event_id, "kind": kind}

    def annotations(self, sid, limit=20, after=0, kind=None):
        self._page(limit, after)
        with self.db() as db:
            self._session(db, sid)
            rows = db.execute("""SELECT rowid AS cursor,* FROM annotations WHERE session_id=? AND rowid>?
                AND (? IS NULL OR kind=?) ORDER BY rowid LIMIT ?""", (sid,after,kind,kind,limit+1)).fetchall()
        return self._paged(rows,limit,"cursor")

    def summary(self,sid):
        with self.db() as db:
            session = self._session(db,sid)
            counts = dict(db.execute("SELECT status,count(*) FROM events WHERE session_id=? GROUP BY status",(sid,)).fetchall())
            annotations = db.execute("SELECT count(*) FROM annotations WHERE session_id=?",(sid,)).fetchone()[0]
        return {"session":session,"event_counts":counts,"annotation_count":annotations}

    def history(self,sid,limit=20,after=0):
        page = self.events(sid,limit,after)
        return {"items":[{"event_id":e["event_id"],"sequence":e["sequence"],**e["evidence"]} for e in page["items"]],
                "next_cursor":page["next_cursor"]}

    def asset_evidence(self,sid,limit=20,after=0):
        """Distinct revisions ordered by first recorded occurrence (stable append-only cursor). """
        self._page(limit,after)
        with self.db() as db:
            self._session(db,sid)
            rows=db.execute("""WITH revisions AS (
                SELECT e.event_id,e.sequence,a.value AS asset,
                ROW_NUMBER() OVER (PARTITION BY json_extract(a.value,'$.name'),
                    json_extract(a.value,'$.sha256') ORDER BY e.sequence,a.key) AS rank
                FROM events e, json_each(e.evidence,'$.assets') a WHERE e.session_id=?),
                numbered AS (
                    SELECT event_id,sequence,asset,ROW_NUMBER() OVER (ORDER BY sequence,
                        json_extract(asset,'$.name'),json_extract(asset,'$.sha256')) AS cursor
                    FROM revisions WHERE rank=1)
                SELECT * FROM numbered WHERE cursor>? ORDER BY cursor LIMIT ?""",(sid,after,limit+1)).fetchall()
        items=[{"event_id":r["event_id"],"sequence":r["sequence"],"asset":json.loads(r["asset"]),"cursor":r["cursor"]} for r in rows[:limit]]
        return {"items":items,"next_cursor":items[-1]["cursor"] if len(rows)>limit else None}

    def resume_context(self,sid,limit=10):
        self._page(limit,0)
        with self.db() as db:
            session = self._session(db,sid)
            recent = db.execute("SELECT * FROM events WHERE session_id=? ORDER BY sequence DESC LIMIT ?",(sid,limit)).fetchall()
            cp = db.execute("SELECT * FROM annotations WHERE session_id=? AND kind='checkpoint' ORDER BY rowid DESC LIMIT 1",(sid,)).fetchone()
            anns = db.execute("SELECT * FROM annotations WHERE session_id=? ORDER BY rowid DESC LIMIT ?",(sid,limit)).fetchall()
            verified_row = db.execute("SELECT * FROM annotations WHERE session_id=? AND json_extract(annotation, '$.verification')='PASS' ORDER BY rowid DESC LIMIT 1",(sid,)).fetchone()
            asset_rows = db.execute("""WITH revisions AS (
                SELECT e.event_id,e.sequence,a.value AS asset,
                ROW_NUMBER() OVER (PARTITION BY json_extract(a.value,'$.name'),
                    json_extract(a.value,'$.sha256') ORDER BY e.sequence DESC,a.key DESC) AS rank
                FROM events e, json_each(e.evidence,'$.assets') a WHERE e.session_id=?)
                SELECT event_id,sequence,asset FROM revisions WHERE rank=1
                ORDER BY sequence DESC LIMIT ?""",(sid,limit+1)).fetchall()
            failures = db.execute("SELECT * FROM events WHERE session_id=? AND status!='success' ORDER BY sequence DESC LIMIT ?",(sid,limit)).fetchall()
        def brief(r):
            e = _decode(r)
            return {k:e[k] for k in ("event_id","sequence","operation","status","evidence","error")}
        latest = [_decode(r) for r in anns]
        verified = _decode(verified_row) if verified_row else None
        checkpoint = _decode(cp) if cp else None
        if checkpoint:
            checkpoint["event_evidence"] = self.event(sid,checkpoint["event_id"])["evidence"]
        return {"session":session,"latest_checkpoint":checkpoint,"latest_verified_annotation":verified,
                "recent_events":[brief(r) for r in recent],"recent_annotations":latest,
                "recent_non_success":[brief(r) for r in failures],
                "recent_asset_evidence":[{"event_id":r["event_id"],"sequence":r["sequence"],"asset":json.loads(r["asset"])} for r in asset_rows[:limit]],
                "more_asset_evidence":len(asset_rows)>limit,
                "note":"Semantic state and completed steps are explicit annotations/checkpoints, not inferred from execution."}

    def query(self, action, **args):
        sid = args.pop("session_id",None)
        if action == "start": return self.start(**args)
        if action == "list": return self.list_sessions(**args)
        if not sid: raise RecorderError("session_id is required")
        if action in ("pause","resume","stop"): return self.transition(sid,action)
        if action == "status": return self.status(sid)
        if action in ("inspect","summary"): return self.summary(sid)
        if action == "events": return self.events(sid,**args)
        if action == "event": return self.event(sid,**args)
        if action in ("annotate","checkpoint"): return self.annotate(sid,kind="checkpoint" if action=="checkpoint" else "annotation",**args)
        if action == "annotations": return self.annotations(sid,**args)
        if action == "history": return self.history(sid,**args)
        if action == "asset-evidence": return self.asset_evidence(sid,**args)
        if action == "latest-checkpoint": return self.resume_context(sid,1)["latest_checkpoint"]
        if action == "resume-context": return self.resume_context(sid,**args)
        raise RecorderError("Unknown recorder action")

def record_tool_definitions():
    string = {"type":"string"}
    integer = {"type":"integer","minimum":0}
    page = {"limit":{"type":"integer","minimum":1,"maximum":50},"after":integer}
    specs = {
        "start": ({"name":string,"goal":string,"device":string}, ["name","goal","device"]),
        "list": (page, []),
        "status": ({}, []), "pause": ({}, []), "resume": ({}, []), "stop": ({}, []),
        "inspect": ({}, []), "summary": ({}, []),
        "events": ({**page,"operation":string,"status":{"type":"string","enum":["success","failed","timeout","pending"]}}, []),
        "event": ({"event_id":string}, ["event_id"]),
        "annotate": ({"event_id":string,"annotation":annotation_schema()}, ["event_id","annotation"]),
        "checkpoint": ({"event_id":string,"annotation":annotation_schema()}, ["event_id","annotation"]),
        "annotations": ({**page,"kind":{"type":"string","enum":["annotation","checkpoint"]}}, []),
        "history": (page, []),
        "asset_evidence": (page, []),
        "resume_context": ({"limit":page["limit"]}, []),
        "latest_checkpoint": ({}, []),
    }
    descriptions = {
        "start":"Start a persistent session scoped to an explicit device and goal.",
        "events":"Page events in ascending sequence; filter by operation/status. Use event for details.",
        "resume_context":"Bounded evidence-linked context, recent events and annotations, latest checkpoint.",
        "annotate":"Attach explicit semantic evidence to an event. Never include secrets.",
        "checkpoint":"Attach a progress checkpoint with state, completed_steps, unresolved_issues, next_step and verification.",
        "history":"Page frame, asset revision and reference evidence by event sequence.",
        "asset_evidence":"Page distinct retained asset revisions by first occurrence, with provenance.",
    }
    result = []
    for action,(props,required) in specs.items():
        if action not in ("start","list"):
            props = {"session_id":string,**props}
            required = ["session_id",*required]
        result.append({"name":"vision_record_"+action,
                       "description":descriptions.get(action,"Recorder "+action),
                       "inputSchema":{"type":"object","properties":props,"required":required,"additionalProperties":False}})
    return result
