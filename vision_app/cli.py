"""CLI entrypoint for vision observation and export commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vision_app.observation import ObservationService, OperationError, UsageError
from vision_app.store import FrameStore


class _CliParser(argparse.ArgumentParser):
    """ArgumentParser that raises UsageError instead of calling sys.exit directly."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(message)


def _parse_region(raw: str) -> Tuple[int, int, int, int]:
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 4:
        raise UsageError(f"Region must be X1,Y1,X2,Y2, got {raw!r}")
    try:
        x1, y1, x2, y2 = (int(p) for p in parts)
    except ValueError as exc:
        raise UsageError(f"Region coordinates must be integers, got {raw!r}") from exc
    return x1, y1, x2, y2


def _build_parser() -> _CliParser:
    parser = _CliParser(prog="vision", add_help=True)
    parser.add_argument(
        "--store-dir",
        default=os.environ.get("VISION_STORE_DIR", ".vision_store"),
        help="Workspace-local frame store directory",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_devices = sub.add_parser("devices", help="List available devices")
    p_devices.add_argument("--json", action="store_true", help="Output JSON")

    p_cap = sub.add_parser("capabilities", help="Show device/platform capabilities")
    p_cap.add_argument("--device", default="adb", help="Device serial or 'desktop'")
    p_cap.add_argument("--json", action="store_true", help="Output JSON")

    p_snap = sub.add_parser("snapshot", help="Capture a screenshot from a device")
    p_snap.add_argument("--device", required=True, help="Device serial or 'desktop'")
    p_snap.add_argument("--region", default=None, help="Optional crop region X1,Y1,X2,Y2")
    p_snap.add_argument("--out", default=None, help="Optional output PNG path")
    p_snap.add_argument("--json", action="store_true", help="Output JSON")

    p_crop = sub.add_parser("crop", help="Crop an existing stored frame")
    p_crop.add_argument("--frame", required=True, help="Source frame ID")
    p_crop.add_argument("--region", required=True, help="Crop region X1,Y1,X2,Y2")
    p_crop.add_argument("--out", default=None, help="Optional output PNG path")
    p_crop.add_argument("--json", action="store_true", help="Output JSON")

    p_resize = sub.add_parser("resize", help="Resize an existing stored frame")
    p_resize.add_argument("--frame", required=True, help="Source frame ID")
    p_resize.add_argument("--scale", required=True, type=float, help="Positive scale factor")
    p_resize.add_argument("--out", default=None, help="Optional output PNG path")
    p_resize.add_argument("--json", action="store_true", help="Output JSON")

    return parser


def _emit_json(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def run_cli(
    argv: Optional[List[str]] = None,
    *,
    service: Optional[ObservationService] = None,
) -> int:
    """Execute CLI with given argv and return exit code (0, 2, 3, or 4)."""
    parser = _build_parser()
    command_name: Optional[str] = None
    device_name: Optional[str] = None

    try:
        args = parser.parse_args(argv)
        command_name = args.command
        device_name = getattr(args, "device", None)

        obs = service or ObservationService(store=FrameStore(Path(args.store_dir)))

        if args.command == "devices":
            data = obs.devices()
            _emit_json({"ok": True, "command": "devices", "device": None, "result": {"devices": data}})
            return 0

        if args.command == "capabilities":
            data = obs.capabilities(device_id=args.device)
            _emit_json({"ok": True, "command": "capabilities", "device": args.device, "result": data})
            return 0

        if args.command == "snapshot":
            region = _parse_region(args.region) if args.region else None
            data = obs.snapshot(args.device, region=region, out=args.out)
            _emit_json(
                {
                    "ok": True,
                    "command": "snapshot",
                    "device": args.device,
                    "result": data["frame"],
                    "artifact": data["artifact"],
                }
            )
            return 0

        if args.command == "crop":
            region = _parse_region(args.region)
            data = obs.crop(args.frame, region=region, out=args.out)
            _emit_json(
                {
                    "ok": True,
                    "command": "crop",
                    "device": data["frame"]["device_id"],
                    "result": data["frame"],
                    "artifact": data["artifact"],
                }
            )
            return 0

        if args.command == "resize":
            data = obs.resize(args.frame, scale=args.scale, out=args.out)
            _emit_json(
                {
                    "ok": True,
                    "command": "resize",
                    "device": data["frame"]["device_id"],
                    "result": data["frame"],
                    "artifact": data["artifact"],
                }
            )
            return 0

        raise UsageError(f"Unknown command: {args.command}")

    except OperationError as exc:
        sys.stderr.write(f"[{exc.code}] {exc.message}\n")
        _emit_json(
            {
                "ok": False,
                "command": command_name,
                "device": device_name,
                "error": {
                    "code": exc.code,
                    "message": exc.message,
                    "retryable": exc.retryable,
                },
            }
        )
        return exc.exit_code
    except Exception as exc:
        sys.stderr.write(f"[INTERNAL_ERROR] {exc}\n")
        _emit_json(
            {
                "ok": False,
                "command": command_name,
                "device": device_name,
                "error": {
                    "code": "INTERNAL_ERROR",
                    "message": str(exc),
                    "retryable": False,
                },
            }
        )
        return 3


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
