"""Strict, read-only Android discovery for the additive Phase 9 API."""

import re

from service.platform.adb.adb_command import AdbCommand
from vision_app.observation import OperationError


ANDROID_DEVICES_SCHEMA = {
    "type": "object", "properties": {}, "required": [],
    "additionalProperties": False,
}
_SERIAL = re.compile(r"(?!(?:adb|desktop)\Z)[A-Za-z0-9_.:-]{1,128}\Z")
_STATES = {"device", "offline", "unauthorized", "bootloader", "recovery",
           "sideload", "rescue", "host", "connecting", "authorizing", "detached"}


def validate_serial(device):
    """Validate an exact serial without trimming, aliases or implicit selection."""
    if not isinstance(device, str) or not _SERIAL.fullmatch(device):
        raise OperationError("INVALID_DEVICE", "An explicit Android serial is required")
    return device


def _failed():
    # Never expose subprocess output (which may include host paths or secrets).
    return OperationError("DISCOVERY_FAILED", "Android discovery failed", retryable=True)


def android_devices(platform_factory):
    """Use the existing platform seam and typed ADB subprocess; never legacy fallback."""
    try:
        platform = platform_factory("adb")
        result = platform.adb.run_argv(AdbCommand.DEVICE_LIST.get_argv(), serial="")
    except (OSError, TimeoutError) as exc:
        raise _failed() from exc
    if not result.ok or not isinstance(result.stdout, str):
        raise _failed()
    lines = result.stdout.splitlines()
    if not lines or lines[0] != "List of devices attached":
        raise _failed()
    devices, seen = [], set()
    for line in lines[1:]:
        if not line.strip():
            continue
        # `adb devices` (without -l) emits exactly serial TAB state.
        fields = line.split("\t")
        if len(fields) != 2:
            raise _failed()
        serial, state = fields
        if not _SERIAL.fullmatch(serial) or state not in _STATES or serial in seen:
            raise _failed()
        seen.add(serial)
        if state == "device":
            devices.append({"device_id": serial, "platform": "adb"})
    return {"devices": devices}


class DiscoveryService:
    """One validation/envelope path shared by CLI and MCP."""

    def __init__(self, observation):
        self.observation = observation

    def invoke(self, request):
        if type(request) is not dict or request:
            return self._error("INVALID_ARGUMENT", "android_devices requires an empty object"), 2
        try:
            return {"ok": True, "result": self.observation.android_devices()}, 0
        except OperationError as exc:
            return self._error(exc.code, exc.message, exc.retryable), exc.exit_code
        except Exception:
            return self._error("INTERNAL_ERROR", "Internal discovery error"), 3

    @staticmethod
    def _error(code, message, retryable=False):
        return {"ok": False, "error": {"code": code, "message": message,
                "details": {}, "retryable": retryable}}

    def require_online(self, device):
        """Admission helper for subsequent explicit-device paths; no fallback."""
        validate_serial(device)
        rows = self.observation.android_devices()["devices"]
        if not any(row["device_id"] == device for row in rows):
            raise OperationError("DEVICE_UNAVAILABLE", "Android device is unavailable", retryable=True)
        return device
