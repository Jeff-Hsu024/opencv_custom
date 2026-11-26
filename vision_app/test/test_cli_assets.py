"""Tests for application asset registry, scoped refs, matching, and CLI."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from vision_app.assets import (
    AssetNotFoundError,
    AssetRegistry,
    InvalidAssetNameError,
    MatchingService,
    RefRegistry,
    StaleRefError,
)
from vision_app.store import DeviceMismatchError, FrameStore
from vision_app.transforms import CoordinateTransform


def _make_pattern_frame(width: int = 320, height: int = 240) -> np.ndarray:
    """Create a deterministic BGR frame with two distinct 32x32 colored patches."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (30, 30, 30)
    # Patch 1 at (40, 50) -> (72, 82)
    img[50:82, 40:72] = (20, 200, 40)
    img[58:74, 48:64] = (255, 255, 255)
    # Patch 2 at (180, 120) -> (212, 152)
    img[120:152, 180:212] = (20, 200, 40)
    img[128:144, 188:204] = (255, 255, 255)
    return img


def test_asset_registry_persistence_and_safe_names(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    img = _make_pattern_frame()
    frame = store.save_frame(img, device_id="127.0.0.1:16480")

    reg1 = AssetRegistry(store.store_dir)
    rec = reg1.register_from_frame("play_btn", store, frame.frame_id, region=(40, 50, 72, 82))
    assert rec.name == "play_btn"
    assert rec.width == 32
    assert rec.height == 32
    assert rec.device_id == "127.0.0.1:16480"

    # Persistence across new registry instance
    reg2 = AssetRegistry(store.store_dir)
    loaded = reg2.get("play_btn")
    assert loaded.name == "play_btn"
    assert loaded.width == 32
    assert [a.name for a in reg2.list_assets()] == ["play_btn"]

    for bad_name in ("", "../evil", "a/b", "a\\b", "bad name", "x" * 65):
        with pytest.raises(InvalidAssetNameError):
            reg2.register_from_frame(bad_name, store, frame.frame_id)

    with pytest.raises(AssetNotFoundError):
        reg2.get("missing_asset")


def test_matching_single_all_nomatch_and_cropped_device_coords(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    img = _make_pattern_frame()
    frame = store.save_frame(img, device_id="dev-1", rotation=0)

    reg = AssetRegistry(store.store_dir)
    reg.register_from_frame("target_box", store, frame.frame_id, region=(40, 50, 72, 82))

    # Also register an asset that does not exist in an empty frame
    empty_frame = store.save_frame(np.zeros((240, 320, 3), dtype=np.uint8), device_id="dev-1")

    matcher = MatchingService(store=store, assets=reg)

    # Single match
    res_single = matcher.find(frame.frame_id, "target_box", threshold=0.9)
    assert res_single["found"] is True
    assert res_single["count"] == 1
    assert res_single["device_id"] == "dev-1"
    m0 = res_single["matches"][0]
    assert m0["score"] >= 0.99
    assert m0["bbox"] in ([40, 50, 72, 82], [180, 120, 212, 152])
    assert m0["ref_id"].startswith("ref_")

    # Find all
    res_all = matcher.find(frame.frame_id, "target_box", find_all=True, threshold=0.9)
    assert res_all["found"] is True
    assert res_all["count"] == 2
    bboxes = {tuple(m["bbox"]) for m in res_all["matches"]}
    assert bboxes == {(40, 50, 72, 82), (180, 120, 212, 152)}

    # No-match
    res_none = matcher.find(empty_frame.frame_id, "target_box", threshold=0.9)
    assert res_none["found"] is False
    assert res_none["count"] == 0
    assert res_none["matches"] == []

    # Cropped frame maps local bbox back to device coordinates
    cropped = img[100:200, 150:250]
    crop_frame = store.save_frame(
        cropped,
        device_id="dev-1",
        parent_id=frame.frame_id,
        transform=CoordinateTransform(offset_x=150, offset_y=100),
        source_width=320,
        source_height=240,
        rotation=0,
    )
    res_crop = matcher.find(crop_frame.frame_id, "target_box", threshold=0.9)
    assert res_crop["count"] == 1
    mc = res_crop["matches"][0]
    assert mc["bbox"] == [30, 20, 62, 52]
    assert mc["device_bbox"] == [180, 120, 212, 152]
    assert mc["device_center"] == [196.0, 136.0]


def test_scoped_ref_validation(tmp_path: Path) -> None:
    store = FrameStore(tmp_path / "store")
    img = _make_pattern_frame()
    frame = store.save_frame(img, device_id="dev-1", rotation=0)

    reg = AssetRegistry(store.store_dir)
    reg.register_from_frame("target_box", store, frame.frame_id, region=(40, 50, 72, 82))
    refs = RefRegistry(store.store_dir)
    matcher = MatchingService(store=store, assets=reg, refs=refs)

    res = matcher.find(frame.frame_id, "target_box", threshold=0.9)
    ref_id = res["matches"][0]["ref_id"]

    # Valid
    validated = refs.validate(ref_id, device_id="dev-1", frame_store=store)
    assert validated.ref_id == ref_id

    # Wrong device
    with pytest.raises(DeviceMismatchError):
        refs.validate(ref_id, device_id="dev-2", frame_store=store)

    # Stale rotation
    store.save_frame(img, device_id="dev-1", frame_id=frame.frame_id, rotation=90)
    with pytest.raises(StaleRefError):
        refs.validate(ref_id, device_id="dev-1", frame_store=store)


def test_cli_subprocess_assets_and_find(tmp_path: Path) -> None:
    store_dir = tmp_path / "store"
    store = FrameStore(store_dir)
    img = _make_pattern_frame()
    frame = store.save_frame(img, device_id="127.0.0.1:16480")
    empty_frame = store.save_frame(np.zeros((240, 320, 3), dtype=np.uint8), device_id="127.0.0.1:16480")

    env = os.environ.copy()
    repo_root = Path(__file__).resolve().parents[2]
    env["PYTHONPATH"] = f"{repo_root / 'core'}{os.pathsep}{repo_root}"

    def _run(*args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "vision_app", "--store-dir", str(store_dir), *args],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )

    # Register
    p_reg = _run("assets", "register", "--name", "btn_ok", "--frame", frame.frame_id, "--region", "40,50,72,82", "--json")
    assert p_reg.returncode == 0, p_reg.stderr
    reg_out = json.loads(p_reg.stdout)
    assert reg_out["ok"] is True
    assert reg_out["command"] == "assets register"
    assert reg_out["result"]["name"] == "btn_ok"

    # List
    p_list = _run("assets", "list", "--json")
    assert p_list.returncode == 0, p_list.stderr
    list_out = json.loads(p_list.stdout)
    assert list_out["ok"] is True
    assert list_out["result"]["count"] == 1
    assert list_out["result"]["assets"][0]["name"] == "btn_ok"

    # Find --all
    p_find = _run("find", "--frame", frame.frame_id, "--target", "btn_ok", "--all", "--threshold", "0.9", "--json")
    assert p_find.returncode == 0, p_find.stderr
    find_out = json.loads(p_find.stdout)
    assert find_out["ok"] is True
    assert find_out["device"] == "127.0.0.1:16480"
    assert find_out["result"]["count"] == 2

    # No-match returns exit 0 with empty matches
    p_none = _run("find", "--frame", empty_frame.frame_id, "--target", "btn_ok", "--threshold", "0.9", "--json")
    assert p_none.returncode == 0, p_none.stderr
    none_out = json.loads(p_none.stdout)
    assert none_out["ok"] is True
    assert none_out["result"]["found"] is False
    assert none_out["result"]["matches"] == []

    # Unsafe name returns exit 2
    p_bad = _run("assets", "register", "--name", "../bad", "--frame", frame.frame_id, "--json")
    assert p_bad.returncode == 2
    bad_out = json.loads(p_bad.stdout)
    assert bad_out["ok"] is False
    assert bad_out["error"]["code"] == "INVALID_USAGE"
