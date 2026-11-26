"""Tests for MCP stdio JSON-RPC 2.0 adapter and image delivery."""

from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, List, Optional

import cv2
import numpy as np
import pytest

from vision_app.mcp_server import MCP_PROTOCOL_VERSION, VisionMcpServer


class _FakePlatform:
    def __init__(self, image: Optional[np.ndarray] = None) -> None:
        self._image = image
        self.clicks: List[tuple[int, int]] = []

    def get_devices(self) -> List[str]:
        return ["127.0.0.1:16480"]

    def get_capabilities(self) -> dict[str, Any]:
        return {"platform": "adb", "snapshot": True, "click": True}

    def snapshot(self) -> Optional[np.ndarray]:
        return None if self._image is None else self._image.copy()

    def click(self, x: int, y: int) -> bool:
        self.clicks.append((x, y))
        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration_ms: int = 300) -> bool:
        return True

    def input_text(self, text: str) -> bool:
        return True

    def key_event(self, key: str) -> bool:
        return True


def _sample_bgr() -> np.ndarray:
    img = np.zeros((200, 300, 3), dtype=np.uint8)
    img[40:90, 60:140] = (20, 180, 240)
    return img


def test_mcp_initialize_and_tools_list(tmp_path: Path) -> None:
    server = VisionMcpServer(store_dir=tmp_path / "store")
    init_resp = server.handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize"})
    assert init_resp is not None
    assert init_resp["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert "tools" in init_resp["result"]["capabilities"]

    notif_resp = server.handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"})
    assert notif_resp is None

    list_resp = server.handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    assert list_resp is not None
    tools = list_resp["result"]["tools"]
    names = {t["name"] for t in tools}
    assert {"vision_snapshot", "vision_crop", "vision_resize", "vision_find", "vision_click"} <= names
    for tool in tools:
        assert "inputSchema" in tool
        assert tool["inputSchema"]["type"] == "object"


def test_mcp_snapshot_crop_resize_deliver_png_bytes_and_metadata(tmp_path: Path) -> None:
    fake = _FakePlatform(_sample_bgr())
    server = VisionMcpServer(store_dir=tmp_path / "store", platform_factory=lambda _d: fake)

    snap_resp = server.call_tool("vision_snapshot", {"device": "127.0.0.1:16480"})
    assert snap_resp["isError"] is False
    content = snap_resp["content"]
    assert content[0]["type"] == "image"
    assert content[0]["mimeType"] == "image/png"
    raw_png = base64.b64decode(content[0]["data"])
    assert raw_png.startswith(b"\x89PNG\r\n\x1a\n")
    decoded = cv2.imdecode(np.frombuffer(raw_png, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert decoded is not None
    assert decoded.shape == (200, 300, 3)

    meta = json.loads(content[1]["text"])
    assert meta["ok"] is True
    assert meta["device"] == "127.0.0.1:16480"
    frame_id = meta["frame"]["frame_id"]

    crop_resp = server.call_tool(
        "vision_crop", {"frame_id": frame_id, "region": [60, 40, 140, 90]}
    )
    assert crop_resp["isError"] is False
    assert crop_resp["content"][0]["mimeType"] == "image/png"
    crop_png = base64.b64decode(crop_resp["content"][0]["data"])
    crop_img = cv2.imdecode(np.frombuffer(crop_png, dtype=np.uint8), cv2.IMREAD_COLOR)
    assert crop_img is not None
    assert crop_img.shape == (50, 80, 3)
    crop_meta = json.loads(crop_resp["content"][1]["text"])
    assert crop_meta["frame"]["transform"]["offset_x"] == 60
    assert crop_meta["frame"]["transform"]["offset_y"] == 40

    resize_resp = server.call_tool(
        "vision_resize", {"frame_id": crop_meta["frame"]["frame_id"], "scale": 0.5}
    )
    assert resize_resp["isError"] is False
    resize_meta = json.loads(resize_resp["content"][1]["text"])
    assert resize_meta["frame"]["width"] == 40
    assert resize_meta["frame"]["height"] == 25


def test_mcp_scoped_errors(tmp_path: Path) -> None:
    fake = _FakePlatform(_sample_bgr())
    server = VisionMcpServer(store_dir=tmp_path / "store", platform_factory=lambda _d: fake)

    unknown = server.call_tool("vision_unknown", {})
    assert unknown["isError"] is True
    err = json.loads(unknown["content"][0]["text"])
    assert err["ok"] is False
    assert err["error"]["code"] == "INVALID_USAGE"

    snap = server.call_tool("vision_snapshot", {"device": "127.0.0.1:16480"})
    frame_id = json.loads(snap["content"][1]["text"])["frame"]["frame_id"]

    oob = server.call_tool("vision_crop", {"frame_id": frame_id, "region": [0, 0, 999, 999]})
    assert oob["isError"] is True
    assert json.loads(oob["content"][0]["text"])["error"]["code"] == "FRAME_ERROR"

    mismatch = server.call_tool(
        "vision_click", {"device": "other-device", "frame_id": frame_id, "point": [10, 10]}
    )
    assert mismatch["isError"] is True
    assert json.loads(mismatch["content"][0]["text"])["error"]["code"] == "DEVICE_MISMATCH"


def test_mcp_stdio_subprocess_roundtrip(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[2]
    env = os.environ.copy()
    env["PYTHONPATH"] = f"{repo_root / 'core'}{os.pathsep}{repo_root}"
    env["VISION_STORE_DIR"] = str(tmp_path / "store")

    requests = "\n".join(
        [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": 3,
                    "method": "tools/call",
                    "params": {"name": "vision_devices", "arguments": {}},
                }
            ),
        ]
    ) + "\n"

    proc = subprocess.run(
        [sys.executable, "-m", "vision_app.mcp_server"],
        input=requests,
        text=True,
        capture_output=True,
        env=env,
        timeout=15,
        check=True,
    )
    lines = [json.loads(line) for line in proc.stdout.strip().splitlines() if line.strip()]
    assert [m["id"] for m in lines] == [1, 2, 3]
    assert lines[0]["result"]["protocolVersion"] == MCP_PROTOCOL_VERSION
    assert any(t["name"] == "vision_snapshot" for t in lines[1]["result"]["tools"])
    devices_payload = json.loads(lines[2]["result"]["content"][0]["text"])
    assert devices_payload["ok"] is True
    assert any(d["device_id"] == "desktop" for d in devices_payload["devices"])
