"""Application-layer observation service for devices, capture, crop, resize, and export."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cv2
import numpy as np

from vision_app.store import FrameRecord, FrameStore, OutOfBoundsError, StoreError
from vision_app.transforms import CoordinateTransform


class OperationError(Exception):
    """Structured operation error mapped to CLI exit codes."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool = False,
        exit_code: int = 3,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.retryable = retryable
        self.exit_code = exit_code


class UsageError(OperationError):
    """Invalid user arguments or syntax, mapped to exit code 2."""

    def __init__(self, message: str, *, code: str = "INVALID_USAGE") -> None:
        super().__init__(code, message, retryable=False, exit_code=2)


def _encode_png(image: np.ndarray) -> bytes:
    ok, buf = cv2.imencode(".png", image)
    if not ok:
        raise OperationError("ENCODE_FAILED", "Failed to encode image as PNG")
    return buf.tobytes()


def _export_png(image: np.ndarray, out_path: str) -> Dict[str, Any]:
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _encode_png(image)
    target.write_bytes(data)
    h, w = image.shape[:2]
    return {
        "path": str(target),
        "mime_type": "image/png",
        "width": int(w),
        "height": int(h),
        "bytes": len(data),
    }


def _artifact_for_record(store: FrameStore, rec: FrameRecord) -> Dict[str, Any]:
    path = store.resolve_image_path(rec.image_path)
    size_bytes = path.stat().st_size if path.exists() else 0
    return {
        "path": str(path),
        "mime_type": "image/png",
        "width": rec.width,
        "height": rec.height,
        "bytes": int(size_bytes),
    }


def _validate_region(region: Tuple[int, int, int, int], width: int, height: int) -> Tuple[int, int, int, int]:
    x1, y1, x2, y2 = region
    if x1 < 0 or y1 < 0 or x2 <= x1 or y2 <= y1 or x2 > width or y2 > height:
        raise OutOfBoundsError(
            f"Region ({x1}, {y1}, {x2}, {y2}) out of bounds for {width}x{height}"
        )
    return x1, y1, x2, y2


def _default_platform_factory(device_id: str) -> Any:
    from service.core.opencv.open_cv_service import OpenCvService

    opencv = OpenCvService()
    if device_id == "desktop":
        from service.platform.robot.robot_platform import RobotPlatform

        return RobotPlatform(opencv)

    from service.platform.adb.adb import Adb
    from service.platform.adb.adb_platform import AdbPlatform

    adb = Adb(device_id=device_id)
    return AdbPlatform(adb, opencv)


