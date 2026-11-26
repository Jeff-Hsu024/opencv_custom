"""Application-layer action service with coordinate mapping, validation, and receipts."""

from __future__ import annotations

import subprocess
import time
from contextlib import nullcontext
from typing import Any, Callable, Dict, Optional, Tuple

from vision_app.assets import RefRegistry, StaleRefError
from vision_app.coordinator import ClaimError, Owner
from vision_app.epochs import ActionIntent, DeviceEpochs
from vision_app.metadata import canonical_store
from vision_app.observation import OperationError, UsageError, _default_platform_factory
from vision_app.store import DeviceMismatchError, FrameStore, OutOfBoundsError


def _validate_local_point(x: int, y: int, width: int, height: int, *, label: str = "point") -> Tuple[int, int]:
    if x < 0 or y < 0 or x >= width or y >= height:
        raise OutOfBoundsError(
            f"{label} ({x}, {y}) out of bounds for {width}x{height}"
        )
    return int(x), int(y)


def _execute_platform_call(
    action_name: str,
    device_id: str,
    fn: Callable[[], bool],
) -> None:
    """Execute a single platform action without retries, distinguishing timeouts."""
    try:
        ok = fn()
    except (TimeoutError, subprocess.TimeoutExpired) as exc:
        raise OperationError(
            code="ACTION_TIMEOUT",
            message=f"Action {action_name} timed out on device {device_id}: {exc}",
            retryable=False,
            exit_code=4,
        ) from exc
    except OperationError:
        raise
    except Exception as exc:
        if "timeout" in type(exc).__name__.lower():
            raise OperationError(
                code="ACTION_TIMEOUT",
                message=f"Action {action_name} timed out on device {device_id}: {exc}",
                retryable=False,
                exit_code=4,
            ) from exc
        raise OperationError(
            code="ACTION_FAILED",
            message=f"Action {action_name} failed on device {device_id}: {exc}",
            retryable=False,
            exit_code=3,
        ) from exc

    if not ok:
        raise OperationError(
            code="ACTION_FAILED",
            message=f"Action {action_name} returned failure on device {device_id}",
            retryable=False,
            exit_code=3,
        )


