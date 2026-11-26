"""Application-layer state wait and image comparison service."""

from __future__ import annotations

import time
from typing import Any, Callable, Dict, Optional, Tuple

import numpy as np

from vision_app.assets import AssetRegistry
from vision_app.observation import (
    OperationError,
    UsageError,
    _artifact_for_record,
    _default_platform_factory,
    _validate_region,
)
from vision_app.store import DeviceMismatchError, FrameStore


def _validate_wait_params(
    timeout: float,
    interval: float,
    max_captures: int,
) -> Tuple[float, float, int]:
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout < 0:
        raise UsageError(f"timeout must be a non-negative number, got {timeout!r}")
    if isinstance(interval, bool) or not isinstance(interval, (int, float)) or interval <= 0:
        raise UsageError(f"interval must be a positive number, got {interval!r}")
    if isinstance(max_captures, bool) or not isinstance(max_captures, int) or max_captures < 1:
        raise UsageError(f"max_captures must be a positive integer, got {max_captures!r}")
    return float(timeout), float(interval), int(max_captures)


def _crop_if_region(
    image: np.ndarray,
    region: Optional[Tuple[int, int, int, int]],
) -> np.ndarray:
    if region is None:
        return image
    h, w = image.shape[:2]
    x1, y1, x2, y2 = _validate_region(region, w, h)
    return image[y1:y2, x1:x2].copy()


