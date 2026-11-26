"""Tests for WaitService and `vision wait` CLI."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import numpy as np
import pytest

from vision_app.assets import AssetRegistry
from vision_app.cli import run_cli
from vision_app.observation import ObservationService, OperationError
from vision_app.store import FrameStore
from vision_app.waits import WaitService


class _FakeClock:
    def __init__(self, start: float = 100.0) -> None:
        self.now = start
        self.sleeps: List[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class _SequencePlatform:
    def __init__(self, frames: List[np.ndarray]) -> None:
        self._frames = list(frames)
        self.calls = 0

    def snapshot(self) -> np.ndarray:
        idx = min(self.calls, len(self._frames) - 1)
        self.calls += 1
        return self._frames[idx].copy()


def _solid_frame(w: int = 100, h: int = 80, bgr=(10, 20, 30)) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :] = bgr
    return img


def test_wait_changed_with_roi_ignores_outside_noise(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    clock = _FakeClock()

    base = _solid_frame()
    noisy_outside = base.copy()
    noisy_outside[0:10, 0:10] = (255, 255, 255)  # outside ROI (20,20,60,60)
    changed_inside = noisy_outside.copy()
    changed_inside[30:40, 30:40] = (0, 255, 0)  # inside ROI

    plat = _SequencePlatform([base, noisy_outside, changed_inside])
    waits = WaitService(
        store,
        platform_factory=lambda _dev: plat,
        clock=clock,
        sleeper=clock.sleep,
    )

    res = waits.wait_changed(
        "dev1",
        region=(20, 20, 60, 60),
        timeout=5.0,
        interval=0.5,
        min_changed_ratio=0.05,
    )
    assert res["condition"] == "changed"
    assert res["verified"] is True
    assert res["captures"] == 3
    assert res["region"] == [20, 20, 60, 60]
    assert plat.calls == 3


def test_wait_changed_with_baseline_frame_id(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    clock = _FakeClock()
    base = _solid_frame()
    base_rec = store.save_frame(device_id="dev1", image=base)

    changed = base.copy()
    changed[10:30, 10:30] = (200, 100, 50)
    plat = _SequencePlatform([changed])
    waits = WaitService(
        store,
        platform_factory=lambda _dev: plat,
        clock=clock,
        sleeper=clock.sleep,
    )

    res = waits.wait_changed("dev1", baseline_frame_id=base_rec.frame_id, timeout=2.0)
    assert res["verified"] is True
    assert res["captures"] == 1


def test_wait_stable_resets_on_change_and_succeeds(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    clock = _FakeClock()

    f1 = _solid_frame(bgr=(10, 10, 10))
    f2 = _solid_frame(bgr=(20, 20, 20))  # changed -> resets stable_since
    f3 = f2.copy()
    f4 = f2.copy()
    plat = _SequencePlatform([f1, f2, f3, f4])
    waits = WaitService(
        store,
        platform_factory=lambda _dev: plat,
        clock=clock,
        sleeper=clock.sleep,
    )

    res = waits.wait_stable(
        "dev1",
        timeout=10.0,
        interval=0.5,
        stable_duration=1.0,
    )
    assert res["condition"] == "stable"
    assert res["verified"] is True
    assert res["captures"] == 4
    assert res["stable_seconds"] >= 1.0


def test_wait_image_with_roi_maps_coordinates(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    registry = AssetRegistry(store.store_dir)
    clock = _FakeClock()

    tpl = np.zeros((16, 16, 3), dtype=np.uint8)
    tpl[4:12, 4:12] = (255, 255, 255)
    src_rec = store.save_frame(device_id="dev1", image=tpl)
    registry.register_from_frame("icon", store, src_rec.frame_id)

    empty = _solid_frame(100, 80, (0, 0, 0))
    with_icon = empty.copy()
    with_icon[30:46, 40:56] = tpl

    plat = _SequencePlatform([empty, with_icon])
    waits = WaitService(
        store,
        asset_registry=registry,
        platform_factory=lambda _dev: plat,
        clock=clock,
        sleeper=clock.sleep,
    )

    res = waits.wait_image(
        "dev1",
        target_name="icon",
        region=(35, 25, 70, 60),
        timeout=5.0,
        interval=0.5,
    )
    assert res["condition"] == "image"
    assert res["verified"] is True
    assert res["captures"] == 2
    assert res["match"]["bbox"] == [40, 30, 56, 46]
    assert res["match"]["center"] == [48, 38]


def test_wait_timeout_and_max_captures_bounded(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    clock = _FakeClock()
    static = _solid_frame()
    plat = _SequencePlatform([static])
    waits = WaitService(
        store,
        platform_factory=lambda _dev: plat,
        clock=clock,
        sleeper=clock.sleep,
    )

    with pytest.raises(OperationError) as exc_info:
        waits.wait_changed("dev1", timeout=5.0, interval=0.5, max_captures=3)
    assert exc_info.value.code == "WAIT_TIMEOUT"
    assert exc_info.value.exit_code == 4
    assert plat.calls == 3


def test_compare_frames_with_roi(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    a = _solid_frame()
    b = a.copy()
    b[0:10, 0:10] = (255, 255, 255)
    rec_a = store.save_frame(device_id="dev1", image=a)
    rec_b = store.save_frame(device_id="dev1", image=b)

    waits = WaitService(store)
    res_roi = waits.compare_frames(rec_a.frame_id, rec_b.frame_id, region=(20, 20, 60, 60))
    assert res_roi["within_tolerance"] is True
    assert res_roi["changed_pixels"] == 0


def test_cli_wait_changed_and_timeout_exit_4(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = FrameStore(tmp_path / "store")
    static = _solid_frame()
    changed = static.copy()
    changed[10:40, 10:40] = (0, 255, 0)

    plat_ok = _SequencePlatform([static, changed])
    obs_ok = ObservationService(store=store, platform_factory=lambda _d: plat_ok)
    code_ok = run_cli(
        ["wait", "--device", "dev1", "--changed", "--interval", "0.01", "--timeout", "1.0", "--json"],
        service=obs_ok,
    )
    assert code_ok == 0
    payload_ok = json.loads(capsys.readouterr().out)
    assert payload_ok["ok"] is True
    assert payload_ok["command"] == "wait"
    assert payload_ok["result"]["condition"] == "changed"
    assert payload_ok["result"]["verified"] is True

    plat_to = _SequencePlatform([static])
    obs_to = ObservationService(store=store, platform_factory=lambda _d: plat_to)
    code_to = run_cli(
        ["wait", "--device", "dev1", "--changed", "--interval", "0.01", "--max-captures", "2", "--json"],
        service=obs_to,
    )
    assert code_to == 4
    payload_to = json.loads(capsys.readouterr().out)
    assert payload_to["ok"] is False
    assert payload_to["error"]["code"] == "WAIT_TIMEOUT"