class ActionService:
    """Orchestrates validated device actions with coordinate mapping and receipts."""

    def __init__(
        self,
        store: FrameStore,
        *,
        ref_registry: Optional[RefRegistry] = None,
        platform_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.store = store
        self.epochs = DeviceEpochs(store)
        self.ref_registry = ref_registry or RefRegistry(store.store_dir)
        if canonical_store(self.ref_registry.root_dir) != self.epochs.root:
            raise ValueError("Reference registry must use the action Store")
        self._platform_factory = platform_factory or _default_platform_factory

    def _get_platform(self, device_id: str) -> Any:
        try:
            return self._platform_factory(device_id)
        except OperationError:
            raise
        except Exception as exc:
            raise OperationError("PLATFORM_INIT_FAILED", str(exc), exit_code=3) from exc

    def click(
        self,
        device_id: str,
        *,
        frame_id: Optional[str] = None,
        point: Optional[Tuple[int, int]] = None,
        ref_id: Optional[str] = None,
        max_age_seconds: Optional[float] = None,
        device_owner: Optional[Owner] = None,
        session_id: Optional[str] = None,
        intent: Optional[ActionIntent] = None,
    ) -> Dict[str, Any]:
        """Click a frame-local point or a scoped reference on the target device."""
        using_frame = frame_id is not None or point is not None
        using_ref = ref_id is not None

        if using_frame and using_ref:
            raise UsageError("Specify either (--frame and --point) or --ref, not both")
        if not using_frame and not using_ref:
            raise UsageError("Must specify either (--frame and --point) or --ref")
        if using_frame and (frame_id is None or point is None):
            raise UsageError("Both --frame and --point are required together")

        if max_age_seconds is not None and max_age_seconds <= 0:
            raise UsageError(f"max_age_seconds must be positive, got {max_age_seconds}")
        if intent is not None and (ref_id is None or max_age_seconds is None):
            raise UsageError("Guarded click requires a reference and max age")

        with self.epochs.device_owner(device_id, legacy=intent is None, owner=device_owner) as owner:
            if owner is None:
                raise OperationError("DEVICE_BUSY", f"Device {device_id} is busy", retryable=True)
            return self._click(owner, device_id, frame_id, point, ref_id, max_age_seconds, session_id, intent)

    def _click(self, owner, device_id, frame_id, point, ref_id, max_age_seconds, session_id, intent):
        now = time.time()

        if ref_id is not None:
            ref = self.ref_registry.validate(
                ref_id,
                device_id=device_id,
                frame_store=self.store,
            )
            try:
                self.epochs.guard_ref(owner, ref.ref_id, device_id, session_id=session_id, legacy=intent is None)
            except ClaimError as exc:
                raise OperationError(exc.code, str(exc)) from exc
            if max_age_seconds is not None and (now - ref.created_at) > max_age_seconds:
                raise StaleRefError(
                    f"Reference {ref_id} is stale (age {now - ref.created_at:.2f}s > {max_age_seconds}s)"
                )
            dx, dy = ref.device_center
            _validate_local_point(dx, dy, ref.source_width, ref.source_height, label="mapped point")
            source_meta: Dict[str, Any] = {
                "mode": "ref",
                "ref_id": ref.ref_id,
                "frame_id": ref.frame_id,
                "target": ref.target,
                "device_bbox": list(ref.device_bbox),
            }
        else:
            assert frame_id is not None and point is not None
            frame = self.store.get_frame(frame_id)
            if frame.device_id != device_id:
                raise DeviceMismatchError(
                    f"Frame {frame_id} belongs to device {frame.device_id!r}, expected {device_id!r}"
                )
            if max_age_seconds is not None and (now - frame.timestamp) > max_age_seconds:
                raise StaleRefError(
                    f"Frame {frame_id} is stale (age {now - frame.timestamp:.2f}s > {max_age_seconds}s)"
                )
            lx, ly = _validate_local_point(point[0], point[1], frame.width, frame.height, label="local point")
            dx, dy = frame.transform.map_point(lx, ly)
            _validate_local_point(dx, dy, frame.source_width, frame.source_height, label="mapped point")
            source_meta = {
                "mode": "frame_point",
                "frame_id": frame.frame_id,
                "local_point": [lx, ly],
                "transform": frame.transform.to_dict(),
            }

        pin = (self.store.pin_frames([source_meta["frame_id"]], device_id=device_id)
               if intent is not None else nullcontext())
        with pin:
            platform = self._get_platform(device_id)
            if intent is None:
                self.epochs.advance_raw(owner, device_id)
            else:
                self.epochs.begin_intent(owner, intent.request_owner, intent.request_id,
                                         intent.step_id, intent.pending_receipt)
            _execute_platform_call("click", device_id, lambda: bool(platform.click(dx, dy)))

        return {
            "action": "click",
            "device_id": device_id,
            "status": "executed",
            "verified": False,
            "target": {"x": dx, "y": dy},
            "source": source_meta,
            "executed_at": time.time(),
        }

    def swipe(
        self,
        device_id: str,
        *,
        start: Tuple[int, int],
        end: Tuple[int, int],
        duration_ms: int = 500,
        frame_id: Optional[str] = None,
        device_owner: Optional[Owner] = None,
    ) -> Dict[str, Any]:
        """Swipe from start to end coordinates on the target device."""
        if duration_ms <= 0:
            raise UsageError(f"duration must be positive, got {duration_ms}")

        if frame_id is not None:
            frame = self.store.get_frame(frame_id)
            if frame.device_id != device_id:
                raise DeviceMismatchError(
                    f"Frame {frame_id} belongs to device {frame.device_id!r}, expected {device_id!r}"
                )
            sx, sy = _validate_local_point(start[0], start[1], frame.width, frame.height, label="from")
            ex, ey = _validate_local_point(end[0], end[1], frame.width, frame.height, label="to")
            dx1, dy1 = frame.transform.map_point(sx, sy)
            dx2, dy2 = frame.transform.map_point(ex, ey)
            _validate_local_point(dx1, dy1, frame.source_width, frame.source_height, label="mapped from")
            _validate_local_point(dx2, dy2, frame.source_width, frame.source_height, label="mapped to")
        else:
            dx1, dy1 = int(start[0]), int(start[1])
            dx2, dy2 = int(end[0]), int(end[1])
            if dx1 < 0 or dy1 < 0 or dx2 < 0 or dy2 < 0:
                raise OutOfBoundsError(
                    f"Swipe coordinates must be non-negative, got ({dx1}, {dy1}) -> ({dx2}, {dy2})"
                )

        self._raw("swipe", device_id, device_owner,
                  lambda platform: platform.swipe(dx1, dy1, dx2, dy2, duration=duration_ms))

        return {
            "action": "swipe",
            "device_id": device_id,
            "status": "executed",
            "verified": False,
            "from": [dx1, dy1],
            "to": [dx2, dy2],
            "duration_ms": int(duration_ms),
            "executed_at": time.time(),
        }

    def type_text(self, device_id: str, *, text: str, device_owner: Optional[Owner] = None) -> Dict[str, Any]:
        """Type text on the target device."""
        if text == "":
            raise UsageError("Text must not be empty")

        self._raw("type", device_id, device_owner, lambda platform: platform.type_text(text))

        return {
            "action": "type",
            "device_id": device_id,
            "status": "executed",
            "verified": False,
            "text_length": len(text),
            "executed_at": time.time(),
        }

    def press_key(self, device_id: str, *, key: str, device_owner: Optional[Owner] = None) -> Dict[str, Any]:
        """Send a key event on the target device."""
        if not key or not key.strip():
            raise UsageError("Key must not be empty")

        self._raw("key", device_id, device_owner, lambda platform: platform.key_event(key))

        return {
            "action": "key",
            "device_id": device_id,
            "status": "executed",
            "verified": False,
            "key": key,
            "executed_at": time.time(),
        }

    def _raw(self, action, device_id, device_owner, call):
        with self.epochs.device_owner(device_id, legacy=True, owner=device_owner) as owner:
            if owner is None:
                raise OperationError("DEVICE_BUSY", f"Device {device_id} is busy", retryable=True)
            platform = self._get_platform(device_id)
            self.epochs.advance_raw(owner, device_id)
            _execute_platform_call(action, device_id, lambda: bool(call(platform)))