class WaitService:
    """Orchestrates bounded state waits (changed, stable, image) and frame comparisons."""

    def __init__(
        self,
        store: FrameStore,
        *,
        asset_registry: Optional[AssetRegistry] = None,
        platform_factory: Optional[Callable[[str], Any]] = None,
        clock: Callable[[], float] = time.monotonic,
        sleeper: Callable[[float], None] = time.sleep,
    ) -> None:
        self.store = store
        self.asset_registry = asset_registry or AssetRegistry(store.store_dir)
        self._platform_factory = platform_factory or _default_platform_factory
        self._clock = clock
        self._sleeper = sleeper

    def _get_platform(self, device_id: str) -> Any:
        try:
            return self._platform_factory(device_id)
        except OperationError:
            raise
        except Exception as exc:
            raise OperationError("PLATFORM_INIT_FAILED", str(exc), exit_code=3) from exc

    def _capture(self, platform: Any, device_id: str) -> np.ndarray:
        image = platform.snapshot()
        if image is None:
            raise OperationError(
                code="CAPTURE_FAILED",
                message=f"Failed to capture screenshot from device {device_id}",
                retryable=True,
                exit_code=3,
            )
        return image

    def compare_frames(
        self,
        frame_id_a: str,
        frame_id_b: str,
        *,
        region: Optional[Tuple[int, int, int, int]] = None,
        pixel_tolerance: int = 0,
        max_changed_ratio: float = 0.0,
    ) -> Dict[str, Any]:
        """Compare two stored frames (optionally within an ROI) using Core compare_images."""
        from service.core.opencv.open_cv_service import OpenCvService

        img_a = self.store.load_image(frame_id_a)
        img_b = self.store.load_image(frame_id_b)
        roi_a = _crop_if_region(img_a, region)
        roi_b = _crop_if_region(img_b, region)
        res = OpenCvService().compare_images(
            roi_a,
            roi_b,
            pixel_tolerance=pixel_tolerance,
            max_changed_ratio=max_changed_ratio,
        )
        return {
            "changed_ratio": res.changed_ratio,
            "changed_pixels": res.changed_pixels,
            "total_pixels": res.total_pixels,
            "pixel_tolerance": res.pixel_tolerance,
            "max_changed_ratio": res.max_changed_ratio,
            "within_tolerance": res.within_tolerance,
            "region": list(region) if region is not None else None,
        }

    def wait_changed(
        self,
        device_id: str,
        *,
        baseline_frame_id: Optional[str] = None,
        region: Optional[Tuple[int, int, int, int]] = None,
        timeout: float = 10.0,
        interval: float = 0.5,
        max_captures: int = 100,
        pixel_tolerance: int = 0,
        min_changed_ratio: float = 0.01,
    ) -> Dict[str, Any]:
        """Wait until the screen (or ROI) changes relative to a baseline."""
        from service.core.opencv.open_cv_service import OpenCvService

        timeout_f, interval_f, max_cap = _validate_wait_params(timeout, interval, max_captures)
        if isinstance(min_changed_ratio, bool) or not isinstance(min_changed_ratio, (int, float)) or not (0.0 <= float(min_changed_ratio) <= 1.0):
            raise UsageError(f"min_changed_ratio must be in [0.0, 1.0], got {min_changed_ratio!r}")
        min_ratio_f = float(min_changed_ratio)

        opencv = OpenCvService()
        platform = self._get_platform(device_id)
        start = self._clock()
        deadline = start + timeout_f
        captures = 0

        if baseline_frame_id is not None:
            base_full = self.store.load_image(baseline_frame_id, device_id=device_id)
            baseline_roi = _crop_if_region(base_full, region)
        else:
            base_full = self._capture(platform, device_id)
            captures += 1
            baseline_roi = _crop_if_region(base_full, region)

        while True:
            if captures >= max_cap:
                raise OperationError(
                    code="WAIT_TIMEOUT",
                    message=f"wait --changed reached max_captures ({max_cap}) on {device_id}",
                    retryable=True,
                    exit_code=4,
                )
            remaining = deadline - self._clock()
            if remaining <= 0 and captures > 0:
                raise OperationError(
                    code="WAIT_TIMEOUT",
                    message=f"wait --changed timed out after {timeout_f}s on {device_id}",
                    retryable=True,
                    exit_code=4,
                )

            current_full = self._capture(platform, device_id)
            captures += 1
            current_roi = _crop_if_region(current_full, region)
            cmp = opencv.compare_images(
                baseline_roi,
                current_roi,
                pixel_tolerance=pixel_tolerance,
                max_changed_ratio=min_ratio_f,
            )
            changed = cmp.changed_ratio > 0.0 if min_ratio_f == 0.0 else cmp.changed_ratio >= min_ratio_f
            if changed:
                rec = self.store.save_frame(device_id=device_id, image=current_full)
                return {
                    "condition": "changed",
                    "verified": True,
                    "device_id": device_id,
                    "frame_id": rec.frame_id,
                    "artifact": _artifact_for_record(self.store, rec),
                    "captures": captures,
                    "elapsed_seconds": max(0.0, self._clock() - start),
                    "changed_ratio": cmp.changed_ratio,
                    "changed_pixels": cmp.changed_pixels,
                    "total_pixels": cmp.total_pixels,
                    "region": list(region) if region is not None else None,
                }

            remaining = deadline - self._clock()
            if remaining <= 0 or captures >= max_cap:
                raise OperationError(
                    code="WAIT_TIMEOUT",
                    message=f"wait --changed timed out after {timeout_f}s on {device_id}",
                    retryable=True,
                    exit_code=4,
                )
            self._sleeper(min(interval_f, remaining))

    def wait_stable(
        self,
        device_id: str,
        *,
        region: Optional[Tuple[int, int, int, int]] = None,
        timeout: float = 10.0,
        interval: float = 0.5,
        stable_duration: float = 1.0,
        max_captures: int = 100,
        pixel_tolerance: int = 0,
        max_changed_ratio: float = 0.0,
    ) -> Dict[str, Any]:
        """Wait until the screen (or ROI) remains within tolerance for stable_duration."""
        from service.core.opencv.open_cv_service import OpenCvService

        timeout_f, interval_f, max_cap = _validate_wait_params(timeout, interval, max_captures)
        if isinstance(stable_duration, bool) or not isinstance(stable_duration, (int, float)) or stable_duration < 0:
            raise UsageError(f"stable_duration must be a non-negative number, got {stable_duration!r}")
        stable_req = float(stable_duration)

        opencv = OpenCvService()
        platform = self._get_platform(device_id)
        start = self._clock()
        deadline = start + timeout_f

        prev_full = self._capture(platform, device_id)
        captures = 1
        prev_roi = _crop_if_region(prev_full, region)
        stable_since = self._clock()

        while True:
            if captures >= max_cap:
                raise OperationError(
                    code="WAIT_TIMEOUT",
                    message=f"wait --stable reached max_captures ({max_cap}) on {device_id}",
                    retryable=True,
                    exit_code=4,
                )
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise OperationError(
                    code="WAIT_TIMEOUT",
                    message=f"wait --stable timed out after {timeout_f}s on {device_id}",
                    retryable=True,
                    exit_code=4,
                )
            self._sleeper(min(interval_f, remaining))

            current_full = self._capture(platform, device_id)
            captures += 1
            now = self._clock()
            current_roi = _crop_if_region(current_full, region)
            cmp = opencv.compare_images(
                prev_roi,
                current_roi,
                pixel_tolerance=pixel_tolerance,
                max_changed_ratio=max_changed_ratio,
            )
            if cmp.within_tolerance:
                if (now - stable_since) >= stable_req:
                    rec = self.store.save_frame(device_id=device_id, image=current_full)
                    return {
                        "condition": "stable",
                        "verified": True,
                        "device_id": device_id,
                        "frame_id": rec.frame_id,
                        "artifact": _artifact_for_record(self.store, rec),
                        "captures": captures,
                        "elapsed_seconds": max(0.0, now - start),
                        "stable_seconds": max(0.0, now - stable_since),
                        "changed_ratio": cmp.changed_ratio,
                        "region": list(region) if region is not None else None,
                    }
            else:
                stable_since = now
            prev_roi = current_roi

    def wait_image(
        self,
        device_id: str,
        *,
        target_name: str,
        region: Optional[Tuple[int, int, int, int]] = None,
        timeout: float = 10.0,
        interval: float = 0.5,
        max_captures: int = 100,
        threshold: float = 0.8,
        color_mode: str = "gray",
    ) -> Dict[str, Any]:
        """Wait until a registered asset template is matched on the device."""
        from service.core.opencv.open_cv_service import OpenCvService

        timeout_f, interval_f, max_cap = _validate_wait_params(timeout, interval, max_captures)
        template = self.asset_registry.load_image(target_name)
        opencv = OpenCvService()
        platform = self._get_platform(device_id)
        start = self._clock()
        deadline = start + timeout_f
        captures = 0

        while True:
            if captures >= max_cap:
                raise OperationError(
                    code="WAIT_TIMEOUT",
                    message=f"wait --image {target_name!r} reached max_captures ({max_cap}) on {device_id}",
                    retryable=True,
                    exit_code=4,
                )
            current_full = self._capture(platform, device_id)
            captures += 1
            search_img = _crop_if_region(current_full, region)
            match = opencv.match_template(
                search_img,
                template,
                threshold=threshold,
                color_mode=color_mode,
            )
            if match is not None:
                ox, oy = (region[0], region[1]) if region is not None else (0, 0)
                x1, y1, x2, y2 = match.bbox
                cx, cy = match.center
                rec = self.store.save_frame(device_id=device_id, image=current_full)
                return {
                    "condition": "image",
                    "verified": True,
                    "device_id": device_id,
                    "target": target_name,
                    "frame_id": rec.frame_id,
                    "artifact": _artifact_for_record(self.store, rec),
                    "captures": captures,
                    "elapsed_seconds": max(0.0, self._clock() - start),
                    "match": {
                        "score": match.score,
                        "bbox": [x1 + ox, y1 + oy, x2 + ox, y2 + oy],
                        "center": [cx + ox, cy + oy],
                    },
                    "region": list(region) if region is not None else None,
                }

            remaining = deadline - self._clock()
            if remaining <= 0 or captures >= max_cap:
                raise OperationError(
                    code="WAIT_TIMEOUT",
                    message=f"wait --image {target_name!r} timed out after {timeout_f}s on {device_id}",
                    retryable=True,
                    exit_code=4,
                )
            self._sleeper(min(interval_f, remaining))
