"""MCP (Model Context Protocol) stdio JSON-RPC 2.0 adapter for vision_app.

Reuses the shared application services (ObservationService, MatchingService,
ActionService, WaitService) without duplicating orchestration. Image-producing
tools return standard MCP ImageContent (``type: "image"``, ``mimeType: "image/png"``,
base64-encoded PNG bytes) alongside structured metadata and transform info.
"""

from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO, Tuple

from vision_app.actions import ActionService
from vision_app.assets import (
    AssetNotFoundError,
    AssetRegistry,
    InvalidAssetNameError,
    InvalidRefIdError,
    MatchingService,
    RefNotFoundError,
    RefRegistry,
    StaleRefError,
)
from vision_app.observation import ObservationService, OperationError, UsageError
from vision_app.store import (
    DeviceMismatchError,
    FrameNotFoundError,
    FrameStore,
    InvalidFrameIdError,
    OutOfBoundsError,
    StoreError,
)
from vision_app.waits import WaitService
from vision_app.recorder import Recorder, OPERATIONS, workspace_lock, record_tool_definitions
from vision_app.workflow import WorkflowBuilder, WorkflowError, workflow_tool_definitions
from vision_app.runtime import WorkflowRuntime, RuntimeFault, runtime_tool_definitions

MCP_PROTOCOL_VERSION = "2024-11-05"
SERVER_NAME = "vision-mcp"
SERVER_VERSION = "0.1.0"


def _error_payload(exc: Exception) -> Dict[str, Any]:
    if isinstance(exc, RuntimeFault):
        return {'code':exc.code,'message':str(exc),'details':exc.details,'retryable':False}
    if isinstance(exc, WorkflowError):
        return {"code":"WORKFLOW_ERROR","message":str(exc),"retryable":False}
    if isinstance(exc, UsageError):
        return {"code": exc.code, "message": exc.message, "retryable": False}
    if isinstance(exc, OperationError):
        return {
            "code": exc.code,
            "message": exc.message,
            "retryable": exc.retryable,
        }
    if isinstance(exc, InvalidFrameIdError):
        return {"code": "INVALID_FRAME_ID", "message": str(exc), "retryable": False}
    if isinstance(exc, FrameNotFoundError):
        return {"code": "FRAME_NOT_FOUND", "message": str(exc), "retryable": False}
    if isinstance(exc, OutOfBoundsError):
        return {"code": "OUT_OF_BOUNDS", "message": str(exc), "retryable": False}
    if isinstance(exc, DeviceMismatchError):
        return {"code": "DEVICE_MISMATCH", "message": str(exc), "retryable": False}
    if isinstance(exc, InvalidAssetNameError):
        return {"code": "INVALID_ASSET_NAME", "message": str(exc), "retryable": False}
    if isinstance(exc, AssetNotFoundError):
        return {"code": "ASSET_NOT_FOUND", "message": str(exc), "retryable": False}
    if isinstance(exc, InvalidRefIdError):
        return {"code": "INVALID_REF_ID", "message": str(exc), "retryable": False}
    if isinstance(exc, RefNotFoundError):
        return {"code": "REF_NOT_FOUND", "message": str(exc), "retryable": False}
    if isinstance(exc, StaleRefError):
        return {"code": "STALE_REF", "message": str(exc), "retryable": False}
    if isinstance(exc, StoreError):
        return {"code": "STORE_ERROR", "message": str(exc), "retryable": False}
    return {"code": "INTERNAL_ERROR", "message": str(exc), "retryable": False}


def _parse_region_arg(raw: Any) -> Optional[Tuple[int, int, int, int]]:
    if raw is None:
        return None
    if isinstance(raw, (list, tuple)) and len(raw) == 4:
        try:
            return (int(raw[0]), int(raw[1]), int(raw[2]), int(raw[3]))
        except (TypeError, ValueError) as exc:
            raise UsageError(f"region must contain 4 integers, got {raw!r}") from exc
    raise UsageError(f"region must be [x1, y1, x2, y2], got {raw!r}")


def _parse_point_arg(raw: Any, label: str = "point") -> Tuple[int, int]:
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            return (int(raw[0]), int(raw[1]))
        except (TypeError, ValueError) as exc:
            raise UsageError(f"{label} must contain 2 integers, got {raw!r}") from exc
    raise UsageError(f"{label} must be [x, y], got {raw!r}")


