"""Phase 9 owner and claim primitives, inside the compatibility outer gate."""

from contextlib import closing, contextmanager, nullcontext
from dataclasses import dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import threading
import time
import uuid

from vision_app.metadata import FileLock, canonical_store, metadata_held, metadata_transaction

_local = threading.local()
_order = {"parent": 0, "request": 1, "device": 2}


class ClaimError(Exception):
    def __init__(self, code, request_id):
        super().__init__(f"{code}: {request_id}")
        self.code = code


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _digest(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def child_task_id(batch_id, device):
    return "ptask_" + _digest({"kind": "batch-child-task", "batch_id": batch_id, "device": device})[:32]


def task_run_id(task_id, device):
    return "prun_" + _digest({"kind": "task-run", "task_id": task_id, "device": device})[:32]


@dataclass(frozen=True)
class Owner:
    store: Path
    role: str
    key: str
    token: str

    @property
    def active(self):
        return any(owner is self for owner in getattr(_local, "owners", ()))


@dataclass(frozen=True)
class Claim:
    id: str
    kind: str
    request: dict
    receipt: dict
    device: str | None = None
    parent_id: str | None = None
    owner_id: str | None = None


class OwnerCoordinator:
    def __init__(self, store):
        self.root = canonical_store(store)

    @contextmanager
    def _lock(self, role, key, timeout):
        if not math.isfinite(timeout) or not 0 <= timeout <= 120:
            raise ValueError("Invalid owner timeout")
        owners = getattr(_local, "owners", ())
        if metadata_held() or (owners and _order[owners[-1].role] >= _order[role]):
            raise RuntimeError("Owner lock order violation")
        # Parent and standalone request roles share one per-ID exclusion domain.
        namespace = "device-owner" if role == "device" else "request-owner"
        lock = FileLock(self.root, namespace, key)
        if not lock.acquire(timeout=timeout):
            yield None
            return
        owner = Owner(self.root, role, key, uuid.uuid4().hex)
        _local.owners = (*owners, owner)
        try:
            yield owner
        finally:
            _local.owners = owners
            lock.release()

    def request_owner(self, request_id, *, parent=False, legacy=False, timeout=0):
        if timeout > (120 if legacy else 2):
            raise ValueError("Request owner timeout exceeds admission limit")
        return self._lock("parent" if parent else "request", request_id, timeout)

    @contextmanager
    def device_owner(self, serial, *, legacy=False, timeout=None, owner=None):
        if owner is not None:
            self._require_owner(owner, serial, "device")
            yield owner
            return
        limit = 120 if legacy else 2
        if timeout is not None and timeout > limit:
            raise ValueError("Device owner timeout exceeds admission limit")
        with self._lock("device", serial, limit if timeout is None else timeout) as acquired:
            yield acquired

    def _require_owner(self, owner, key, role):
        if owner is None or not owner.active or (owner.store, owner.key, owner.role) != (self.root, key, role):
            raise RuntimeError("Matching active owner required")

    @staticmethod
    def _owns_request(root, key):
        return any(owner.store == root and owner.key == key and owner.role != "device"
                   for owner in getattr(_local, "owners", ()))


_CLAIMS = """
CREATE TABLE IF NOT EXISTS request_claim (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    request_json TEXT NOT NULL,
    parent_id TEXT REFERENCES request_claim(id),
    device TEXT,
    owner_id TEXT NOT NULL,
    owner_token TEXT,
    state TEXT NOT NULL CHECK(state IN ('reserved', 'running', 'terminal')),
    receipt_json TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""
_BATCHES = """
CREATE TABLE IF NOT EXISTS batch_admission (
    batch_id TEXT PRIMARY KEY REFERENCES request_claim(id),
    phase TEXT NOT NULL CHECK(phase IN ('open', 'closed', 'reconciling', 'terminal')),
    pins_json TEXT NOT NULL
)
"""


class RequestLedger(OwnerCoordinator):
    """Durable primitives for callers that already apply frozen request defaults.

    Admission's recheck callback runs inside the shared metadata transaction.
    External discovery and proof validation belong outside that transaction.
    Receipts and reconciliation policy are supplied by the effect service.
    """

    @contextmanager
    def transaction(self):
        """Share the coordinator SQLite transaction with atomic metadata mutations."""
        with metadata_transaction(self.root):
            with closing(sqlite3.connect(self.root / "coordinator.sqlite")) as db, db:
                db.row_factory = sqlite3.Row
                db.execute("PRAGMA foreign_keys = ON")
                db.execute("BEGIN IMMEDIATE")
                db.execute(_CLAIMS)
                db.execute(_BATCHES)
                yield db

    @staticmethod
    def _row(db, request_id):
        return db.execute("SELECT * FROM request_claim WHERE id = ?", (request_id,)).fetchone()

    @staticmethod
    def _normalized(request):
        return {key: value for key, value in request.items() if key != "return_image"}

    @staticmethod
    def _receipt(row, *, duplicate=False):
        receipt = json.loads(row["receipt_json"])
        if duplicate:
            receipt["duplicate_request"] = True
        return receipt

    def _duplicate(self, db, request_id, kind, request):
        row = self._row(db, request_id)
        if row is None:
            return None
        if row["kind"] != kind or row["request_hash"] != _digest(self._normalized(request)):
            raise ClaimError("REQUEST_ID_CONFLICT", request_id)
        if row["state"] == "reserved" and row["parent_id"] is not None:
            raise ClaimError("ID_RESERVED", request_id)
        return self._receipt(row, duplicate=True)

    def duplicate(self, request_id, kind, request):
        """First admission step, before mutable device/registry validation."""
        with self.transaction() as db:
            return self._duplicate(db, request_id, kind, request)

    def _insert(self, db, claim, state, owner):
        if self._row(db, claim.id) is not None:
            raise ClaimError("REQUEST_ID_CONFLICT", claim.id)
        request = self._normalized(claim.request)
        now = time.time()
        db.execute(
            "INSERT INTO request_claim VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (claim.id, claim.kind, _digest(request), canonical_json(request), claim.parent_id,
             claim.device, claim.owner_id or claim.id, owner.token if owner else None, state,
             canonical_json(claim.receipt), now, now),
        )

    def admit(self, owner, claim, *, reservations=(), batch_pins=None, recheck=None):
        """Return a duplicate receipt or atomically insert the claim and reservations.

        Reservations carry their real initial receipt, device and optional shared
        owner ID (a child run uses its child task ID).
        """
        self._require_owner(owner, claim.id, "parent" if batch_pins is not None else "request")
        if claim.parent_id is not None or claim.owner_id not in (None, claim.id):
            raise ValueError("Invalid root claim")
        with self.transaction() as db:
            duplicate = self._duplicate(db, claim.id, claim.kind, claim.request)
            if duplicate is not None:
                return duplicate
            if recheck is not None:
                recheck(db)
            self._insert(db, claim, "running", owner)
            if batch_pins is not None:
                db.execute("INSERT INTO batch_admission VALUES (?, 'open', ?)",
                           (claim.id, canonical_json(batch_pins)))
            for reservation in reservations:
                self._insert(db, replace(reservation, parent_id=claim.id), "reserved", None)
        return None

    def start_reserved(self, owner, batch_id):
        """Claim a reserved child and every nested claim sharing its owner."""
        self._require_owner(owner, getattr(owner, "key", None), "request")
        with self.transaction() as db:
            phase = db.execute("SELECT phase FROM batch_admission WHERE batch_id = ?", (batch_id,)).fetchone()
            row = self._row(db, owner.key)
            if (phase is None or phase["phase"] != "open" or row is None or
                    row["parent_id"] != batch_id or row["owner_id"] != owner.key or row["state"] != "reserved"):
                return False
            db.execute(
                "UPDATE request_claim SET state = 'running', owner_token = ?, updated_at = ? "
                "WHERE parent_id = ? AND owner_id = ? AND state = 'reserved'",
                (owner.token, time.time(), batch_id, owner.key),
            )
            return True

    def start_nested(self, owner, request_id):
        """Start a standalone task's reserved run under the existing task owner."""
        self._require_owner(owner, getattr(owner, "key", None), "request")
        with self.transaction() as db:
            task = self._row(db, owner.key)
            if task is None or task["state"] != "running" or task["owner_token"] != owner.token:
                return False
            result = db.execute(
                "UPDATE request_claim SET state = 'running', owner_token = ?, updated_at = ? "
                "WHERE id = ? AND parent_id = ? AND owner_id = ? AND state = 'reserved'",
                (owner.token, time.time(), request_id, owner.key, owner.key),
            )
            return result.rowcount == 1

    def close_nested(self, owner, receipt):
        """Finalize unused reservations for a completed or abandoned standalone task."""
        self._require_owner(owner, owner.key, "request")
        with self.transaction() as db:
            db.execute(
                "UPDATE request_claim SET state = 'terminal', receipt_json = ?, updated_at = ? "
                "WHERE parent_id = ? AND owner_id = ? AND state = 'reserved'",
                (canonical_json(receipt), time.time(), owner.key, owner.key),
            )

    def abandon_unpublished_child(self, owner, request_id):
        """Close an owned run whose journal was never created, before any intent."""
        self._require_owner(owner, owner.key, "request")
        with self.transaction() as db:
            row = self._row(db, request_id)
            if (row is not None and row["parent_id"] == owner.key and row["owner_id"] == owner.key
                    and row["state"] == "running"):
                receipt = self._receipt(row)
                if receipt.get("action_outcome") != "not_attempted":
                    raise RuntimeError("Unpublished child has a possible effect")
                self._write(db, request_id, "terminal", receipt)

    def close_admission(self, owner, not_attempted):
        """Close the batch and finalize unclaimed children in one transaction."""
        self._require_owner(owner, getattr(owner, "key", None), "parent")
        with self.transaction() as db:
            changed = db.execute(
                "UPDATE batch_admission SET phase = 'closed' WHERE batch_id = ? AND phase = 'open'",
                (owner.key,),
            )
            if changed.rowcount:
                rows = db.execute("SELECT * FROM request_claim WHERE parent_id = ? AND state = 'reserved'",
                                  (owner.key,)).fetchall()
                for row in rows:
                    self._write(db, row["id"], "terminal", not_attempted(self._receipt(row)))

    @staticmethod
    def _write(db, request_id, state, receipt):
        db.execute("UPDATE request_claim SET state = ?, receipt_json = ?, updated_at = ? WHERE id = ?",
                   (state, canonical_json(receipt), time.time(), request_id))

    @staticmethod
    def _finish_batch(db, batch_id):
        if db.execute("SELECT 1 FROM request_claim WHERE parent_id = ? AND state != 'terminal'",
                      (batch_id,)).fetchone() is not None:
            raise RuntimeError("Batch children still in progress")
        db.execute("UPDATE batch_admission SET phase = 'terminal' WHERE batch_id = ?", (batch_id,))

    def record(self, owner, request_id, receipt, *, terminal=False):
        """Update a running claim owned by this execution, with immutable terminal state."""
        self._require_owner(owner, owner.key, owner.role)
        with self.transaction() as db:
            row = self._row(db, request_id)
            if (row is None or row["owner_id"] != owner.key or row["state"] != "running" or
                    row["owner_token"] != owner.token):
                raise RuntimeError("Running claim required")
            if terminal and owner.role == "parent":
                self._finish_batch(db, request_id)
            self._write(db, request_id, "terminal" if terminal else "running", receipt)

    def inspect(self, request_id, reconcile=None, *, owner=None):
        """Read current facts, optionally reconciling a running claim under its OS owner.

        The callback receives the active owner and current receipt outside metadata.
        It returns a terminal receipt or None to leave the claim unchanged.
        """
        with self.transaction() as db:
            row = self._row(db, request_id)
            if row is None:
                raise ClaimError("NOT_FOUND", request_id)
            receipt = self._receipt(row)
            parent = db.execute("SELECT 1 FROM batch_admission WHERE batch_id = ?", (request_id,)).fetchone() is not None
        role = "parent" if parent else "request"
        if owner is not None:
            self._require_owner(owner, row["owner_id"], role)
        if (reconcile is None or row["state"] != "running" or
                (owner is None and self._owns_request(self.root, row["owner_id"]))):
            return receipt
        lock = nullcontext(owner) if owner is not None else self.request_owner(row["owner_id"], parent=parent)
        with lock as owner:
            with self.transaction() as db:
                current = self._row(db, request_id)
                receipt = self._receipt(current)
            if owner is None or current["state"] != "running":
                return receipt
            terminal = reconcile(owner, receipt)
            if terminal is None:
                return receipt
            with self.transaction() as db:
                self._write(db, request_id, "terminal", terminal)
                if parent:
                    self._finish_batch(db, request_id)
            return terminal
