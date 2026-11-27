"""C03 immutable, scoped asset revisions and the coherent legacy alias pointer.

Authoritative state is the additive ``asset_revisions.sqlite`` database:

* ``asset_revision``: immutable canonical content keyed by ``ar_<sha256>``.
* ``scoped_asset_alias``: last committed revision per (device, session, name).
* ``legacy_asset_alias``: last committed revision for a bare legacy name plus
  the exact legacy AssetRecord JSON; ``assets/<name>.{png,json}`` is only a
  compatibility projection repaired from this pointer.
* ``asset_pin``: OS-owner retained active uses (reconciled after owner death).

PNG bytes are content addressed (``asset_revisions/blobs/<sha256>.png``),
fsynced and published before any pointer refers to them; blobs are never
rewritten or collected. Pointers commit under the shared metadata transaction.
Encoding, decoding and blob hashing happen outside metadata. New scoped paths
never consult the legacy alias and never fall back across scopes.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import tempfile
import time
import uuid
from contextlib import ExitStack, closing, contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import cv2
import numpy as np

from service.core.opencv.dto import Region
from service.core.opencv.mat_utility import MatUtility
from vision_app.metadata import FileLock, metadata_transaction
from vision_app.observation import OperationError
from vision_app.store import (
    DeviceMismatchError,
    FrameNotFoundError,
    InvalidFrameIdError,
    StoreError,
    FrameStore,
)

_DEVICE = r"^(?!(?:adb|desktop)$)[A-Za-z0-9_.:-]{1,128}$(?![\s\S])"
_SESSION = r"^ses_[A-Za-z0-9_-]{1,64}$(?![\s\S])"
_NAME = r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$(?![\s\S])"
_FRAME = r"^frm_[A-Za-z0-9_-]{1,64}$(?![\s\S])"
_REVISION_RE = re.compile(r"ar_[0-9a-f]{64}\Z")

ASSET_REVISION_REGISTER_SCHEMA = {
    "type": "object",
    "properties": {
        "device": {"type": "string", "pattern": _DEVICE},
        "session_id": {"anyOf": [{"type": "string", "pattern": _SESSION}, {"type": "null"}], "default": None},
        "name": {"type": "string", "pattern": _NAME},
        "frame_id": {"type": "string", "pattern": _FRAME},
        "region": {"anyOf": [{"type": "array", "items": {"type": "integer", "minimum": 0},
                              "minItems": 4, "maxItems": 4}, {"type": "null"}], "default": None},
    },
    "required": ["device", "name", "frame_id"],
    "additionalProperties": False,
}
ASSET_REVISION_RESOLVE_SCHEMA = {
    "type": "object",
    "properties": {
        "device": {"type": "string", "pattern": _DEVICE},
        "session_id": {"anyOf": [{"type": "string", "pattern": _SESSION}, {"type": "null"}], "default": None},
        "name": {"type": "string", "pattern": _NAME},
    },
    "required": ["device", "name"],
    "additionalProperties": False,
}
SCHEMAS = {"asset_revision_register": ASSET_REVISION_REGISTER_SCHEMA,
           "asset_revision_resolve": ASSET_REVISION_RESOLVE_SCHEMA}

# Test-only fault seam: called with a stage name at each publication boundary.
_after_stage = None


def _stage(name):
    if _after_stage is not None:
        _after_stage(name)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def revision_id_for(content):
    """ar_ + SHA-256 of the canonical K04 digest fields (timestamp excluded)."""
    keys = ("device", "session_id", "name", "source_frame_id", "source_frame_sha256",
            "region", "png_sha256", "width", "height")
    return "ar_" + hashlib.sha256(canonical({k: content[k] for k in keys}).encode("utf-8")).hexdigest()


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _error(code, message, exit_code=3):
    return OperationError(code, message, exit_code=exit_code)


def _invalid(message):
    return _error("INVALID_ARGUMENT", message, 2)


def validate_request(op, request):
    """Validate exactly like the frozen Draft 2020-12 schema; apply defaults."""
    schema = SCHEMAS[op]
    if type(request) is not dict:
        raise _invalid(f"{op} requires a JSON object")
    unknown = set(request) - set(schema["properties"])
    if unknown:
        raise _invalid("Unknown fields: " + ", ".join(sorted(map(str, unknown))))
    missing = [k for k in schema["required"] if k not in request]
    if missing:
        raise _invalid("Missing required fields: " + ", ".join(missing))
    out = {}
    for key in schema["properties"]:
        value = request.get(key)
        if key in ("device", "name", "frame_id"):
            pattern = {"device": _DEVICE, "name": _NAME, "frame_id": _FRAME}[key]
            if not isinstance(value, str) or not re.search(pattern, value):
                raise _invalid(f"Invalid {key}")
        elif key == "session_id":
            if value is not None and (not isinstance(value, str) or not re.search(_SESSION, value)):
                raise _invalid("Invalid session_id")
        elif key == "region" and value is not None:
            if not isinstance(value, list) or len(value) != 4:
                raise _invalid("region must be four nonnegative integers")
            ints = []
            for item in value:
                # JSON Schema integer: no booleans, integral numbers only.
                if isinstance(item, bool) or not isinstance(item, (int, float)) or \
                        (isinstance(item, float) and not item.is_integer()) or item < 0:
                    raise _invalid("region must be four nonnegative integers")
                ints.append(int(item))
            value = ints
        out[key] = value
    return out


@dataclass(frozen=True)
class PinnedAssetRevision:
    """A coherent immutable revision and its verified PNG bytes."""

    revision: Dict[str, Any]
    png_bytes: bytes
    blob_path: Path

    @property
    def asset_revision_id(self):
        return self.revision["asset_revision_id"]


class AssetRevisionStore:
    """Shared store for CLI, MCP, legacy registry and Recorder seams."""

    def __init__(self, root_dir, frame_store=None):
        self.root_dir = Path(root_dir).resolve()
        self.frame_store = frame_store
        self.db_path = self.root_dir / "asset_revisions.sqlite"
        self.blobs_dir = self.root_dir / "asset_revisions" / "blobs"
        self.blobs_dir.mkdir(parents=True, exist_ok=True)
        with metadata_transaction(self.root_dir), self._db() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS asset_revision(
                id TEXT PRIMARY KEY, immutable_json TEXT NOT NULL,
                png_sha256 TEXT NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS scoped_asset_alias(
                device TEXT NOT NULL, session_key TEXT NOT NULL, name TEXT NOT NULL,
                revision_id TEXT NOT NULL REFERENCES asset_revision(id),
                generation INTEGER NOT NULL, updated_at REAL NOT NULL,
                PRIMARY KEY(device, session_key, name));
            CREATE TABLE IF NOT EXISTS legacy_asset_alias(
                name TEXT PRIMARY KEY, revision_id TEXT NOT NULL REFERENCES asset_revision(id),
                record_json TEXT NOT NULL, generation INTEGER NOT NULL,
                projection TEXT NOT NULL CHECK(projection IN ('pending','complete')),
                updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS asset_pin(
                token TEXT NOT NULL, revision_id TEXT NOT NULL, PRIMARY KEY(token, revision_id));
            """)

    @contextmanager
    def _db(self):
        with closing(sqlite3.connect(self.db_path, timeout=120)) as db:
            db.row_factory = sqlite3.Row
            db.execute("PRAGMA synchronous=FULL")
            db.execute("PRAGMA foreign_keys=ON")
            with db:
                yield db

    def blob_path(self, png_sha256):
        return self.blobs_dir / (png_sha256 + ".png")

    # ------------------------------------------------------------------ bytes
    def _publish_blob(self, png_bytes):
        digest = _sha(png_bytes)
        path = self.blob_path(digest)
        if not path.exists():
            tmp = _durable_temp(path.parent, png_bytes)
            try:
                try:
                    os.link(tmp, path)
                except FileExistsError:
                    pass  # An identical publisher won; verify the winner below.
            finally:
                tmp.unlink(missing_ok=True)
        self.read_blob(digest)
        return digest

    def read_blob(self, png_sha256):
        """Read immutable bytes and verify the retained digest (outside metadata)."""
        path = self.blob_path(png_sha256)
        try:
            data = path.read_bytes()
        except OSError:
            raise _error("STORE_ERROR", "Asset revision bytes are missing") from None
        if _sha(data) != png_sha256:
            raise _error("STORE_ERROR", "Asset revision bytes do not match digest")
        return data

    @contextmanager
    def prepare(self, frame_id, *, name, session_id=None, device=None, region=None, frame_store=None):
        """Capture coherent frame bytes under a pin, crop/encode outside metadata,
        publish the content-addressed blob and return the immutable content."""
        frames = frame_store or self.frame_store
        with frames.pin_frames([frame_id], device_id=device) as records:
            record = records[0]
            frame_bytes = frames.resolve_image_path(record.image_path).read_bytes()
            image = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
            if image is None:
                raise StoreError(f"Failed to decode image for frame {record.frame_id}")
            if region is not None:
                image = MatUtility.crop(image, Region(*region))
            png = MatUtility.encode_png(image)
            h, w = image.shape[:2]
            _stage("encoded")
            content = {
                "device": record.device_id, "session_id": session_id, "name": name,
                "source_frame_id": record.frame_id, "source_frame_sha256": _sha(frame_bytes),
                "region": list(region) if region is not None else None,
                "png_sha256": self._publish_blob(png), "width": int(w), "height": int(h),
            }
            _stage("blob_published")
            yield revision_id_for(content), content, png, record

    # --------------------------------------------------------------- metadata
    def _insert_revision(self, db, rid, content):
        encoded = canonical(content)
        row = db.execute("SELECT immutable_json FROM asset_revision WHERE id=?", (rid,)).fetchone()
        if row is not None:
            if row["immutable_json"] != encoded:
                raise _error("ID_RESERVED", "Asset revision ID already holds different content")
            return
        db.execute("INSERT INTO asset_revision VALUES (?,?,?,?)",
                   (rid, encoded, content["png_sha256"], time.time()))

    def _revision(self, db, rid):
        row = db.execute("SELECT immutable_json, png_sha256 FROM asset_revision WHERE id=?", (rid,)).fetchone()
        if row is None:
            raise _error("NOT_FOUND", "Asset revision not found")
        try:
            content = json.loads(row["immutable_json"])
            if revision_id_for(content) == rid and content["png_sha256"] == row["png_sha256"]:
                return {"asset_revision_id": rid, **content}
        except (KeyError, TypeError, ValueError):
            pass
        raise _error("STORE_ERROR", "Asset revision metadata does not match its identity")

    def _session(self, session_id, device, *, require_active):
        path = self.root_dir / "recorder.sqlite"
        if not path.is_file():
            raise _error("NOT_FOUND", "Session not found")
        uri = path.as_uri() + "?mode=ro"
        try:
            with closing(sqlite3.connect(uri, uri=True, timeout=120)) as db:
                row = db.execute("SELECT device_id,status FROM sessions WHERE session_id=?",
                                 (session_id,)).fetchone()
        except sqlite3.Error:
            raise _error("STORE_ERROR", "Session store unavailable") from None
        if row is None:
            raise _error("NOT_FOUND", "Session not found")
        if row[0] != device:
            raise _error("SCOPE_MISMATCH", "Session belongs to a different device")
        if require_active and row[1] != "active":
            raise _error("PRECONDITION_FAILED", "Session is not active")

    @staticmethod
    def public(revision):
        result = {k: revision[k] for k in ("asset_revision_id", "device", "session_id", "name",
                                            "source_frame_id", "region", "png_sha256", "width", "height")}
        result["details"] = {"source_frame_sha256": revision["source_frame_sha256"]}
        return result

    # ----------------------------------------------------------- scoped API
    def register(self, request):
        req = validate_request("asset_revision_register", request)
        device, sid, name = req["device"], req["session_id"], req["name"]
        if sid is not None:
            self._session(sid, device, require_active=True)
        try:
            with self.prepare(req["frame_id"], name=name, session_id=sid,
                              device=device, region=req["region"]) as (rid, content, _, _):
                self._commit_scoped(rid, content)
        except DeviceMismatchError:
            raise _error("SCOPE_MISMATCH", "Frame belongs to a different device") from None
        except (FrameNotFoundError, InvalidFrameIdError):
            raise _error("NOT_FOUND", "Frame not found") from None
        except ValueError:
            raise _invalid("region must be a nonempty area inside the frame") from None
        return self.public({"asset_revision_id": rid, **content})

    def _commit_scoped(self, rid, content):
        device, sid, name = content["device"], content["session_id"], content["name"]
        with metadata_transaction(self.root_dir):
            if sid is not None:  # Recheck immediately before publication.
                self._session(sid, device, require_active=True)
            with self._db() as db:
                self._insert_revision(db, rid, content)
                row = db.execute("SELECT generation FROM scoped_asset_alias WHERE device=? AND "
                                 "session_key=? AND name=?", (device, sid or "", name)).fetchone()
                db.execute("INSERT OR REPLACE INTO scoped_asset_alias VALUES (?,?,?,?,?,?)",
                           (device, sid or "", name, rid, (row[0] if row else 0) + 1, time.time()))
            _stage("scoped_committed")

    def resolve(self, request):
        req = validate_request("asset_revision_resolve", request)
        device, sid, name = req["device"], req["session_id"], req["name"]
        with metadata_transaction(self.root_dir):
            if sid is not None:
                self._session(sid, device, require_active=False)
            with self._db() as db:
                row = db.execute("SELECT revision_id FROM scoped_asset_alias WHERE device=? AND "
                                 "session_key=? AND name=?", (device, sid or "", name)).fetchone()
                if row is None:  # No cross-scope or legacy-alias fallback.
                    raise _error("NOT_FOUND", "No asset revision for this exact scope and name")
                revision = self._revision(db, row[0])
        self.read_blob(revision["png_sha256"])
        return self.public(revision)

    @staticmethod
    def check_use(revision, device, session_id=None):
        """Explicit use: same device; device-wide or exactly the same session."""
        if revision["device"] != device:
            raise _error("SCOPE_MISMATCH", "Asset revision belongs to a different device")
        if revision["session_id"] is not None and revision["session_id"] != session_id:
            raise _error("SCOPE_MISMATCH", "Asset revision belongs to a different session")

    @contextmanager
    def pin(self, revision_id, *, device, session_id=None):
        """Yield one exact revision with verified bytes, retained by an OS owner."""
        if not isinstance(revision_id, str) or not _REVISION_RE.match(revision_id):
            raise _invalid("Invalid asset_revision_id")
        token = uuid.uuid4().hex
        owner = FileLock(self.root_dir, "asset-owner", token)
        owner.acquire()
        try:
            with metadata_transaction(self.root_dir), self._db() as db:
                revision = self._revision(db, revision_id)
                self.check_use(revision, device, session_id)
                if session_id is not None:
                    self._session(session_id, device, require_active=False)
                db.execute("INSERT INTO asset_pin VALUES (?,?)", (token, revision_id))
            try:
                frames = self.frame_store or FrameStore(self.root_dir)
                with ExitStack() as stack:
                    try:
                        records = stack.enter_context(
                            frames.pin_frames([revision["source_frame_id"]], device_id=device))
                    except FrameNotFoundError:
                        raise _error("NOT_FOUND", "Asset revision source frame not found") from None
                    source = frames.resolve_image_path(records[0].image_path)
                    if _sha(source.read_bytes()) != revision["source_frame_sha256"]:
                        raise _error("EVIDENCE_CHANGED", "Asset revision source frame digest changed")
                    data = self.read_blob(revision["png_sha256"])
                    yield PinnedAssetRevision(revision, data, self.blob_path(revision["png_sha256"]))
            finally:
                with metadata_transaction(self.root_dir), self._db() as db:
                    db.execute("DELETE FROM asset_pin WHERE token=?", (token,))
        finally:
            owner.release()

    def active_pins(self):
        """Reconcile pins whose OS owner died; return actively pinned revisions."""
        with metadata_transaction(self.root_dir), self._db() as db:
            active = set()
            for token, rid in db.execute("SELECT token,revision_id FROM asset_pin").fetchall():
                probe = FileLock(self.root_dir, "asset-owner", token)
                if probe.acquire(blocking=False):
                    probe.release()
                    db.execute("DELETE FROM asset_pin WHERE token=?", (token,))
                else:
                    active.add(rid)
            return active

    # ------------------------------------------------- legacy alias pointer
    def legacy_row(self, db, name):
        return db.execute("SELECT * FROM legacy_asset_alias WHERE name=?", (os.path.normcase(name),)).fetchone()

    def legacy_commit(self, name, rid, content, record, png_bytes, png_path, json_path):
        """Publish the global last-committed alias, then its projection.

        Projection temp files are written and fsynced outside metadata; inside
        metadata the pointer commits first, renames follow, then the pointer is
        marked complete. Upgraded readers repair any pending projection.
        """
        record_json = canonical(record)
        key = os.path.normcase(name)
        with _projection_temps(png_path.parent, png_bytes, record) as (tmp_png, tmp_json):
            with metadata_transaction(self.root_dir):
                with self._db() as db:
                    self._insert_revision(db, rid, content)
                    row = self.legacy_row(db, name)
                    generation = (row["generation"] if row else 0) + 1
                    db.execute("INSERT OR REPLACE INTO legacy_asset_alias VALUES (?,?,?,?,?,?)",
                               (key, rid, record_json, generation, "pending", time.time()))
                _stage("legacy_pointer_committed")
                os.replace(tmp_png, png_path)
                _stage("legacy_projection_png")
                os.replace(tmp_json, json_path)
                _stage("legacy_projection_json")
                with self._db() as db:
                    self._complete_projection(db, key, generation)

    @staticmethod
    def _complete_projection(db, key, generation):
        db.execute("UPDATE legacy_asset_alias SET projection='complete' WHERE name=? "
                   "AND generation=?", (key, generation))

    def repair_projection(self, row, record, data, png_path, json_path):
        """Repair only if the observed pending generation is still current."""
        with _projection_temps(png_path.parent, data, record) as (tmp_png, tmp_json):
            with metadata_transaction(self.root_dir), self._db() as db:
                current = self.legacy_row(db, row["name"])
                if current["projection"] == "pending" and current["generation"] == row["generation"]:
                    os.replace(tmp_png, png_path)
                    os.replace(tmp_json, json_path)
                    self._complete_projection(db, row["name"], row["generation"])


