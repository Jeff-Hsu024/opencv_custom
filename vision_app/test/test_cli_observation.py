"""Unit and subprocess tests for CLI-02 observation CLI and export."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np
import pytest

from vision_app.observation import ObservationService, OperationError, UsageError
from vision_app.store import FrameStore


class _FakePlatform:
    def __init__(self, image: np.ndarray, devices: list[str] | None = None) -> None:
        self._image = image
        self._devices = devices or ["127.0.0.1:16480"]
        self.snapshot_calls = 0

    def get_devices(self) -> list[str]:
        return list(self._devices)

    def capabilities(self) -> dict:
        return {"snapshot": True, "click": True, "swipe": True}

    def snapshot(self) -> np.ndarray:
        self.snapshot_calls += 1
        return self._image.copy()


def _make_image(width: int = 720, height: int = 1280) -> np.ndarray:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :, 0] = 40
    img[:, :, 1] = 120
    img[:, :, 2] = 200
    return img


def test_devices_and_capabilities(tmp_path: Path) -> None:
    fake = _FakePlatform(_make_image(100, 100), devices=["127.0.0.1:16480"])
    svc = ObservationService(
        store=FrameStore(tmp_path / "store"),
        platform_factory=lambda _dev: fake,
    )
    devs = svc.devices()
    assert {"device_id": "127.0.0.1:16480", "platform": "adb"} in devs
    assert {"device_id": "desktop", "platform": "desktop"} in devs

    caps = svc.capabilities("127.0.0.1:16480")
    assert caps["device_id"] == "127.0.0.1:16480"
    assert caps["capabilities"]["snapshot"] is True


def test_snapshot_single_capture_with_region_and_export(tmp_path: Path) -> None:
    fake = _FakePlatform(_make_image(720, 1280))
    store = FrameStore(tmp_path / "store")
    svc = ObservationService(store=store, platform_factory=lambda _dev: fake)

    out_png = tmp_path / "out" / "snap.png"
    res = svc.snapshot("127.0.0.1:16480", region=(100, 300, 400, 500), out=str(out_png))

    assert fake.snapshot_calls == 1
    assert res["frame"]["width"] == 300
    assert res["frame"]["height"] == 200
    assert res["frame"]["source_width"] == 720
    assert res["frame"]["source_height"] == 1280
    assert out_png.exists()

    loaded = cv2.imread(str(out_png))
    assert loaded is not None
    assert loaded.shape == (200, 300, 3)


def test_crop_and_resize_compose_without_recapture(tmp_path: Path) -> None:
    fake = _FakePlatform(_make_image(720, 1280))
    store = FrameStore(tmp_path / "store")
    svc = ObservationService(store=store, platform_factory=lambda _dev: fake)

    snap = svc.snapshot("127.0.0.1:16480")
    assert fake.snapshot_calls == 1

    cropped = svc.crop(snap["frame"]["frame_id"], (100, 300, 400, 500))
    assert cropped["frame"]["width"] == 300
    assert cropped["frame"]["height"] == 200

    resized = svc.resize(cropped["frame"]["frame_id"], 0.5)
    assert resized["frame"]["width"] == 150
    assert resized["frame"]["height"] == 100
    assert fake.snapshot_calls == 1

    mapped = store.map_point(resized["frame"]["frame_id"], 30, 40)
    assert mapped == (160, 380)


def test_timeout_and_usage_errors(tmp_path: Path) -> None:
    class _TimeoutPlatform(_FakePlatform):
        def snapshot(self) -> np.ndarray:
            raise TimeoutError("adb timed out")

    svc = ObservationService(
        store=FrameStore(tmp_path / "store"),
        platform_factory=lambda _dev: _TimeoutPlatform(_make_image(10, 10)),
    )
    with pytest.raises(OperationError) as exc_info:
        svc.snapshot("127.0.0.1:16480")
    assert exc_info.value.exit_code == 4

    with pytest.raises(UsageError) as usage_info:
        svc.resize("missing", 0.0)
    assert usage_info.value.exit_code == 2


def _run_cli_subprocess(args: list[str], store_dir: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = f"{repo_root / 'core'}{os.pathsep}{repo_root}"
    env["VISION_STORE_DIR"] = str(store_dir)
    return subprocess.run(
        [sys.executable, "-m", "vision_app.cli", *args],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )


def test_cli_subprocess_devices_capabilities_and_usage_exit_2(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"

    proc_dev = _run_cli_subprocess(["devices", "--json"], store_dir)
    assert proc_dev.returncode == 0
    payload_dev = json.loads(proc_dev.stdout)
    assert payload_dev["ok"] is True
    assert payload_dev["command"] == "devices"
    assert any(d["device_id"] == "desktop" for d in payload_dev["result"]["devices"])

    proc_cap = _run_cli_subprocess(["capabilities", "--device", "desktop", "--json"], store_dir)
    assert proc_cap.returncode == 0
    payload_cap = json.loads(proc_cap.stdout)
    assert payload_cap["ok"] is True
    assert payload_cap["device"] == "desktop"

    proc_bad = _run_cli_subprocess(["snapshot"], store_dir)
    assert proc_bad.returncode == 2
    payload_bad = json.loads(proc_bad.stdout)
    assert payload_bad["ok"] is False
    assert payload_bad["error"]["code"] == "INVALID_USAGE"
    assert proc_bad.stderr.strip() != ""


def test_cli_subprocess_crop_and_resize_export_png(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FrameStore(store_dir)
    rec = store.save_frame(_make_image(720, 1280), "127.0.0.1:16480")

    crop_out = tmp_path / "exports" / "crop.png"
    proc_crop = _run_cli_subprocess(
        ["crop", "--frame", rec.frame_id, "--region", "100,300,400,500", "--out", str(crop_out), "--json"],
        store_dir,
    )
    assert proc_crop.returncode == 0
    crop_json = json.loads(proc_crop.stdout)
    assert crop_json["ok"] is True
    assert crop_json["artifact"]["width"] == 300
    assert crop_json["artifact"]["height"] == 200
    assert crop_out.exists()
    assert cv2.imread(str(crop_out)).shape == (200, 300, 3)

    resize_out = tmp_path / "exports" / "resize.png"
    proc_resize = _run_cli_subprocess(
        ["resize", "--frame", crop_json["result"]["frame_id"], "--scale", "0.5", "--out", str(resize_out), "--json"],
        store_dir,
    )
    assert proc_resize.returncode == 0
    resize_json = json.loads(proc_resize.stdout)
    assert resize_json["ok"] is True
    assert resize_json["artifact"]["width"] == 150
    assert resize_json["artifact"]["height"] == 100
    assert resize_out.exists()
    assert cv2.imread(str(resize_out)).shape == (100, 150, 3)
