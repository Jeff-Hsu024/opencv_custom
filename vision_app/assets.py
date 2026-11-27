"""Application-layer named asset registry, scoped references, and template matching."""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from service.core.opencv.dto import MatchResult, Region
from service.core.opencv.mat_utility import MatUtility
from service.core.opencv.open_cv_service import OpenCvService
from vision_app.asset_revisions import AssetRevisionStore, canonical, revision_id_for
from vision_app.epochs import DeviceEpochs
from vision_app.metadata import canonical_store, metadata_transaction
from vision_app.store import (
    DeviceMismatchError,
    FrameRecord,
    FrameStore,
    StoreError,
    _atomic_write_bytes,
    _atomic_write_json,
)

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
_recorded_assets = ContextVar("recorded_assets", default=None)


@contextmanager
def recorded_asset_snapshots(store):
    """Share exact alias reads and publications within a single Recorder event."""
    root = canonical_store(store)
    current = _recorded_assets.get()
    if current is not None and current[0] == root:
        yield
        return
    snapshots = {}
    token = _recorded_assets.set((root, snapshots))
    try:
        yield
    finally:
        _recorded_assets.reset(token)


class InvalidAssetNameError(StoreError, ValueError):
    """Raised when an asset name is malformed or unsafe."""


class AssetNotFoundError(StoreError, KeyError):
    """Raised when a requested named asset does not exist."""


class InvalidRefIdError(StoreError, ValueError):
    """Raised when a reference ID is malformed or unsafe."""


class RefNotFoundError(StoreError, KeyError):
    """Raised when a requested scoped reference does not exist."""


class StaleRefError(StoreError, ValueError):
    """Raised when a scoped reference no longer matches current frame/device state."""


def validate_asset_name(name: str) -> str:
    """Validate that an asset name is path-safe and contains no traversal characters."""
    if not isinstance(name, str) or not _SAFE_NAME_RE.match(name):
        raise InvalidAssetNameError(f"Invalid or unsafe asset name: {name!r}")
    return name


def validate_ref_id(ref_id: str) -> str:
    """Validate that a reference ID is path-safe and contains no traversal characters."""
    if not isinstance(ref_id, str) or not _SAFE_NAME_RE.match(ref_id):
        raise InvalidRefIdError(f"Invalid or unsafe ref_id: {ref_id!r}")
    return ref_id


@dataclass(frozen=True)
class AssetRecord:
    """Persisted metadata for a named template asset."""

    name: str
    image_path: str
    width: int
    height: int
    created_at: float
    source_frame_id: Optional[str] = None
    device_id: Optional[str] = None
    region: Optional[Tuple[int, int, int, int]] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "image_path": self.image_path,
            "width": self.width,
            "height": self.height,
            "created_at": self.created_at,
            "source_frame_id": self.source_frame_id,
            "device_id": self.device_id,
            "region": list(self.region) if self.region is not None else None,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AssetRecord:
        raw_region = data.get("region")
        region = tuple(int(v) for v in raw_region) if raw_region is not None else None
        return cls(
            name=str(data["name"]),
            image_path=str(data["image_path"]),
            width=int(data["width"]),
            height=int(data["height"]),
            created_at=float(data["created_at"]),
            source_frame_id=data.get("source_frame_id"),
            device_id=data.get("device_id"),
            region=region,  # type: ignore[arg-type]
        )


@dataclass(frozen=True)
class ScopedRef:
    """A frame- and device-scoped match reference with mapped device coordinates."""

    ref_id: str
    frame_id: str
    device_id: str
    target: str
    score: float
    bbox: Tuple[int, int, int, int]
    center: Tuple[float, float]
    device_bbox: Tuple[int, int, int, int]
    device_center: Tuple[float, float]
    source_width: int
    source_height: int
    rotation: Optional[int] = None
    created_at: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "frame_id": self.frame_id,
            "device_id": self.device_id,
            "target": self.target,
            "score": self.score,
            "bbox": list(self.bbox),
            "center": list(self.center),
            "device_bbox": list(self.device_bbox),
            "device_center": list(self.device_center),
            "source_width": self.source_width,
            "source_height": self.source_height,
            "rotation": self.rotation,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ScopedRef:
        return cls(
            ref_id=str(data["ref_id"]),
            frame_id=str(data["frame_id"]),
            device_id=str(data["device_id"]),
            target=str(data["target"]),
            score=float(data["score"]),
            bbox=tuple(int(v) for v in data["bbox"]),  # type: ignore[arg-type]
            center=tuple(float(v) for v in data["center"]),  # type: ignore[arg-type]
            device_bbox=tuple(int(v) for v in data["device_bbox"]),  # type: ignore[arg-type]
            device_center=tuple(float(v) for v in data["device_center"]),  # type: ignore[arg-type]
            source_width=int(data["source_width"]),
            source_height=int(data["source_height"]),
            rotation=data.get("rotation"),
            created_at=float(data.get("created_at", 0.0)),
        )


