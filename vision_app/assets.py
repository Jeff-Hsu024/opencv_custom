"""Application-layer named asset registry, scoped references, and template matching."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

from service.core.opencv.dto import MatchResult, Region
from service.core.opencv.mat_utility import MatUtility
from service.core.opencv.open_cv_service import OpenCvService
from vision_app.store import (
    DeviceMismatchError,
    FrameRecord,
    FrameStore,
    StoreError,
    _atomic_write_bytes,
    _atomic_write_json,
)

_SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


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

    def _meta_path(self, name: str) -> Path:
        validate_asset_name(name)
        return self.assets_dir / f"{name}.json"

    def _image_path(self, name: str) -> Path:
        validate_asset_name(name)
        return self.assets_dir / f"{name}.png"

    def register_from_frame(
        self,
        name: str,
        frame_store: FrameStore,
        frame_id: str,
        *,
        region: Optional[Tuple[int, int, int, int]] = None,
    ) -> AssetRecord:
        """Register a named asset from a stored frame (or a cropped region of it)."""
        validate_asset_name(name)
        frame = frame_store.get_frame(frame_id)
        image = frame_store.load_image(frame_id)

        if region is not None:
            image = MatUtility.crop(image, Region(*region))

        h, w = image.shape[:2]
        png_bytes = MatUtility.encode_png(image)
        img_path = self._image_path(name)
        meta_path = self._meta_path(name)

        record = AssetRecord(
            name=name,
            image_path=str(img_path),
            width=int(w),
            height=int(h),
            created_at=time.time(),
            source_frame_id=frame.frame_id,
            device_id=frame.device_id,
            region=region,
        )
        _atomic_write_bytes(img_path, png_bytes)
        _atomic_write_json(meta_path, record.to_dict())
        return record

    def get(self, name: str) -> AssetRecord:
        """Load metadata for a registered asset."""
        meta_path = self._meta_path(name)
        if not meta_path.exists():
            raise AssetNotFoundError(f"Asset not found: {name}")
        data = json.loads(meta_path.read_text(encoding="utf-8"))
        return AssetRecord.from_dict(data)

    def load_image(self, name: str) -> np.ndarray:
        """Load the BGR image for a registered asset."""
        record = self.get(name)
        img_path = Path(record.image_path)
        if not img_path.exists():
            raise AssetNotFoundError(f"Asset image missing for {name}: {img_path}")
        img = cv2.imread(str(img_path), cv2.IMREAD_COLOR)
        if img is None:
            raise AssetNotFoundError(f"Failed to decode asset image for {name}: {img_path}")
        return img

    def list_assets(self) -> List[AssetRecord]:
        """List all registered assets sorted by name."""
        records: List[AssetRecord] = []
        for meta_path in sorted(self.assets_dir.glob("*.json")):
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            records.append(AssetRecord.from_dict(data))
        return records


class RefRegistry:
    """Persistent store for scoped match references."""

    def __init__(self, root_dir: Path) -> None:
        self.root_dir = Path(root_dir)
        self.refs_dir = self.root_dir / "refs"
        self.refs_dir.mkdir(parents=True, exist_ok=True)

    def _ref_path(self, ref_id: str) -> Path:
        validate_ref_id(ref_id)
        return self.refs_dir / f"{ref_id}.json"

    def save(self, ref: ScopedRef) -> ScopedRef:
        """Persist a scoped reference atomically."""
        _atomic_write_json(self._ref_path(ref.ref_id), ref.to_dict())
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
    ) -> Dict[str, Any]:
        """Match a named asset against a stored frame and return scoped refs."""
        frame = self.store.get_frame(frame_id)
        source_img = self.store.load_image(frame_id)
        template_img = self.assets.load_image(target)

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
            self.refs.save(ref)
            scoped_refs.append(ref.to_dict())

        return {
            "frame_id": frame.frame_id,
            "device_id": frame.device_id,
            "target": target,
            "found": len(scoped_refs) > 0,
            "count": len(scoped_refs),
            "matches": scoped_refs,
        }