def _tool_definitions() -> List[Dict[str, Any]]:
    region_schema = {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 4,
        "maxItems": 4,
        "description": "Half-open region [x1, y1, x2, y2]",
    }
    point_schema = {
        "type": "array",
        "items": {"type": "integer"},
        "minItems": 2,
        "maxItems": 2,
        "description": "2D integer coordinates [x, y]",
    }
    definitions = [
        {
            "name": "vision_devices",
            "description": "List available ADB devices and the local desktop target.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "vision_capabilities",
            "description": "Show capabilities for a target device ('desktop' or ADB serial).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "default": "adb"},
                },
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_snapshot",
            "description": "Capture a screenshot from a device and return PNG image content + metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device": {"type": "string", "description": "Device serial or 'desktop'"},
                    "region": region_schema,
                },
                "required": ["device"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_crop",
            "description": "Crop an existing frame and return PNG image content + metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "frame_id": {"type": "string"},
                    "region": region_schema,
                },
                "required": ["frame_id", "region"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_resize",
            "description": "Resize an existing frame by scale and return PNG image content + metadata.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "frame_id": {"type": "string"},
                    "scale": {"type": "number", "exclusiveMinimum": 0},
                },
                "required": ["frame_id", "scale"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_assets_register",
            "description": "Register a named template asset from a frame (and optional region).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "frame_id": {"type": "string"},
                    "region": region_schema,
                },
                "required": ["name", "frame_id"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_assets_list",
            "description": "List registered named assets.",
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "vision_find",
            "description": "Find a registered asset in a frame and return scoped references.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "frame_id": {"type": "string"},
                    "target": {"type": "string"},
                    "all": {"type": "boolean", "default": False},
                    "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.8},
                },
                "required": ["frame_id", "target"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_click",
            "description": "Click a frame-local point or a scoped reference on a device.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device": {"type": "string"},
                    "frame_id": {"type": "string"},
                    "point": point_schema,
                    "ref": {"type": "string"},
                    "max_age_seconds": {"type": "number", "exclusiveMinimum": 0},
                },
                "required": ["device"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_swipe",
            "description": "Swipe between two points on a device.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device": {"type": "string"},
                    "from_point": point_schema,
                    "to_point": point_schema,
                    "duration_ms": {"type": "integer", "minimum": 1, "default": 300},
                },
                "required": ["device", "from_point", "to_point"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_type",
            "description": "Type text on a device.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device": {"type": "string"},
                    "text": {"type": "string"},
                },
                "required": ["device", "text"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_key",
            "description": "Send a key event on a device.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device": {"type": "string"},
                    "key": {"type": "string"},
                },
                "required": ["device", "key"],
                "additionalProperties": False,
            },
        },
        {
            "name": "vision_wait",
            "description": "Wait for screen change, stability, or a target asset.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "device": {"type": "string"},
                    "mode": {"type": "string", "enum": ["changed", "stable", "image"]},
                    "baseline_frame_id": {"type": "string"},
                    "target": {"type": "string"},
                    "region": region_schema,
                    "timeout": {"type": "number", "exclusiveMinimum": 0, "default": 10.0},
                    "poll_interval": {"type": "number", "exclusiveMinimum": 0, "default": 0.2},
                    "threshold": {"type": "number", "minimum": 0, "maximum": 1, "default": 0.8},
                },
                "required": ["device", "mode"],
                "additionalProperties": False,
            },
        },
    ]
    for tool in definitions:
        if tool['name'].removeprefix('vision_') in OPERATIONS:
            tool['inputSchema']['properties']['session_id'] = {'type':'string', 'description':'Explicit active recording session'}
    return definitions + record_tool_definitions() + workflow_tool_definitions() + runtime_tool_definitions()