class AssetRegistry:
    """Persistent, workspace-local registry of named template assets."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.assets_dir = self.root_dir / "assets"
        self.assets_dir.mkdir(parents=True, exist_ok=True)
        self._revisions: Optional[AssetRevisionStore] = None

    def _meta_path(self, name: str) -> Path:
        validate_asset_name(name)
        return self.assets_dir / f"{name}.json"

    def _image_path(self, name: str) -> Path:
        validate_asset_name(name)
        return self.assets_dir / f"{name}.png"

    @property
    def revisions(self) -> AssetRevisionStore:
        # Lazily shared C03 pointer store; created on first use only.
        if self._revisions is None:
            self._revisions = AssetRevisionStore(self.root_dir)
        return self._revisions

    def register_from_frame(
        self,
        name: str,
        frame_store: FrameStore,
        frame_id: str,
        *,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> AssetRecord:
        """Register a named asset from a stored frame (or a cropped region of it).

        Legacy shape and global last-committed semantics are retained. Bytes are
        published as an immutable revision before the global alias pointer
        commits; ``assets/<name>.{png,json}`` is a projection of that pointer.
        """
        validate_asset_name(name)
        with self.revisions.prepare(
            frame_id, name=name, region=region, frame_store=frame_store,
        ) as (rid, content, png_bytes, frame):
            img_path = self._image_path(name)
            record = AssetRecord(
                name=name,
                image_path=str(img_path),
                width=content["width"],
                height=content["height"],
                created_at=time.time(),
                source_frame_id=frame.frame_id,
                device_id=frame.device_id,
                region=region,
            )
            self.revisions.legacy_commit(name, rid, content, record.to_dict(), png_bytes,
                                         img_path, self._meta_path(name))
            snapshots = self._recorded_snapshots()
            if snapshots is not None:
                snapshots[os.path.normcase(name)] = (record, png_bytes, rid)
            return record

    def _recorded_snapshots(self):
        scope = _recorded_assets.get()
        return scope[1] if scope is not None and scope[0] == canonical_store(self.root_dir) else None

    def _project_if_pending(self, row, record, data):
        if row["projection"] == "pending":
            self.revisions.repair_projection(row, record.to_dict(), data, self._image_path(record.name),
                                             self._meta_path(record.name))

    def get(self, name: str) -> AssetRecord:
        """Load metadata for a registered asset."""
        meta_path = self._meta_path(name)
        with metadata_transaction(self.root_dir), self.revisions._db() as db:
            row = self.revisions.legacy_row(db, name)
            if row is None:
                return self._historical_record(meta_path, name)
            record = AssetRecord.from_dict(json.loads(row["record_json"]))
            if row["projection"] == "complete":
                return record
            sha = self.revisions._revision(db, row["revision_id"])["png_sha256"]
        self._project_if_pending(row, record, self.revisions.read_blob(sha))
        return record

    @staticmethod
    def _historical_record(meta_path, name):
        if not meta_path.exists():
            raise AssetNotFoundError(f"Asset not found: {name}")
        return AssetRecord.from_dict(json.loads(meta_path.read_text(encoding="utf-8")))

    def snapshot(self, name: str) -> Tuple[AssetRecord, bytes, Optional[str]]:
        """Coherent (record, PNG bytes, revision ID or None) for one committed alias."""
        snapshots = self._recorded_snapshots()
        if snapshots is None:
            return self._snapshot(name)
        key = os.path.normcase(name)
        if key not in snapshots:
            try:
                snapshots[key] = self._snapshot(name)
            except AssetNotFoundError as exc:
                snapshots[key] = exc
        snapshot = snapshots[key]
        if isinstance(snapshot, AssetNotFoundError):
            raise snapshot
        return snapshot

    def _snapshot(self, name):
        meta_path = self._meta_path(name)
        with metadata_transaction(self.root_dir), self.revisions._db() as db:
            row = self.revisions.legacy_row(db, name)
            if row is None:
                record = self._historical_record(meta_path, name)
                try:
                    data = Path(record.image_path).read_bytes()
                except OSError:
                    raise AssetNotFoundError(f"Asset image missing for {name}: {record.image_path}") from None
                return record, data, None
            record = AssetRecord.from_dict(json.loads(row["record_json"]))
            sha = self.revisions._revision(db, row["revision_id"])["png_sha256"]
        data = self.revisions.read_blob(sha)
        self._project_if_pending(row, record, data)
        return record, data, row["revision_id"]

    def load_image(self, name: str) -> np.ndarray:
        """Load the BGR image for a registered asset."""
        record, data, _ = self.snapshot(name)
        return self.decode(data, f"{name}: {record.image_path}")

    @staticmethod
    def decode(data, label):
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise AssetNotFoundError(f"Failed to decode asset image for {label}")
        return img

    def list_assets(self) -> List[AssetRecord]:
        """List all registered assets sorted by name."""
        with metadata_transaction(self.root_dir), self.revisions._db() as db:
            rows = db.execute("SELECT * FROM legacy_asset_alias").fetchall()
            records = {row["name"]: AssetRecord.from_dict(json.loads(row["record_json"])) for row in rows}
            pending = [
                (row, records[row["name"]], self.revisions._revision(db, row["revision_id"])["png_sha256"])
                for row in rows if row["projection"] == "pending"
            ]
            for meta_path in self.assets_dir.glob("*.json"):
                key = os.path.normcase(meta_path.stem)
                if key not in records:
                    records[key] = self._historical_record(meta_path, meta_path.stem)
        for row, record, sha in pending:
            self._project_if_pending(row, record, self.revisions.read_blob(sha))
        return sorted(records.values(), key=lambda record: record.name)

    def adopt_legacy(self, name: str, frame_store: FrameStore) -> str:
        """Return the legacy alias revision, lazily adopting a historical asset.

        Adoption validates JSON, PNG, frame device and exact cropped pixels and
        otherwise fails. Historical projection files are never rewritten.
        """
        record, data, rid = self.snapshot(name)
        if rid is not None:
            return rid
        img_path = Path(record.image_path)
        if record.name != name or record.device_id is None or record.source_frame_id is None \
                or img_path.resolve() != self._image_path(name).resolve():
            raise StoreError(f"Legacy asset {name} metadata is not adoptable")
        image = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        with frame_store.pin_frames([record.source_frame_id], device_id=record.device_id) as recs:
            frame_bytes = frame_store.resolve_image_path(recs[0].image_path).read_bytes()
            frame_img = cv2.imdecode(np.frombuffer(frame_bytes, np.uint8), cv2.IMREAD_COLOR)
            expected = frame_img if record.region is None else MatUtility.crop(frame_img, Region(*record.region))
            if image is None or expected is None or image.shape[:2] != (record.height, record.width) \
                    or expected.shape != image.shape or not np.array_equal(expected, image):
                raise StoreError(f"Legacy asset {name} PNG does not match its source frame")
            content = {
                "device": record.device_id, "session_id": None, "name": name,
                "source_frame_id": record.source_frame_id,
                "source_frame_sha256": hashlib.sha256(frame_bytes).hexdigest(),
                "region": list(record.region) if record.region is not None else None,
                "png_sha256": self.revisions._publish_blob(data),
                "width": record.width, "height": record.height,
            }
            rid = revision_id_for(content)
            record_json = canonical(record.to_dict())
            with metadata_transaction(self.root_dir), self.revisions._db() as db:
                row = self.revisions.legacy_row(db, name)
                if row is not None:
                    if row["revision_id"] == rid:
                        return rid
                    raise StoreError(f"Legacy asset {name} changed during adoption")
                current = self._historical_record(self._meta_path(name), name)
                if current != record or img_path.read_bytes() != data:
                    raise StoreError(f"Legacy asset {name} changed during adoption")
                self.revisions._insert_revision(db, rid, content)
                db.execute("INSERT INTO legacy_asset_alias VALUES (?,?,?,?,?,?)",
                           (os.path.normcase(name), rid, record_json, 1, "complete", time.time()))
            return rid


class RefRegistry:
    """Persistent store for scoped match references."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.refs_dir = self.root_dir / "refs"
        self.refs_dir.mkdir(parents=True, exist_ok=True)

    def _ref_path(self, ref_id: str) -> Path:
        validate_ref_id(ref_id)
        return self.refs_dir / f"{ref_id}.json"

    def save(self, ref: ScopedRef, *, session_id: Optional[str] = None, revision_id=None) -> ScopedRef:
        """Persist a scoped reference atomically."""
        path = self._ref_path(ref.ref_id)
        with metadata_transaction(self.root_dir):
            DeviceEpochs(self.root_dir).publish_ref_stamp(
                ref, session_id=session_id, exists=path.exists(), revision_id=revision_id
            )
            _atomic_write_json(path, ref.to_dict())
        return ref

    def get(self, ref_id: str) -> ScopedRef:
        """Load a scoped reference by ID."""
        ref_path = self._ref_path(ref_id)
        if not ref_path.exists():
            raise RefNotFoundError(f"Reference not found: {ref_id}")
        data = json.loads(ref_path.read_text(encoding="utf-8"))
        return ScopedRef.from_dict(data)

    def validate(
        self,
        ref_id: str,
        *,
        device_id: Optional[str] = None,
        frame_store: Optional[FrameStore] = None,
    ) -> ScopedRef:
        """Load and validate a scoped reference against device and frame metadata."""
        ref = self.get(ref_id)
        if device_id is not None and ref.device_id != device_id:
            raise DeviceMismatchError(
                f"Reference {ref_id} belongs to device {ref.device_id!r}, expected {device_id!r}"
            )
        if frame_store is not None:
            frame = frame_store.get_frame(ref.frame_id)
            if frame.device_id != ref.device_id:
                raise DeviceMismatchError(
                    f"Reference {ref_id} device {ref.device_id!r} mismatches frame device {frame.device_id!r}"
                )
            if frame.source_width != ref.source_width or frame.source_height != ref.source_height:
                raise StaleRefError(
                    f"Reference {ref_id} source dimensions ({ref.source_width}x{ref.source_height}) "
                    f"do not match frame ({frame.source_width}x{frame.source_height})"
                )
            if frame.rotation != ref.rotation:
                raise StaleRefError(
                    f"Reference {ref_id} rotation {ref.rotation!r} does not match frame {frame.rotation!r}"
                )
        return ref


