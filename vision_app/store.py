"""Persistent, bounded, workspace/device-scoped frame store with atomic writes."""

from __future__ import annotations

import json
import os
import re
import tempfile
import time
import uuid
from contextvars import ContextVar
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from vision_app.coordinator import Owner
from vision_app.epochs import DeviceEpochs
from vision_app.transforms import CoordinateTransform
from vision_app.metadata import FileLock, metadata_transaction

protect_new_frames = ContextVar('protect_new_frames', default=False)

_FRAME_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class StoreError(Exception):
    """Base error for frame store operations."""


class InvalidFrameIdError(StoreError, ValueError):
    """Raised when a frame ID is malformed or attempts path traversal."""


class FrameNotFoundError(StoreError, KeyError):
    """Raised when a requested frame ID does not exist in the store."""


class DeviceMismatchError(StoreError, ValueError):
    """Raised when a frame belongs to a different device than requested."""


class OutOfBoundsError(StoreError, ValueError):
    """Raised when a local or mapped coordinate is outside valid half-open bounds."""


@dataclass(frozen=True)
class FrameRecord:
    """Persisted metadata for a captured or derived frame."""

    frame_id: str
    device_id: str
    timestamp: float
    width: int
    height: int
    source_width: int
    source_height: int
    image_path: str
    parent_id: Optional[str] = None
    transform: CoordinateTransform = CoordinateTransform()
    rotation: Optional[int] = None
    protected: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "frame_id": self.frame_id,
            "device_id": self.device_id,
            "timestamp": self.timestamp,
            "width": self.width,
            "height": self.height,
            "source_width": self.source_width,
            "source_height": self.source_height,
            "image_path": self.image_path,
            "parent_id": self.parent_id,
            "transform": self.transform.to_dict(),
            "rotation": self.rotation,
            "protected": self.protected,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> FrameRecord:
        return cls(
            frame_id=str(data["frame_id"]),
            device_id=str(data["device_id"]),
            timestamp=float(data["timestamp"]),
            width=int(data["width"]),
            height=int(data["height"]),
            source_width=int(data["source_width"]),
            source_height=int(data["source_height"]),
            image_path=str(data["image_path"]),
            parent_id=data.get("parent_id"),
            transform=CoordinateTransform.from_dict(data.get("transform", {})),
            rotation=data.get("rotation"),
            protected=bool(data.get("protected", False)),
        )


def validate_frame_id(frame_id: str) -> str:
    """Validate that frame_id is path-safe and contains no traversal characters."""
    if not isinstance(frame_id, str) or not _FRAME_ID_RE.match(frame_id):
        raise InvalidFrameIdError(f"Invalid or unsafe frame_id: {frame_id!r}")
    return frame_id


