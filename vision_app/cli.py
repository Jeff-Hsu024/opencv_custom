"""CLI entrypoint for vision observation and export commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vision_app.assets import (
    AssetNotFoundError,
    AssetRegistry,
    InvalidAssetNameError,
    MatchingService,
)
from vision_app.observation import ObservationService, OperationError, UsageError
from vision_app.store import FrameNotFoundError, FrameStore, InvalidFrameIdError


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

    p_assets = sub.add_parser("assets", help="Manage named template assets")
    assets_sub = p_assets.add_subparsers(dest="assets_command", required=True)

    p_assets_reg = assets_sub.add_parser("register", help="Register a named asset from a frame")
    p_assets_reg.add_argument("--name", required=True, help="Safe asset name")
    p_assets_reg.add_argument("--frame", required=True, help="Source frame ID")
    p_assets_reg.add_argument("--region", default=None, help="Optional crop region X1,Y1,X2,Y2")
    p_assets_reg.add_argument("--json", action="store_true", help="Output JSON")

    p_assets_list = assets_sub.add_parser("list", help="List registered named assets")
    p_assets_list.add_argument("--json", action="store_true", help="Output JSON")

    p_find = sub.add_parser("find", help="Find a named asset in a stored frame")
    p_find.add_argument("--frame", required=True, help="Target frame ID")
    p_find.add_argument("--target", required=True, help="Registered asset name")
    p_find.add_argument("--all", dest="find_all", action="store_true", help="Return all matches")
    p_find.add_argument("--threshold", type=float, default=0.8, help="Match threshold in [0.0, 1.0]")
    p_find.add_argument("--max-results", type=int, default=10, help="Maximum matches for --all")
    p_find.add_argument("--color-mode", default="gray", choices=["gray", "bgr"], help="Color mode")
    p_find.add_argument("--json", action="store_true", help="Output JSON")

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

        if args.command == "assets":
            store = obs.store
            registry = AssetRegistry(store.store_dir)
            if args.assets_command == "register":
                command_name = "assets register"
                region = _parse_region(args.region) if args.region else None
                try:
                    record = registry.register_from_frame(args.name, store, args.frame, region=region)
                except (InvalidAssetNameError, InvalidFrameIdError, ValueError) as exc:
                    raise UsageError(str(exc)) from exc
                except FrameNotFoundError as exc:
                    raise OperationError(code="FRAME_NOT_FOUND", message=str(exc), exit_code=3) from exc
                _emit_json(
                    {
                        "ok": True,
                        "command": "assets register",
                        "device": record.device_id,
                        "result": record.to_dict(),
                    }
                )
                return 0
            if args.assets_command == "list":
                command_name = "assets list"
                items = [a.to_dict() for a in registry.list_assets()]
                _emit_json(
                    {
                        "ok": True,
                        "command": "assets list",
                        "device": None,
                        "result": {"assets": items, "count": len(items)},
                    }
                )
                return 0

        if args.command == "find":
            store = obs.store
            matcher = MatchingService(store=store)
            try:
                result = matcher.find(
                    args.frame,
                    args.target,
                    find_all=args.find_all,
                    threshold=args.threshold,
                    max_results=args.max_results,
                    color_mode=args.color_mode,
                )
            except (InvalidAssetNameError, InvalidFrameIdError, ValueError) as exc:
                raise UsageError(str(exc)) from exc
            except FrameNotFoundError as exc:
                raise OperationError(code="FRAME_NOT_FOUND", message=str(exc), exit_code=3) from exc
            except AssetNotFoundError as exc:
                raise OperationError(code="ASSET_NOT_FOUND", message=str(exc), exit_code=3) from exc
            _emit_json(
                {
                    "ok": True,
                    "command": "find",
                    "device": result["device_id"],
                    "result": result,
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
