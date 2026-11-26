"""Durable observation stamps and pre-input intents for one device owner."""

from dataclasses import dataclass
import os
from typing import Callable

from vision_app.coordinator import ClaimError, Owner, RequestLedger


@dataclass(frozen=True)
class RefEpoch:
    device: str
    epoch: int
    session_id: str | None


@dataclass(frozen=True)
class ActionIntent:
    request_owner: Owner
    request_id: str
    step_id: str
    pending_receipt: Callable[[dict, int], dict]


class DeviceEpochs(RequestLedger):
    def _current(self, db, device):
        db.execute("CREATE TABLE IF NOT EXISTS device_epoch (device TEXT PRIMARY KEY, epoch INTEGER NOT NULL)")
        row = db.execute("SELECT epoch FROM device_epoch WHERE device = ?", (device,)).fetchone()
        return row["epoch"] if row else 0

    def current(self, device):
        with self.transaction() as db:
            return self._current(db, device)

    @staticmethod
    def _frame_table(db):
        db.execute("CREATE TABLE IF NOT EXISTS frame_epoch "
                   "(frame_id TEXT PRIMARY KEY, device TEXT NOT NULL, epoch INTEGER NOT NULL)")

    def frame_epoch(self, frame_id, device):
        with self.transaction() as db:
            self._frame_table(db)
            row = db.execute("SELECT device, epoch FROM frame_epoch WHERE frame_id = ?",
                             (os.path.normcase(frame_id),)).fetchone()
            if row is not None and row["device"] != device:
                raise ClaimError("SCOPE_MISMATCH", frame_id)
            return row["epoch"] if row else None

    def publish_frame_stamp(self, frame_id, device, *, owner=None, parent_id=None):
        if owner is not None:
            self._require_owner(owner, device, "device")
        with self.transaction() as db:
            self._frame_table(db)
            key = os.path.normcase(frame_id)
            if db.execute("SELECT 1 FROM frame_epoch WHERE frame_id = ?", (key,)).fetchone():
                raise ClaimError("ID_RESERVED", frame_id)
            if parent_id is not None:
                parent = db.execute("SELECT device, epoch FROM frame_epoch WHERE frame_id = ?",
                                    (os.path.normcase(parent_id),)).fetchone()
                if parent is not None and parent["device"] != device:
                    raise ClaimError("SCOPE_MISMATCH", parent_id)
                epoch = parent["epoch"] if parent else None
            else:
                epoch = self._current(db, device) if owner is not None else None
            if epoch is not None:
                db.execute("INSERT INTO frame_epoch VALUES (?, ?, ?)", (key, device, epoch))

    @staticmethod
    def _ref_table(db):
        db.execute("CREATE TABLE IF NOT EXISTS ref_epoch "
                   "(ref_id TEXT PRIMARY KEY, device TEXT NOT NULL, epoch INTEGER NOT NULL, session_id TEXT)")

    def ref_epoch(self, ref_id):
        with self.transaction() as db:
            self._ref_table(db)
            row = db.execute("SELECT device, epoch, session_id FROM ref_epoch WHERE ref_id = ?",
                             (os.path.normcase(ref_id),)).fetchone()
            return RefEpoch(*row) if row else None

    def publish_ref_stamp(self, ref, *, session_id, exists):
        with self.transaction() as db:
            self._ref_table(db)
            key = os.path.normcase(ref.ref_id)
            if db.execute("SELECT 1 FROM ref_epoch WHERE ref_id = ?", (key,)).fetchone():
                raise ClaimError("ID_RESERVED", ref.ref_id)
            self._frame_table(db)
            frame = db.execute("SELECT device, epoch FROM frame_epoch WHERE frame_id = ?",
                               (os.path.normcase(ref.frame_id),)).fetchone()
            if frame is not None:
                if frame["device"] != ref.device_id:
                    raise ClaimError("SCOPE_MISMATCH", ref.ref_id)
                if exists:
                    raise ClaimError("ID_RESERVED", ref.ref_id)
                db.execute("INSERT INTO ref_epoch VALUES (?, ?, ?, ?)",
                           (key, ref.device_id, frame["epoch"], session_id))

    def guard_ref(self, owner, ref_id, device, *, session_id=None, legacy=False):
        """Check freshness/scope while the same owner excludes all cooperating input."""
        self._require_owner(owner, device, "device")
        stamp = self.ref_epoch(ref_id)
        if stamp is None:
            if legacy:
                return None
            raise ClaimError("REF_UNVERSIONED", ref_id)
        if (stamp.device, stamp.session_id) != (device, session_id):
            raise ClaimError("SCOPE_MISMATCH", ref_id)
        if stamp.epoch != self.current(device):
            raise ClaimError("STALE_REF_EPOCH", ref_id)
        return stamp.epoch

    def _advance(self, db, device):
        epoch = self._current(db, device) + 1
        db.execute("INSERT INTO device_epoch VALUES (?, ?) "
                   "ON CONFLICT(device) DO UPDATE SET epoch = excluded.epoch", (device, epoch))
        return epoch

    def advance_raw(self, owner, device):
        """Fence references before an ID-less effect, even if platform input fails."""
        self._require_owner(owner, device, "device")
        with self.transaction() as db:
            return self._advance(db, device)

    def begin_intent(self, owner, request_owner, request_id, step_id, pending_receipt):
        """Commit a single step's unknown outcome and epoch before its only dispatch.

        The receipt builder receives the running receipt and new epoch. It
        runs under metadata and must only prepare receipt data.
        """
        self._require_owner(owner, owner.key, "device")
        self._require_owner(request_owner, request_owner.key, "request")
        if not isinstance(step_id, str) or not step_id:
            raise ValueError("Step ID required")
        with self.transaction() as db:
            row = self._row(db, request_id)
            if (row is None or row["state"] != "running" or row["device"] != owner.key or
                    row["owner_id"] != request_owner.key or row["owner_token"] != request_owner.token):
                raise RuntimeError("Matching running device claim required")
            db.execute("CREATE TABLE IF NOT EXISTS action_intent "
                       "(request_id TEXT REFERENCES request_claim(id), step_id TEXT NOT NULL, "
                       "epoch INTEGER NOT NULL, PRIMARY KEY (request_id, step_id))")
            current_receipt = self._receipt(row)
            if (current_receipt.get("action_outcome") == "unknown" or
                    db.execute("SELECT 1 FROM action_intent WHERE request_id = ? AND step_id = ?",
                               (request_id, step_id)).fetchone()):
                raise ClaimError("ACTION_UNCERTAIN", request_id)
            epoch = self._advance(db, owner.key)
            receipt = dict(pending_receipt(current_receipt, epoch), status="in_progress",
                           action_outcome="unknown", observation_phase="post_action_unknown",
                           last_frame_id=None, finished_at=None)
            db.execute("INSERT INTO action_intent VALUES (?, ?, ?)", (request_id, step_id, epoch))
            self._write(db, request_id, "running", receipt)
        return epoch