def _atomic_write_bytes(target_path: Path, data: bytes) -> None:
    """Atomically write bytes to target_path using a same-directory temp file."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target_path.parent), prefix=".tmp_", suffix=".part")
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, target_path)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink(missing_ok=True)
        raise


def _atomic_write_json(target_path: Path, payload: Dict[str, Any]) -> None:
    """Atomically write a JSON object to target_path."""
    encoded = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    _atomic_write_bytes(target_path, encoded)


class FrameStore:
    """Workspace-local persistent frame store with device scoping and bounded TTL cleanup."""

    def __init__(
        self,
        workspace_dir: Path | str,
        max_frames: int = 100,
        ttl_seconds: float = 3600.0,
    ) -> None:
        if max_frames < 1:
            raise ValueError("max_frames must be >= 1")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be > 0")
        self.store_dir = Path(workspace_dir).resolve()
        self.frames_dir = self.store_dir / "frames"
        self.index_path = self.store_dir / "index.json"
        self.lifetime_path = self.store_dir / "frame_lifetimes.json"
        self.max_frames = max_frames
        self.ttl_seconds = ttl_seconds
        self.frames_dir.mkdir(parents=True, exist_ok=True)

    def _lifetimes(self):
        if self.lifetime_path.exists():
            return json.loads(self.lifetime_path.read_text(encoding="utf-8"))
        return {"reservations": {}, "pins": {}}

    def _write_lifetimes(self, state):
        _atomic_write_json(self.lifetime_path, state)

    def _active_frames(self):
        """Reconcile dead OS owners without waiting; called inside metadata."""
        state = self._lifetimes()
        active = set()
        changed = False
        for token, frames in list(state["pins"].items()):
            probe = FileLock(self.store_dir, "frame-owner", token)
            if probe.acquire(blocking=False):
                probe.release()
                del state["pins"][token]
                changed = True
            else:
                active.update(frames)
        for fid, token in state["reservations"].items():
            if token is None:
                continue
            probe = FileLock(self.store_dir, "frame-owner", token)
            if probe.acquire(blocking=False):
                probe.release()
                state["reservations"][fid] = None
                changed = True
            else:
                active.add(fid)
        if changed:
            self._write_lifetimes(state)
        return active

    @contextmanager
    def pin_frames(self, frame_ids, *, device_id=None):
        """Yield coherent records retained until this context exits or its OS owner dies."""
        ids = [validate_frame_id(fid) for fid in frame_ids]
        token = uuid.uuid4().hex
        owner = FileLock(self.store_dir, "frame-owner", token)
        owner.acquire()
        try:
            with metadata_transaction(self):
                records = self._load_index()
                selected = []
                for fid in ids:
                    rec = self._get_frame(records, fid, device_id)
                    if not self.resolve_image_path(rec.image_path).is_file():
                        raise FrameNotFoundError(f"Image file missing for frame {fid}")
                    selected.append(rec)
                state = self._lifetimes()
                state["pins"][token] = ids
                self._write_lifetimes(state)
            yield selected
        finally:
            try:
                with metadata_transaction(self):
                    state = self._lifetimes()
                    state["pins"].pop(token, None)
                    self._write_lifetimes(state)
            finally:
                owner.release()

    def _load_index(self) -> Dict[str, FrameRecord]:
        if not self.index_path.exists():
            return {}
        raw = json.loads(self.index_path.read_text(encoding="utf-8"))
        frames_raw = raw.get("frames", {})
        return {fid: FrameRecord.from_dict(fdata) for fid, fdata in frames_raw.items()}

    def _save_index(self, records: Dict[str, FrameRecord]) -> None:
        payload = {"frames": {fid: rec.to_dict() for fid, rec in records.items()}}
        _atomic_write_json(self.index_path, payload)

    def resolve_image_path(self, image_path: str) -> Path:
        """Resolve a stored relative image path and reject any path traversal."""
        candidate = (self.store_dir / image_path).resolve()
        frames_root = self.frames_dir.resolve()
        if not candidate.is_relative_to(frames_root):
            raise InvalidFrameIdError(f"Image path escapes frames directory: {image_path!r}")
        return candidate

    def save_frame(
        self,
        image: np.ndarray,
        device_id: str,
        *,
        frame_id: Optional[str] = None,
        parent_id: Optional[str] = None,
        transform: Optional[CoordinateTransform] = None,
        source_width: Optional[int] = None,
        source_height: Optional[int] = None,
        rotation: Optional[int] = None,
        protected: bool = False,
        timestamp: Optional[float] = None,
        device_owner: Optional[Owner] = None,
    ) -> FrameRecord:
        """Persist a BGR uint8 image and its metadata atomically, then run bounded cleanup."""
        if not device_id or not isinstance(device_id, str):
            raise ValueError("device_id must be a non-empty string")
        if image is None or not isinstance(image, np.ndarray) or image.ndim != 3 or image.dtype != np.uint8:
            raise ValueError("image must be a uint8 HxWx3 numpy array")

        fid = validate_frame_id(frame_id) if frame_id is not None else f"frm_{uuid.uuid4().hex[:12]}"
        height, width = int(image.shape[0]), int(image.shape[1])
        src_w = int(source_width) if source_width is not None else width
        src_h = int(source_height) if source_height is not None else height
        ts = float(timestamp) if timestamp is not None else time.time()
        rel_path = f"frames/{fid}.png"
        abs_path = self.resolve_image_path(rel_path)

        ok, encoded = cv2.imencode(".png", image)
        if not ok:
            raise StoreError("Failed to encode frame as PNG")

        record = FrameRecord(
            frame_id=fid,
            device_id=device_id,
            timestamp=ts,
            width=width,
            height=height,
            source_width=src_w,
            source_height=src_h,
            image_path=rel_path,
            parent_id=parent_id,
            transform=transform or CoordinateTransform(),
            rotation=rotation,
            protected=protected or protect_new_frames.get(),
        )

        token = uuid.uuid4().hex
        owner = FileLock(self.store_dir, "frame-owner", token)
        owner.acquire()
        try:
            with metadata_transaction(self):
                state = self._lifetimes()
                # On Windows distinct JSON keys can address the same PNG.
                # Compare native path keys before releasing metadata, even
                # when the first publisher has not written its bytes yet.
                path_key = os.path.normcase(fid)
                claimed = self._load_index().keys() | state["reservations"].keys()
                if any(os.path.normcase(other) == path_key for other in claimed) or abs_path.exists():
                    raise StoreError(f"Frame ID already reserved: {fid}")
                state["reservations"][fid] = token
                self._write_lifetimes(state)
            # Encoding and durable byte publication never hold metadata.
            _atomic_write_bytes(abs_path, encoded.tobytes())
            with metadata_transaction(self):
                records = self._load_index()
                # Publish the stamp before the JSON pointer. A crash here can
                # leave an unusable ID, never a visible capture missing its stamp.
                DeviceEpochs(self).publish_frame_stamp(
                    fid, device_id, owner=device_owner, parent_id=parent_id,
                )
                records[fid] = record
                self._save_index(records)
                state = self._lifetimes()
                state["reservations"][fid] = None
                self._write_lifetimes(state)
                self._cleanup_records(records, now=ts)
        finally:
            owner.release()
        return record

    def get_frame(self, frame_id: str, *, device_id: Optional[str] = None) -> FrameRecord:
        """Fetch a frame record by ID, optionally enforcing device_id match."""
        fid = validate_frame_id(frame_id)
        with metadata_transaction(self):
            return self._get_frame(self._load_index(), fid, device_id)

    def _get_frame(self, records, fid, device_id):
        if fid not in records:
            raise FrameNotFoundError(f"Frame not found: {fid}")
        rec = records[fid]
        if device_id is not None and rec.device_id != device_id:
            raise DeviceMismatchError(
                f"Frame {fid} belongs to device {rec.device_id!r}, not {device_id!r}"
            )
        return rec

    def load_image(self, frame_id: str, *, device_id: Optional[str] = None) -> np.ndarray:
        """Load the BGR image for a stored frame."""
        with self.pin_frames([frame_id], device_id=device_id) as records:
            rec = records[0]
            img = cv2.imread(str(self.resolve_image_path(rec.image_path)), cv2.IMREAD_COLOR)
            if img is None:
                raise StoreError(f"Failed to decode image for frame {rec.frame_id}")
            return img

    def set_protected(self, frame_id: str, protected: bool = True) -> FrameRecord:
        """Mark or unmark a frame as protected (e.g. registered asset) from TTL cleanup."""
        with metadata_transaction(self):
            return self._set_protected(frame_id, protected)

    def _set_protected(self, frame_id, protected):
        fid = validate_frame_id(frame_id)
        records = self._load_index()
        if fid not in records:
            raise FrameNotFoundError(f"Frame not found: {fid}")
        old = records[fid]
        if not self.resolve_image_path(old.image_path).is_file():
            raise FrameNotFoundError(f"Image file missing for frame {fid}")
        updated = FrameRecord(
            frame_id=old.frame_id,
            device_id=old.device_id,
            timestamp=old.timestamp,
            width=old.width,
            height=old.height,
            source_width=old.source_width,
            source_height=old.source_height,
            image_path=old.image_path,
            parent_id=old.parent_id,
            transform=old.transform,
            rotation=old.rotation,
            protected=protected,
        )
        records[fid] = updated
        self._save_index(records)
        return updated

    def map_point(
        self,
        frame_id: str,
        x: int,
        y: int,
        *,
        device_id: Optional[str] = None,
    ) -> Tuple[int, int]:
        """Validate local (x, y) in half-open [0, width) x [0, height) and map to source."""
        rec = self.get_frame(frame_id, device_id=device_id)
        if not (0 <= x < rec.width and 0 <= y < rec.height):
            raise OutOfBoundsError(
                f"Local point ({x}, {y}) outside frame {rec.frame_id} bounds [0,{rec.width})x[0,{rec.height})"
            )
        sx, sy = rec.transform.map_point(x, y)
        if not (0 <= sx < rec.source_width and 0 <= sy < rec.source_height):
            raise OutOfBoundsError(
                f"Mapped point ({sx}, {sy}) outside source bounds [0,{rec.source_width})x[0,{rec.source_height})"
            )
        return (sx, sy)

    def list_frames(self, *, device_id: Optional[str] = None) -> List[FrameRecord]:
        """List stored frames, optionally filtered by device_id."""
        with metadata_transaction(self):
            records = self._load_index()
        items = list(records.values())
        if device_id is not None:
            items = [r for r in items if r.device_id == device_id]
        return sorted(items, key=lambda r: r.timestamp)

    def cleanup(self, *, now: Optional[float] = None) -> List[str]:
        """Remove expired or excess unprotected frames and return removed frame IDs."""
        with metadata_transaction(self):
            records = self._load_index()
            return self._cleanup_records(records, now=now if now is not None else time.time())

    def _cleanup_records(self, records: Dict[str, FrameRecord], *, now: float) -> List[str]:
        removed: List[str] = []
        active = self._active_frames()
        deleted = []
        cutoff = now - self.ttl_seconds

        # 1. Remove expired unprotected frames
        for fid, rec in list(records.items()):
            if not rec.protected and fid not in active and rec.timestamp < cutoff:
                deleted.append(rec)
                del records[fid]
                removed.append(fid)

        # 2. Bound the transient cache; protected evidence is outside its budget.
        unprotected = sorted(
            (rec for rec in records.values() if not rec.protected and rec.frame_id not in active),
            key=lambda r: r.timestamp,
        )
        excess = len(unprotected) - self.max_frames
        for rec in unprotected:
            if excess <= 0:
                break
            deleted.append(rec)
            del records[rec.frame_id]
            removed.append(rec.frame_id)
            excess -= 1

        # Commit pointer removal before deleting any bytes, including orphan recovery.
        if removed:
            self._save_index(records)
        for rec in deleted:
            self._delete_record_file(rec)
        indexed_paths = {self.resolve_image_path(rec.image_path) for rec in records.values()}
        for path in self.frames_dir.glob("*.png"):
            if path not in indexed_paths and path.stem not in active:
                path.unlink(missing_ok=True)
        return removed

    def _delete_record_file(self, rec: FrameRecord) -> None:
        try:
            img_path = self.resolve_image_path(rec.image_path)
            if img_path.exists():
                img_path.unlink(missing_ok=True)
        except InvalidFrameIdError:
            pass
