"""Tests for vision_app FrameStore and CoordinateTransform."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from vision_app import (
    CoordinateTransform,
    DeviceMismatchError,
    FrameNotFoundError,
    FrameStore,
    InvalidFrameIdError,
    OutOfBoundsError,
)


def _blank_bgr(width: int, height: int, color: tuple[int, int, int] = (10, 20, 30)) -> np.ndarray:
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = color
    return img


def test_acceptance_coordinate_fixture_and_nested_crop(tmp_path: Path) -> None:
    """Verify ACCEPTANCE.md fixture: 720x1280 -> crop [100,300,400,500] -> resize 150x100 -> nested crop."""
    store = FrameStore(tmp_path)
    src = _blank_bgr(720, 1280)
    f_src = store.save_frame(src, device_id="127.0.0.1:16480", frame_id="src")

    # Crop [100, 300, 400, 500] => 300x200
    crop_img = src[300:500, 100:400]
    t_crop = f_src.transform.compose(CoordinateTransform.for_crop(100, 300))
    f_crop = store.save_frame(
        crop_img,
        device_id="127.0.0.1:16480",
        frame_id="crop1",
        parent_id=f_src.frame_id,
        transform=t_crop,
        source_width=720,
        source_height=1280,
    )
    assert store.map_point("crop1", 60, 80, device_id="127.0.0.1:16480") == (160, 380)

    # Resize 300x200 -> 150x100
    resized_img = _blank_bgr(150, 100)
    t_resize = f_crop.transform.compose(CoordinateTransform.for_resize(300, 200, 150, 100))
    f_res = store.save_frame(
        resized_img,
        device_id="127.0.0.1:16480",
        frame_id="res1",
        parent_id=f_crop.frame_id,
        transform=t_resize,
        source_width=720,
        source_height=1280,
    )
    assert store.map_point("res1", 30, 40, device_id="127.0.0.1:16480") == (160, 380)

    # Nested crop [10, 20, 60, 70] => 50x50 on resized frame
    nested_img = _blank_bgr(50, 50)
    t_nested = f_res.transform.compose(CoordinateTransform.for_crop(10, 20))
    store.save_frame(
        nested_img,
        device_id="127.0.0.1:16480",
        frame_id="nested1",
        parent_id=f_res.frame_id,
        transform=t_nested,
        source_width=720,
        source_height=1280,
    )
    assert store.map_point("nested1", 20, 20, device_id="127.0.0.1:16480") == (160, 380)


def test_out_of_bounds_and_wrong_device_rejection(tmp_path: Path) -> None:
    store = FrameStore(tmp_path)
    store.save_frame(_blank_bgr(100, 80), device_id="dev-a", frame_id="f1")

    with pytest.raises(DeviceMismatchError):
        store.get_frame("f1", device_id="dev-b")

    with pytest.raises(DeviceMismatchError):
        store.map_point("f1", 10, 10, device_id="dev-b")

    # Half-open bounds: [0, 100) x [0, 80)
    with pytest.raises(OutOfBoundsError):
        store.map_point("f1", -1, 0, device_id="dev-a")
    with pytest.raises(OutOfBoundsError):
        store.map_point("f1", 100, 0, device_id="dev-a")
    with pytest.raises(OutOfBoundsError):
        store.map_point("f1", 0, 80, device_id="dev-a")


@pytest.mark.parametrize("bad_id", ["../evil", "..\\evil", "a/b", "a\\b", "", "bad id", "a.b"])
def test_path_traversal_rejection(tmp_path: Path, bad_id: str) -> None:
    store = FrameStore(tmp_path)
    with pytest.raises(InvalidFrameIdError):
        store.save_frame(_blank_bgr(10, 10), device_id="dev-a", frame_id=bad_id)
    with pytest.raises(InvalidFrameIdError):
        store.get_frame(bad_id)


def test_bounded_ttl_cleanup_preserves_protected_assets(tmp_path: Path) -> None:
    store = FrameStore(tmp_path, max_frames=2, ttl_seconds=100.0)
    store.save_frame(_blank_bgr(10, 10), device_id="dev-a", frame_id="asset1", timestamp=10.0, protected=True)
    store.save_frame(_blank_bgr(10, 10), device_id="dev-a", frame_id="old1", timestamp=20.0)
    store.save_frame(_blank_bgr(10, 10), device_id="dev-a", frame_id="new1", timestamp=200.0)

    # old1 expired (20 < 200 - 100), asset1 is protected even though timestamp=10.0
    assert store.get_frame("asset1").protected is True
    assert store.get_frame("new1").frame_id == "new1"
    with pytest.raises(FrameNotFoundError):
        store.get_frame("old1")


def test_cross_process_persistence(tmp_path: Path) -> None:
    """Verify frames saved in one Python process are readable and mappable in another."""
    repo_root = Path(__file__).resolve().parents[2]
    env_python = sys.executable

    writer_code = (
        "import numpy as np; "
        "from vision_app import FrameStore, CoordinateTransform; "
        f"s = FrameStore({str(tmp_path)!r}); "
        "img = np.zeros((200, 300, 3), dtype=np.uint8); "
        "t = CoordinateTransform.for_crop(100, 300); "
        "s.save_frame(img, device_id='127.0.0.1:16480', frame_id='p1', transform=t, source_width=720, source_height=1280)"
    )
    res1 = subprocess.run(
        [env_python, "-c", writer_code],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    assert res1.returncode == 0

    reader_code = (
        "import json; "
        "from vision_app import FrameStore; "
        f"s = FrameStore({str(tmp_path)!r}); "
        "pt = s.map_point('p1', 60, 80, device_id='127.0.0.1:16480'); "
        "img = s.load_image('p1', device_id='127.0.0.1:16480'); "
        "print(json.dumps({'pt': list(pt), 'shape': list(img.shape)}))"
    )
    res2 = subprocess.run(
        [env_python, "-c", reader_code],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(res2.stdout.strip())
    assert data["pt"] == [160, 380]
    assert data["shape"] == [200, 300, 3]