@contextmanager
def _projection_temps(directory, png, record):
    tmp_png = _durable_temp(directory, png)
    try:
        tmp_json = _durable_temp(directory, _legacy_json_bytes(record))
        try:
            yield tmp_png, tmp_json
        finally:
            tmp_json.unlink(missing_ok=True)
    finally:
        tmp_png.unlink(missing_ok=True)


def _legacy_json_bytes(record):
    # Byte-identical to store._atomic_write_json used by the original registry.
    return json.dumps(record, indent=2, sort_keys=True).encode("utf-8")


def _durable_temp(directory, data):
    directory.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(dir=str(directory), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


class AssetRevisionService:
    """One validation/envelope path shared by CLI and MCP."""

    def __init__(self, store):
        self.store = store

    def invoke(self, op, request):
        try:
            revisions = AssetRevisionStore(self.store.store_dir, frame_store=self.store)
            handler = {"asset_revision_register": revisions.register,
                       "asset_revision_resolve": revisions.resolve}[op]
            return {"ok": True, "result": handler(request)}, 0
        except OperationError as exc:
            return self._error(exc.code, exc.message, exc.retryable), exc.exit_code
        except (StoreError, sqlite3.Error, OSError):
            return self._error("STORE_ERROR", "Asset revision store unavailable"), 3
        except Exception:
            return self._error("INTERNAL_ERROR", "Internal asset revision error"), 3

    @staticmethod
    def _error(code, message, retryable=False):
        return {"ok": False, "error": {"code": code, "message": message,
                "details": {}, "retryable": retryable}}