def _map_match_to_ref(
    frame: FrameRecord,
    target: str,
    match: MatchResult,
) -> ScopedRef:
    """Convert a frame-local MatchResult into a device-mapped ScopedRef."""
    x1, y1, x2, y2 = match.bbox
    dx1, dy1 = frame.transform.map_point(x1, y1)
    dx2, dy2 = frame.transform.map_point(x2, y2)
    cx, cy = match.center
    dcx, dcy = frame.transform.map_point(int(round(cx)), int(round(cy)))

    return ScopedRef(
        ref_id=f"ref_{uuid.uuid4().hex[:12]}",
        frame_id=frame.frame_id,
        device_id=frame.device_id,
        target=target,
        score=float(match.score),
        bbox=(int(x1), int(y1), int(x2), int(y2)),
        center=(float(cx), float(cy)),
        device_bbox=(int(dx1), int(dy1), int(dx2), int(dy2)),
        device_center=(float(dcx), float(dcy)),
        source_width=frame.source_width,
        source_height=frame.source_height,
        rotation=frame.rotation,
        created_at=time.time(),
    )


class MatchingService:
    """Application-layer service for matching named assets against stored frames."""

    def __init__(
        self,
        *,
        store: FrameStore,
        assets: Optional[AssetRegistry] = None,
        refs: Optional[RefRegistry] = None,
        opencv: Optional[OpenCvService] = None,
    ) -> None:
        self.store = store
        self.assets = assets or AssetRegistry(store.store_dir)
        self.refs = refs or RefRegistry(store.store_dir)
        self.opencv = opencv or OpenCvService()

    def find(
        self,
        frame_id: str,
        target: str,
        *,
        find_all: bool = False,
        threshold: float = 0.8,
        max_results: int = 10,
        iou_threshold: float = 0.5,
        color_mode: str = "gray",
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Match a named asset against a stored frame and return scoped refs."""
        with self.store.pin_frames([frame_id]) as (frame,):
            asset, data, revision_id = self.assets.snapshot(target)
            return self.match_frame(frame, target, self.assets.decode(data, f"{target}: {asset.image_path}"),
                                    find_all=find_all, threshold=threshold, max_results=max_results,
                                    iou_threshold=iou_threshold, color_mode=color_mode,
                                    session_id=session_id, revision_id=revision_id)

    def match_frame(self, frame, target, template_img, *, find_all=True, threshold=0.8,
                    max_results=10, iou_threshold=0.5, color_mode="gray",
                    session_id=None, revision_id=None):
        source_img = self.store.load_image(frame.frame_id)
        if find_all:
            raw_matches = self.opencv.find_all(
                source_img,
                template_img,
                threshold=threshold,
                max_results=max_results,
                iou_threshold=iou_threshold,
                color_mode=color_mode,
            )
        else:
            single = self.opencv.match_template(
                source_img,
                template_img,
                threshold=threshold,
                color_mode=color_mode,
            )
            raw_matches = [single] if single is not None else []

        scoped_refs: List[Dict[str, Any]] = []
        for match in raw_matches:
            ref = _map_match_to_ref(frame, target, match)
            self.refs.save(ref, session_id=session_id, revision_id=revision_id)
            scoped_refs.append(ref.to_dict())

        return {
            "frame_id": frame.frame_id,
            "device_id": frame.device_id,
            "target": target,
            "found": len(scoped_refs) > 0,
            "count": len(scoped_refs),
            "matches": scoped_refs,
        }
