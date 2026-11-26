"""Tests for CLI-04 action refs, coordinate mapping, validation, receipts, and timeouts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, List, Tuple

import numpy as np
import pytest

from vision_app.actions import ActionService
from vision_app.assets import AssetRegistry, MatchingService, RefRegistry, ScopedRef, StaleRefError
from vision_app.cli import run_cli
from vision_app.observation import ObservationService, OperationError
from vision_app.store import DeviceMismatchError, FrameStore, OutOfBoundsError


class _RecordingPlatform:
    def __init__(self, image: np.ndarray, *, fail_action: bool = False, timeout_exc: Exception | None = None) -> None:
        self._image = image
        self._fail_action = fail_action
        self._timeout_exc = timeout_exc
        self.calls: List[Tuple[str, Tuple[Any, ...]]] = []

    def snapshot(self) -> np.ndarray:
        return self._image.copy()

    def click(self, x: int, y: int) -> bool:
        self.calls.append(("click", (x, y)))
        if self._timeout_exc is not None:
            raise self._timeout_exc
        return not self._fail_action

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> bool:
        self.calls.append(("swipe", (x1, y1, x2, y2, duration)))
        if self._timeout_exc is not None:
            raise self._timeout_exc
        return not self._fail_action

    def type_text(self, text: str) -> bool:
        self.calls.append(("type_text", (text,)))
        if self._timeout_exc is not None:
            raise self._timeout_exc
        return not self._fail_action

    def key_event(self, key_code: str) -> bool:
        self.calls.append(("key_event", (key_code,)))
        if self._timeout_exc is not None:
            raise self._timeout_exc
        return not self._fail_action


def _make_fixture_image() -> np.ndarray:
    """720x1280 BGR image with a distinct 20x20 marker centered at (160, 380)."""
    img = np.zeros((1280, 720, 3), dtype=np.uint8)
    img[370:390, 150:170] = (0, 200, 255)
    return img


def test_click_resized_crop_exact_mapping(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FrameStore(tmp_path / "store")
    platform = _RecordingPlatform(_make_fixture_image())
    obs = ObservationService(store=store, platform_factory=lambda _d: platform)

    snap = obs.snapshot("127.0.0.1:16480")
    cropped = obs.crop(snap["frame"]["frame_id"], (100, 300, 400, 500))
    resized = obs.resize(cropped["frame"]["frame_id"], scale=0.5)

    code = run_cli(
        [
            "--store-dir",
            str(store.store_dir),
            "click",
            "--device",
            "127.0.0.1:16480",
            "--frame",
            resized["frame"]["frame_id"],
            "--point",
            "30,40",
            "--json",
        ],
        service=obs,
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["command"] == "click"
    assert payload["result"]["status"] == "executed"
    assert payload["result"]["verified"] is False
    assert payload["result"]["target"] == {"x": 160, "y": 380}
    assert platform.calls == [("click", (160, 380))]


def test_click_by_scoped_ref(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FrameStore(tmp_path / "store")
    platform = _RecordingPlatform(_make_fixture_image())
    obs = ObservationService(store=store, platform_factory=lambda _d: platform)

    snap = obs.snapshot("127.0.0.1:16480")
    assets = AssetRegistry(store.store_dir)
    assets.register_from_frame(name="marker", frame_store=store, frame_id=snap["frame"]["frame_id"], region=(150, 370, 170, 390))

    cropped = obs.crop(snap["frame"]["frame_id"], (100, 300, 400, 500))
    matcher = MatchingService(store=store)
    found = matcher.find(frame_id=cropped["frame"]["frame_id"], target="marker", threshold=0.9)
    assert found["count"] == 1
    ref_id = found["matches"][0]["ref_id"]

    code = run_cli(
        [
            "--store-dir",
            str(store.store_dir),
            "click",
            "--device",
            "127.0.0.1:16480",
            "--ref",
            ref_id,
            "--json",
        ],
        service=obs,
    )
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["result"]["source"]["mode"] == "ref"
    assert payload["result"]["target"] == {"x": 160, "y": 380}
    assert platform.calls == [("click", (160, 380))]


def test_click_rejects_device_mismatch_stale_and_oob(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    platform = _RecordingPlatform(_make_fixture_image())
    obs = ObservationService(store=store, platform_factory=lambda _d: platform)
    snap = obs.snapshot("127.0.0.1:16480")
    actions = ActionService(store=store, platform_factory=lambda _d: platform)

    with pytest.raises(DeviceMismatchError):
        actions.click("other-device", frame_id=snap["frame"]["frame_id"], point=(10, 10))

    with pytest.raises(OutOfBoundsError):
        actions.click("127.0.0.1:16480", frame_id=snap["frame"]["frame_id"], point=(720, 10))

    with pytest.raises(OutOfBoundsError):
        actions.click("127.0.0.1:16480", frame_id=snap["frame"]["frame_id"], point=(-1, 10))

    refs = RefRegistry(store.store_dir)
    stale_ref = ScopedRef(
        ref_id="ref_stale01",
        frame_id=snap["frame"]["frame_id"],
        device_id="127.0.0.1:16480",
        target="marker",
        bbox=(150, 370, 170, 390),
        center=(160.0, 380.0),
        device_bbox=(150, 370, 170, 390),
        device_center=(160, 380),
        score=0.99,
        source_width=720,
        source_height=1280,
        rotation=0,
        created_at=time.time() - 100.0,
    )
    refs.save(stale_ref)

    with pytest.raises(StaleRefError):
        actions.click("127.0.0.1:16480", ref_id="ref_stale01", max_age_seconds=5.0)

    assert platform.calls == []


def test_swipe_type_key_and_receipts(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FrameStore(tmp_path / "store")
    platform = _RecordingPlatform(_make_fixture_image())
    obs = ObservationService(store=store, platform_factory=lambda _d: platform)

    assert run_cli(
        [
            "--store-dir",
            str(store.store_dir),
            "swipe",
            "--device",
            "127.0.0.1:16480",
            "--from",
            "10,20",
            "--to",
            "100,200",
            "--duration",
            "300",
            "--json",
        ],
        service=obs,
    ) == 0
    swipe_out = json.loads(capsys.readouterr().out)
    assert swipe_out["result"]["from"] == [10, 20]
    assert swipe_out["result"]["to"] == [100, 200]
    assert swipe_out["result"]["duration_ms"] == 300

    assert run_cli(
        [
            "--store-dir",
            str(store.store_dir),
            "type",
            "--device",
            "127.0.0.1:16480",
            "--text",
            "hello",
            "--json",
        ],
        service=obs,
    ) == 0
    type_out = json.loads(capsys.readouterr().out)
    assert type_out["result"]["text_length"] == 5

    assert run_cli(
        [
            "--store-dir",
            str(store.store_dir),
            "key",
            "--device",
            "127.0.0.1:16480",
            "--key",
            "KEYCODE_BACK",
            "--json",
        ],
        service=obs,
    ) == 0
    key_out = json.loads(capsys.readouterr().out)
    assert key_out["result"]["key"] == "KEYCODE_BACK"

    assert platform.calls == [
        ("swipe", (10, 20, 100, 200, 300)),
        ("type_text", ("hello",)),
        ("key_event", ("KEYCODE_BACK",)),
    ]


def test_timeout_returns_exit_4_and_no_retries(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FrameStore(tmp_path / "store")
    platform = _RecordingPlatform(
        _make_fixture_image(),
        timeout_exc=subprocess.TimeoutExpired(cmd="adb", timeout=5),
    )
    obs = ObservationService(store=store, platform_factory=lambda _d: platform)
    snap = obs.snapshot("127.0.0.1:16480")

    code = run_cli(
        [
            "--store-dir",
            str(store.store_dir),
            "click",
            "--device",
            "127.0.0.1:16480",
            "--frame",
            snap["frame"]["frame_id"],
            "--point",
            "10,20",
            "--json",
        ],
        service=obs,
    )
    assert code == 4
    err_payload = json.loads(capsys.readouterr().out)
    assert err_payload["ok"] is False
    assert err_payload["error"]["code"] == "ACTION_TIMEOUT"
    assert err_payload["error"]["retryable"] is False
    assert len(platform.calls) == 1


def test_failure_returns_exit_3_and_no_retries(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FrameStore(tmp_path / "store")
    platform = _RecordingPlatform(_make_fixture_image(), fail_action=True)
    obs = ObservationService(store=store, platform_factory=lambda _d: platform)

    code = run_cli(
        [
            "--store-dir",
            str(store.store_dir),
            "key",
            "--device",
            "127.0.0.1:16480",
            "--key",
            "HOME",
            "--json",
        ],
        service=obs,
    )
    assert code == 3
    err_payload = json.loads(capsys.readouterr().out)
    assert err_payload["ok"] is False
    assert err_payload["error"]["code"] == "ACTION_FAILED"
    assert err_payload["error"]["retryable"] is False
    assert len(platform.calls) == 1


def test_cli_subprocess_usage_error_json(tmp_path: Path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = os.pathsep.join(["core", "."])
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "vision_app",
            "--store-dir",
            str(tmp_path / "store"),
            "click",
            "--device",
            "127.0.0.1:16480",
            "--json",
        ],
        capture_output=True,
        text=True,
        env=env,
        check=False,
    )
    assert proc.returncode == 2
    payload = json.loads(proc.stdout.strip())
    assert payload["ok"] is False
    assert payload["error"]["code"] == "INVALID_USAGE"