class VisionMcpServer:
    """MCP server wrapping the shared vision_app application services."""

    def __init__(
        self,
        store_dir: str | Path = ".vision_store",
        *,
        platform_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        self.store = FrameStore(store_dir)
        self.obs = ObservationService(store=self.store, platform_factory=platform_factory)
        self.assets = AssetRegistry(self.store.store_dir)
        self.refs = RefRegistry(self.store.store_dir)
        self.matcher = MatchingService(store=self.store, assets=self.assets, refs=self.refs)
        self.actions = ActionService(
            self.store, ref_registry=self.refs, platform_factory=platform_factory
        )
        self.waits = WaitService(
            self.store,
            asset_registry=self.assets,
            platform_factory=platform_factory,
        )

    def _image_tool_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        artifact = payload.get("artifact") or {}
        path_str = artifact.get("path")
        if not path_str:
            raise OperationError("MISSING_ARTIFACT", "Image tool did not produce an artifact path")
        image_path = Path(path_str)
        if not image_path.exists():
            raise OperationError("MISSING_ARTIFACT", f"Artifact file not found: {image_path}")
        png_bytes = image_path.read_bytes()
        encoded = base64.b64encode(png_bytes).decode("ascii")
        return {
            "content": [
                {
                    "type": "image",
                    "data": encoded,
                    "mimeType": "image/png",
                },
                {
                    "type": "text",
                    "text": json.dumps(payload),
                },
            ],
            "isError": False,
        }

    def _text_tool_result(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "content": [{"type": "text", "text": json.dumps(payload)}],
            "isError": False,
        }

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        args = dict(arguments or {})
        try:
            if name.startswith('vision_runtime_'):
                action = name.removeprefix('vision_runtime_')
                result = WorkflowRuntime(self.store, observation=self.obs, actions=self.actions).query(action, **args)
                return self._text_tool_result({'ok':True,'result':result})
            if name.startswith('vision_workflow_'):
                action = name.removeprefix('vision_workflow_')
                return self._text_tool_result({'ok':True,'result':WorkflowBuilder(self.store).query(action, **args)})
            if name.startswith('vision_record_'):
                action = name.removeprefix('vision_record_').replace('_','-')
                result = Recorder(self.store).query(action, **args)
                return self._text_tool_result({'ok':True,'result':result})
            operation = name.removeprefix('vision_')
            sid = args.pop('session_id', None)
            if sid is not None and operation in OPERATIONS:
                original = []
                def invoke():
                    response = self._call_tool(name,args)
                    original.append(response)
                    return json.loads(next(c['text'] for c in response['content'] if c['type']=='text'))
                receipt = Recorder(self.store).execute(sid, operation, args, invoke)
                result = self._text_tool_result(receipt)
                result['isError'] = not receipt.get('ok',False)
                if not result['isError'] and original:
                    result['content'] = [c for c in original[0]['content'] if c['type']=='image'] + result['content']
                return result
            with workspace_lock(self.store):
                return self._call_tool(name,args)
        except Exception as exc:
            return {'content':[{'type':'text','text':json.dumps({'ok':False,'error':_error_payload(exc)})}],'isError':True}

    def _call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        args = arguments or {}
        try:
            if name == "vision_devices":
                devices = self.obs.devices()
                return self._text_tool_result({"ok": True, "devices": devices})

            if name == "vision_capabilities":
                device = str(args.get("device", "adb"))
                caps = self.obs.capabilities(device)
                return self._text_tool_result({"ok": True, "device": device, "capabilities": caps})

            if name == "vision_snapshot":
                device = args.get("device")
                if not device:
                    raise UsageError("device is required")
                region = _parse_region_arg(args.get("region"))
                res = self.obs.snapshot(str(device), region=region)
                return self._image_tool_result({"ok": True, "device": str(device), **res})

            if name == "vision_crop":
                frame_id = args.get("frame_id")
                if not frame_id:
                    raise UsageError("frame_id is required")
                region = _parse_region_arg(args.get("region"))
                if region is None:
                    raise UsageError("region is required")
                res = self.obs.crop(str(frame_id), region)
                return self._image_tool_result({"ok": True, **res})

            if name == "vision_resize":
                frame_id = args.get("frame_id")
                scale = args.get("scale")
                if not frame_id or scale is None:
                    raise UsageError("frame_id and scale are required")
                res = self.obs.resize(str(frame_id), float(scale))
                return self._image_tool_result({"ok": True, **res})

            if name == "vision_assets_register":
                asset_name = args.get("name")
                frame_id = args.get("frame_id")
                if not asset_name or not frame_id:
                    raise UsageError("name and frame_id are required")
                region = _parse_region_arg(args.get("region"))
                res = self.assets.register_from_frame(
                    str(asset_name),
                    self.store,
                    str(frame_id),
                    region=region,
                )
                return self._text_tool_result({"ok": True, "asset": res.to_dict()})

            if name == "vision_assets_list":
                items = self.assets.list_assets()
                return self._text_tool_result({"ok": True, "assets": [item.to_dict() for item in items]})

            if name == "vision_find":
                frame_id = args.get("frame_id")
                target = args.get("target")
                if not frame_id or not target:
                    raise UsageError("frame_id and target are required")
                res = self.matcher.find(
                    str(frame_id),
                    str(target),
                    find_all=bool(args.get("all", False)),
                    threshold=float(args.get("threshold", 0.8)),
                )
                return self._text_tool_result({"ok": True, **res})

            if name == "vision_click":
                device = args.get("device")
                if not device:
                    raise UsageError("device is required")
                point = (
                    _parse_point_arg(args["point"], "point")
                    if args.get("point") is not None
                    else None
                )
                res = self.actions.click(
                    str(device),
                    frame_id=args.get("frame_id"),
                    point=point,
                    ref_id=args.get("ref"),
                    max_age_seconds=args.get("max_age_seconds"),
                )
                return self._text_tool_result({"ok": True, **res})

            if name == "vision_swipe":
                device = args.get("device")
                if not device:
                    raise UsageError("device is required")
                from_pt = _parse_point_arg(args.get("from_point"), "from_point")
                to_pt = _parse_point_arg(args.get("to_point"), "to_point")
                res = self.actions.swipe(
                    str(device),
                    start=from_pt,
                    end=to_pt,
                    duration_ms=int(args.get("duration_ms", 300)),
                )
                return self._text_tool_result({"ok": True, **res})

            if name == "vision_type":
                device = args.get("device")
                text = args.get("text")
                if not device or text is None:
                    raise UsageError("device and text are required")
                res = self.actions.type_text(str(device), text=str(text))
                return self._text_tool_result({"ok": True, **res})

            if name == "vision_key":
                device = args.get("device")
                key = args.get("key")
                if not device or not key:
                    raise UsageError("device and key are required")
                res = self.actions.press_key(str(device), key=str(key))
                return self._text_tool_result({"ok": True, **res})

            if name == "vision_wait":
                device = args.get("device")
                mode = args.get("mode")
                if not device or not mode:
                    raise UsageError("device and mode are required")
                region = _parse_region_arg(args.get("region"))
                timeout = float(args.get("timeout", 10.0))
                poll_interval = float(args.get("poll_interval", 0.2))
                if mode == "changed":
                    res = self.waits.wait_changed(
                        str(device), baseline_frame_id=args.get("baseline_frame_id"),
                        region=region, timeout=timeout, interval=poll_interval
                    )
                elif mode == "stable":
                    res = self.waits.wait_stable(
                        str(device), region=region, timeout=timeout, interval=poll_interval
                    )
                elif mode == "image":
                    target = args.get("target")
                    if not target:
                        raise UsageError("target is required when mode='image'")
                    res = self.waits.wait_image(
                        str(device),
                        target_name=str(target),
                        region=region,
                        timeout=timeout,
                        interval=poll_interval,
                        threshold=float(args.get("threshold", 0.8)),
                    )
                else:
                    raise UsageError(f"Unsupported wait mode: {mode!r}")
                return self._text_tool_result({"ok": True, **res})

            raise UsageError(f"Unknown tool: {name!r}")
        except Exception as exc:
            return {
                "content": [
                    {
                        "type": "text",
                        "text": json.dumps({"ok": False, "error": _error_payload(exc)}),
                    }
                ],
                "isError": True,
            }

    def handle_request(self, request: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        req_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        # Notifications have no id and expect no response.
        if req_id is None and isinstance(method, str) and method.startswith("notifications/"):
            return None

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": MCP_PROTOCOL_VERSION,
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
                },
            }

        if method == "ping":
            return {"jsonrpc": "2.0", "id": req_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {"tools": _tool_definitions()},
            }

        if method == "tools/call":
            tool_name = params.get("name")
            if not isinstance(tool_name, str) or not tool_name:
                return {
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "error": {"code": -32602, "message": "Missing tool name"},
                }
            result = self.call_tool(tool_name, params.get("arguments"))
            return {"jsonrpc": "2.0", "id": req_id, "result": result}

        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def serve_stdio(
        self,
        stdin: Optional[TextIO] = None,
        stdout: Optional[TextIO] = None,
    ) -> None:
        in_stream = stdin or sys.stdin
        out_stream = stdout or sys.stdout
        for raw_line in in_stream:
            line = raw_line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as exc:
                err_resp = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {exc}"},
                }
                out_stream.write(json.dumps(err_resp) + "\n")
                out_stream.flush()
                continue
            resp = self.handle_request(msg)
            if resp is not None:
                out_stream.write(json.dumps(resp) + "\n")
                out_stream.flush()


def main(argv: Optional[Sequence[str]] = None) -> int:
    # MCP stdio is UTF-8 regardless of Windows console/ACP defaults.
    sys.stdin.reconfigure(encoding="utf-8", errors="strict")
    sys.stdout.reconfigure(encoding="utf-8", errors="strict")
    store_dir = os.environ.get("VISION_STORE_DIR", ".vision_store")
    server = VisionMcpServer(store_dir=store_dir)
    server.serve_stdio()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
