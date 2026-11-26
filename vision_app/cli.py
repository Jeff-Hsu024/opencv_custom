"""CLI entrypoint for vision observation and export commands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from vision_app.actions import ActionService
from vision_app.assets import (
    AssetNotFoundError,
    AssetRegistry,
    InvalidAssetNameError,
    InvalidRefIdError,
    MatchingService,
    RefNotFoundError,
    StaleRefError,
)
from vision_app.observation import ObservationService, OperationError, UsageError
from vision_app.store import (
    DeviceMismatchError,
    FrameNotFoundError,
    FrameStore,
    InvalidFrameIdError,
    OutOfBoundsError,
)
from vision_app.waits import WaitService
from vision_app.recorder import Recorder, OPERATIONS, workspace_lock
from vision_app.workflow import WorkflowBuilder
from vision_app.runtime import WorkflowRuntime


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


def _parse_point(raw: str, *, label: str = "Point") -> Tuple[int, int]:
    parts = [p.strip() for p in raw.split(",")]
    if len(parts) != 2:
        raise UsageError(f"{label} must be X,Y, got {raw!r}")
    try:
        x, y = (int(p) for p in parts)
    except ValueError as exc:
        raise UsageError(f"{label} coordinates must be integers, got {raw!r}") from exc
    return x, y


def _build_parser() -> _CliParser:
    parser = _CliParser(prog="vision", add_help=True)
    parser.add_argument(
        "--store-dir",
        default=os.environ.get("VISION_STORE_DIR", ".vision_store"),
        help="Workspace-local frame store directory",
    )
    parser.add_argument('--session', default=os.environ.get('VISION_SESSION_ID'))
    sub = parser.add_subparsers(dest="command", required=True)
    runtime = sub.add_parser('runtime', help='Deterministic workflow runtime')
    runtime.add_argument('runtime_action', choices=['qualify','run','inspect','list'])
    runtime.add_argument('--workflow', dest='workflow_id')
    runtime.add_argument('--device')
    runtime.add_argument('--profile', help='UTF-8 JSON Android profile file')
    runtime.add_argument('--binding', dest='binding_id')
    runtime.add_argument('--run-id')
    runtime.add_argument('--limit', type=int)
    runtime.add_argument('--after')
    runtime.add_argument('--json', action='store_true')
    workflow = sub.add_parser('workflow', help='Offline evidence-bound workflow builder')
    workflow.add_argument('workflow_action', choices=['candidates','build','inspect','validate','list'])
    workflow.add_argument('--session', dest='workflow_session')
    workflow.add_argument('--workflow', dest='workflow_id')
    workflow.add_argument('--plan', help='UTF-8 JSON plan file')
    workflow.add_argument('--limit', type=int)
    workflow.add_argument('--after')
    workflow.add_argument('--json', action='store_true')
    record = sub.add_parser('record', help='Persistent exploration recorder')
    record.add_argument('record_action', choices=['start','status','pause','resume','stop','list','inspect','summary','events','event','annotate','checkpoint','annotations','history','resume-context','latest-checkpoint'])
    record.add_argument('--session', dest='record_session')
    record.add_argument('--name')
    record.add_argument('--goal')
    record.add_argument('--device')
    record.add_argument('--event', dest='event_id')
    record.add_argument('--annotation', help='JSON object; do not include secrets')
    record.add_argument('--limit', type=int)
    record.add_argument('--after', type=int)
    record.add_argument('--operation')
    record.add_argument('--status')
    record.add_argument('--kind')
    record.add_argument('--json', action='store_true')

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

    p_click = sub.add_parser("click", help="Click a frame point or scoped reference")
    p_click.add_argument("--device", required=True, help="Device serial or 'desktop'")
    p_click.add_argument("--frame", default=None, help="Source frame ID")
    p_click.add_argument("--point", default=None, help="Frame-local point X,Y")
    p_click.add_argument("--ref", default=None, help="Scoped reference ID")
    p_click.add_argument("--max-age", type=float, default=None, help="Optional max age in seconds")
    p_click.add_argument("--json", action="store_true", help="Output JSON")

    p_swipe = sub.add_parser("swipe", help="Swipe between two points on a device")
    p_swipe.add_argument("--device", required=True, help="Device serial or 'desktop'")
    p_swipe.add_argument("--from", dest="from_point", required=True, help="Start point X,Y")
    p_swipe.add_argument("--to", dest="to_point", required=True, help="End point X,Y")
    p_swipe.add_argument("--duration", type=int, default=500, help="Swipe duration in ms")
    p_swipe.add_argument("--frame", default=None, help="Optional frame ID for local coordinates")
    p_swipe.add_argument("--json", action="store_true", help="Output JSON")

    p_type = sub.add_parser("type", help="Type text on a device")
    p_type.add_argument("--device", required=True, help="Device serial or 'desktop'")
    p_type.add_argument("--text", required=True, help="Text to type")
    p_type.add_argument("--json", action="store_true", help="Output JSON")

    p_key = sub.add_parser("key", help="Send a key event on a device")
    p_key.add_argument("--device", required=True, help="Device serial or 'desktop'")
    p_key.add_argument("--key", required=True, help="Key name or code")
    p_key.add_argument("--json", action="store_true", help="Output JSON")

    p_wait = sub.add_parser("wait", help="Wait for screen change, stability, or image match")
    p_wait.add_argument("--device", required=True, help="Device serial or 'desktop'")
    wait_mode = p_wait.add_mutually_exclusive_group(required=True)
    wait_mode.add_argument("--changed", action="store_true", help="Wait until screen/ROI changes")
    wait_mode.add_argument("--stable", action="store_true", help="Wait until screen/ROI stabilizes")
    wait_mode.add_argument("--image", dest="image_target", default=None, help="Wait until named asset appears")
    p_wait.add_argument("--baseline", default=None, help="Optional baseline frame ID for --changed")
    p_wait.add_argument("--region", default=None, help="Optional ROI X1,Y1,X2,Y2")
    p_wait.add_argument("--timeout", type=float, default=10.0, help="Timeout in seconds")
    p_wait.add_argument("--interval", type=float, default=0.5, help="Polling interval in seconds")
    p_wait.add_argument("--stable-duration", type=float, default=1.0, help="Required stable duration in seconds")
    p_wait.add_argument("--max-captures", type=int, default=100, help="Maximum captures before timeout")
    p_wait.add_argument("--pixel-tolerance", type=int, default=0, help="Per-channel pixel tolerance")
    p_wait.add_argument("--max-changed-ratio", type=float, default=0.0, help="Max changed ratio for --stable")
    p_wait.add_argument("--min-changed-ratio", type=float, default=0.01, help="Min changed ratio for --changed")
    p_wait.add_argument("--threshold", type=float, default=0.8, help="Match threshold for --image")
    p_wait.add_argument("--color-mode", default="gray", choices=["gray", "bgr"], help="Color mode for --image")
    p_wait.add_argument("--json", action="store_true", help="Output JSON")

    return parser


def _emit_json(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=True) + "\n")
    sys.stdout.flush()


def _run_cli(
    argv: Optional[List[str]] = None,
    *,
    service: Optional[ObservationService] = None,
    emit=_emit_json,
    parsed=None,
    mask_diagnostics=False,
) -> int:
    """Execute CLI with given argv and return exit code (0, 2, 3, or 4)."""
    _emit_json = emit
    parser = _build_parser()
    command_name: Optional[str] = None
    device_name: Optional[str] = None

    try:
        args = parsed or parser.parse_args(argv)
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

        if args.command in {"click", "swipe", "type", "key"}:
            actions = ActionService(
                store=obs.store,
                platform_factory=obs._platform_factory,
            )
            try:
                if args.command == "click":
                    point = _parse_point(args.point, label="Point") if args.point is not None else None
                    result = actions.click(
                        args.device,
                        frame_id=args.frame,
                        point=point,
                        ref_id=args.ref,
                        max_age_seconds=args.max_age,
                    )
                elif args.command == "swipe":
                    start = _parse_point(args.from_point, label="From")
                    end = _parse_point(args.to_point, label="To")
                    result = actions.swipe(
                        args.device,
                        start=start,
                        end=end,
                        duration_ms=args.duration,
                        frame_id=args.frame,
                    )
                elif args.command == "type":
                    result = actions.type_text(args.device, text=args.text)
                else:
                    result = actions.press_key(args.device, key=args.key)
            except (InvalidFrameIdError, InvalidRefIdError, ValueError) as exc:
                if isinstance(exc, (DeviceMismatchError, StaleRefError, OutOfBoundsError)):
                    code = (
                        "DEVICE_MISMATCH"
                        if isinstance(exc, DeviceMismatchError)
                        else "STALE_REF"
                        if isinstance(exc, StaleRefError)
                        else "OUT_OF_BOUNDS"
                    )
                    raise OperationError(code=code, message=str(exc), exit_code=3) from exc
                raise UsageError(str(exc)) from exc
            except FrameNotFoundError as exc:
                raise OperationError(code="FRAME_NOT_FOUND", message=str(exc), exit_code=3) from exc
            except RefNotFoundError as exc:
                raise OperationError(code="REF_NOT_FOUND", message=str(exc), exit_code=3) from exc

            _emit_json(
                {
                    "ok": True,
                    "command": args.command,
                    "device": args.device,
                    "result": result,
                }
            )
            return 0

        if args.command == "wait":
            waits = WaitService(
                store=obs.store,
                platform_factory=obs._platform_factory,
            )
            region = _parse_region(args.region) if args.region is not None else None
            try:
                if args.changed:
                    result = waits.wait_changed(
                        args.device,
                        baseline_frame_id=args.baseline,
                        region=region,
                        timeout=args.timeout,
                        interval=args.interval,
                        max_captures=args.max_captures,
                        pixel_tolerance=args.pixel_tolerance,
                        min_changed_ratio=args.min_changed_ratio,
                    )
                elif args.stable:
                    result = waits.wait_stable(
                        args.device,
                        region=region,
                        timeout=args.timeout,
                        interval=args.interval,
                        stable_duration=args.stable_duration,
                        max_captures=args.max_captures,
                        pixel_tolerance=args.pixel_tolerance,
                        max_changed_ratio=args.max_changed_ratio,
                    )
                else:
                    result = waits.wait_image(
                        args.device,
                        target_name=args.image_target,
                        region=region,
                        timeout=args.timeout,
                        interval=args.interval,
                        max_captures=args.max_captures,
                        threshold=args.threshold,
                        color_mode=args.color_mode,
                    )
            except (InvalidAssetNameError, InvalidFrameIdError, ValueError) as exc:
                if isinstance(exc, (DeviceMismatchError, OutOfBoundsError)):
                    code = "DEVICE_MISMATCH" if isinstance(exc, DeviceMismatchError) else "OUT_OF_BOUNDS"
                    raise OperationError(code=code, message=str(exc), exit_code=3) from exc
                raise UsageError(str(exc)) from exc
            except FrameNotFoundError as exc:
                raise OperationError(code="FRAME_NOT_FOUND", message=str(exc), exit_code=3) from exc
            except AssetNotFoundError as exc:
                raise OperationError(code="ASSET_NOT_FOUND", message=str(exc), exit_code=3) from exc

            _emit_json(
                {
                    "ok": True,
                    "command": "wait",
                    "device": args.device,
                    "result": result,
                }
            )
            return 0

        raise UsageError(f"Unknown command: {args.command}")

    except OperationError as exc:
        sys.stderr.write(f"[{exc.code}] " + ("[REDACTED]\n" if mask_diagnostics else f"{exc.message}\n"))
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
        sys.stderr.write("[INTERNAL_ERROR] " + ("[REDACTED]\n" if mask_diagnostics else f"{exc}\n"))
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


def run_cli(argv=None, *, service=None):
    try:
        args = _build_parser().parse_args(argv)
    except UsageError:
        return _run_cli(argv, service=service)
    try:
        store = service.store if service else FrameStore(Path(args.store_dir))
        if args.command == 'runtime':
            params = {k:v for k,v in vars(args).items() if k in ('workflow_id','device','profile','binding_id','run_id','limit','after') and v is not None}
            if 'profile' in params: params['profile'] = json.loads(Path(params['profile']).read_text(encoding='utf-8-sig'))
            result = WorkflowRuntime(store, observation=service).query(args.runtime_action, **params)
            _emit_json({'ok':True,'result':result})
            return 3 if args.runtime_action=='run' and result['status']!='completed' else 0
        if args.command == 'workflow':
            params = {}
            if args.workflow_session: params['session_id'] = args.workflow_session
            if args.workflow_id: params['workflow_id'] = args.workflow_id
            if args.plan: params['plan'] = json.loads(Path(args.plan).read_text(encoding='utf-8-sig'))
            if args.limit is not None: params['limit'] = args.limit
            if args.after is not None: params['after'] = int(args.after) if args.workflow_action=='candidates' else args.after
            result = WorkflowBuilder(store).query(args.workflow_action, **params)
            _emit_json({'ok':True,'result':result})
            return 0
        if args.command == 'record':
            data = {k: v for k, v in vars(args).items() if k in ('name','goal','device','event_id','annotation','limit','after','operation','status','kind') and v is not None}
            if 'annotation' in data:
                data['annotation'] = json.loads(data['annotation'])
            result = Recorder(store).query(args.record_action, session_id=args.record_session or args.session, **data)
            _emit_json({'ok': True, 'result': result})
            return 0
        operation = 'assets_register' if args.command == 'assets' and args.assets_command == 'register' else args.command
        if args.session is not None and operation in OPERATIONS:
            inputs = {k:v for k,v in vars(args).items() if k not in ('store_dir','session','command','json','assets_command')}
            receipt = []
            codes = []
            def invoke():
                codes.append(_run_cli(argv, service=service, parsed=args, emit=receipt.append, mask_diagnostics=operation=="type"))
                return receipt[0]
            result = Recorder(store).execute(args.session, operation, inputs, invoke)
            _emit_json(result)
            return codes[0] if result.get('ok') and codes else (codes[0] if codes and codes[0] else 3)
        with workspace_lock(store):
            return _run_cli(argv, service=service, parsed=args)
    except Exception as exc:
        _emit_json({'ok':False,'error':{'code':getattr(exc,'code','RUNTIME_ERROR') if args.command == 'runtime' else ('WORKFLOW_ERROR' if args.command == 'workflow' else 'RECORDER_ERROR'),'message':str(exc)}})
        return 3


def main() -> None:
    raise SystemExit(run_cli())


if __name__ == "__main__":
    main()