class ObservationService:
    """Orchestrates device discovery, capture, transforms, and PNG export."""

    def __init__(
        self,
        store: Optional[FrameStore] = None,
        platform_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.store = store or FrameStore(".vision_store")
        self._platform_factory = platform_factory or _default_platform_factory

    def devices(self) -> List[Dict[str, Any]]:
        """List available ADB devices and the local desktop target."""
        result: List[Dict[str, Any]] = []
        try:
            platform = self._platform_factory("adb")
            adb_devices = platform.get_devices()
            for serial in adb_devices:
                result.append({"device_id": serial, "platform": "adb"})
        except Exception:
            pass
        result.append({"device_id": "desktop", "platform": "desktop"})
        return result

    def capabilities(self, device_id: str = "adb") -> Dict[str, Any]:
        """Return capability metadata for the specified device or platform."""
        try:
            platform = self._platform_factory(device_id)
            caps = platform.capabilities()
            return {"device_id": device_id, "capabilities": caps}
        except OperationError:
            raise
        except Exception as exc:
            raise OperationError(
                "CAPABILITIES_FAILED",
                f"Failed to query capabilities for {device_id}: {exc}",
            ) from exc

    def snapshot(
        self,
        device_id: str,
        *,
        region: Optional[Tuple[int, int, int, int]] = None,
        out: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Capture a single frame from device_id, optionally crop, and optionally export."""
        if not device_id or not device_id.strip():
            raise UsageError("Device serial/id must not be empty")

        try:
            platform = self._platform_factory(device_id)
            image = platform.snapshot()
        except TimeoutError as exc:
            raise OperationError(
                "CAPTURE_TIMEOUT",
                f"Snapshot timed out for {device_id}: {exc}",
                retryable=True,
                exit_code=4,
            ) from exc
        except OperationError:
            raise
        except Exception as exc:
            raise OperationError(
                "CAPTURE_FAILED",
                f"Snapshot failed for {device_id}: {exc}",
                retryable=True,
            ) from exc

        if image is None or not isinstance(image, np.ndarray) or image.size == 0:
            raise OperationError(
                "CAPTURE_FAILED",
                f"Snapshot returned no image for {device_id}",
                retryable=True,
            )

        src_h, src_w = image.shape[:2]
        transform = CoordinateTransform()
        out_image = image

        if region is not None:
            try:
                x1, y1, x2, y2 = _validate_region(region, src_w, src_h)
            except OutOfBoundsError as exc:
                raise OperationError("OUT_OF_BOUNDS", str(exc)) from exc
            out_image = image[y1:y2, x1:x2].copy()
            transform = CoordinateTransform.for_crop(x1, y1)

        rec = self.store.save_frame(
            out_image,
            device_id,
            source_width=src_w,
            source_height=src_h,
            transform=transform,
        )

        artifact = _export_png(out_image, out) if out else _artifact_for_record(self.store, rec)
        return {
            "frame": rec.to_dict(),
            "artifact": artifact,
        }

    def crop(
        self,
        frame_id: str,
        region: Tuple[int, int, int, int],
        *,
        out: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Crop an existing stored frame without recapturing from any device."""
        try:
            parent = self.store.get_frame(frame_id)
            image = self.store.load_image(frame_id)
            x1, y1, x2, y2 = _validate_region(region, parent.width, parent.height)
        except StoreError as exc:
            raise OperationError("FRAME_ERROR", str(exc)) from exc

        cropped = image[y1:y2, x1:x2].copy()
        composed = parent.transform.compose(CoordinateTransform.for_crop(x1, y1))
        rec = self.store.save_frame(
            cropped,
            parent.device_id,
            source_width=parent.source_width,
            source_height=parent.source_height,
            parent_id=parent.frame_id,
            transform=composed,
            rotation=parent.rotation,
        )
        artifact = _export_png(cropped, out) if out else _artifact_for_record(self.store, rec)
        return {
            "frame": rec.to_dict(),
            "artifact": artifact,
        }

    def resize(
        self,
        frame_id: str,
        scale: float,
        *,
        out: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Resize an existing stored frame by scale without recapturing."""
        if scale <= 0:
            raise UsageError(f"Scale must be positive, got {scale}")

        try:
            parent = self.store.get_frame(frame_id)
            image = self.store.load_image(frame_id)
        except StoreError as exc:
            raise OperationError("FRAME_ERROR", str(exc)) from exc

        dst_w = max(1, int(round(parent.width * scale)))
        dst_h = max(1, int(round(parent.height * scale)))
        interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
        resized = cv2.resize(image, (dst_w, dst_h), interpolation=interp)

        composed = parent.transform.compose(
            CoordinateTransform.for_resize(
                src_width=parent.width,
                src_height=parent.height,
                dst_width=dst_w,
                dst_height=dst_h,
            )
        )
        rec = self.store.save_frame(
            resized,
            parent.device_id,
            source_width=parent.source_width,
            source_height=parent.source_height,
            parent_id=parent.frame_id,
            transform=composed,
            rotation=parent.rotation,
        )
        artifact = _export_png(resized, out) if out else _artifact_for_record(self.store, rec)
        return {
            "frame": rec.to_dict(),
            "artifact": artifact,
        }
