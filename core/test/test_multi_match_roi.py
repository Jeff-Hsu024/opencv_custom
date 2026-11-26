from pathlib import Path
from typing import Optional
import cv2
import numpy as np
import pytest

from core.service.core.opencv.dto import MatchResult, OcrRegion
from core.service.core.opencv.open_cv_service import OpenCvService
from core.service.platform.platform_service import PlatformService


class _FakePlatformService(PlatformService):
    def __init__(self, open_cv_service: OpenCvService, frame: Optional[np.ndarray]):
        super().__init__(open_cv_service)
        self._frame = frame
        self.snapshot_calls = 0

    def start(self) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def set_device_id(self, device_id: str) -> None:
        pass

    def snapshot(self) -> Optional[np.ndarray]:
        self.snapshot_calls += 1
        return None if self._frame is None else self._frame.copy()

    def click(self, x: int, y: int) -> bool:
        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> bool:
        return True

    def type_text(self, text: str) -> bool:
        return True

    def key_event(self, key_code) -> bool:
        return True


@pytest.fixture
def opencv_service():
    return OpenCvService()


def _make_textured_patch(seed: int, h: int = 16, w: int = 16) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.integers(30, 230, size=(h, w, 3), dtype=np.uint8)


def test_find_all_multiple_matches_and_deterministic_ordering(opencv_service):
    source = np.zeros((100, 120, 3), dtype=np.uint8)
    patch = _make_textured_patch(42, 16, 16)

    # Place 3 identical patches at distinct locations
    source[10:26, 70:86] = patch   # (70, 10)
    source[10:26, 20:36] = patch   # (20, 10) -> same y=10, smaller x=20 should come before x=70
    source[60:76, 40:56] = patch   # (40, 60)

    results = opencv_service.find_all(source, patch, threshold=0.95, max_results=10, color_mode="bgr")
    assert len(results) == 3
    assert [r.bbox for r in results] == [
        (20, 10, 36, 26),
        (70, 10, 86, 26),
        (40, 60, 56, 76),
    ]
    for r in results:
        assert r.score >= 0.99


def test_find_all_overlapping_matches_nms_suppresses_duplicates(opencv_service):
    source = np.zeros((80, 80, 3), dtype=np.uint8)
    patch = _make_textured_patch(7, 20, 20)
    source[20:40, 20:40] = patch

    # With a slightly lower threshold, adjacent 1px-shifted windows also score high;
    # NMS with iou_threshold=0.3 should collapse them to a single match.
    results = opencv_service.find_all(
        source, patch, threshold=0.75, max_results=10, iou_threshold=0.3, color_mode="bgr"
    )
    assert len(results) == 1
    assert results[0].bbox == (20, 20, 40, 40)


def test_find_all_respects_max_results_limit(opencv_service):
    source = np.zeros((120, 120, 3), dtype=np.uint8)
    patch = _make_textured_patch(99, 14, 14)
    for y in (10, 40, 70, 100):
        source[y:y + 14, 10:24] = patch

    results = opencv_service.find_all(source, patch, threshold=0.95, max_results=2, color_mode="bgr")
    assert len(results) == 2
    assert [r.bbox for r in results] == [(10, 10, 24, 24), (10, 40, 24, 54)]


def test_find_all_no_match_returns_empty_list(opencv_service):
    source = np.zeros((60, 60, 3), dtype=np.uint8)
    patch = _make_textured_patch(11, 16, 16)
    assert opencv_service.find_all(source, patch, threshold=0.9, color_mode="bgr") == []


@pytest.mark.parametrize("bad_max", [0, -1, True, "5", 2.5])
def test_find_all_invalid_max_results_raises(opencv_service, bad_max):
    source = np.zeros((40, 40, 3), dtype=np.uint8)
    target = np.zeros((10, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="max_results"):
        opencv_service.find_all(source, target, max_results=bad_max)


@pytest.mark.parametrize("bad_iou", [-0.1, 1.1, True, "0.5"])
def test_find_all_invalid_iou_threshold_raises(opencv_service, bad_iou):
    source = np.zeros((40, 40, 3), dtype=np.uint8)
    target = np.zeros((10, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="iou_threshold"):
        opencv_service.find_all(source, target, iou_threshold=bad_iou)


def test_platform_find_match_and_find_all_roi_offset_and_single_capture(tmp_path: Path, opencv_service):
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    patch = _make_textured_patch(55, 16, 16)
    # Place two patches inside ROI (50, 30, 150, 110)
    frame[40:56, 60:76] = patch    # full-screen (60, 40, 76, 56)
    frame[80:96, 110:126] = patch  # full-screen (110, 80, 126, 96)

    tpl_path = tmp_path / "tpl.png"
    cv2.imwrite(str(tpl_path), patch)

    svc = _FakePlatformService(opencv_service, frame)
    roi = OcrRegion(50, 30, 150, 110)

    # Single capture for find_all_matches with ROI mapping
    matches = svc.find_all_matches(str(tpl_path), region=roi, threshold=0.95)
    assert svc.snapshot_calls == 1
    assert len(matches) == 2
    assert [m.bbox for m in matches] == [
        (60, 40, 76, 56),
        (110, 80, 126, 96),
    ]
    assert matches[0].center == (68.0, 48.0)

    # Supplied image: zero additional snapshot calls
    best = svc.find_match(str(tpl_path), region=roi, threshold=0.95, source=frame)
    assert svc.snapshot_calls == 1
    assert best is not None
    assert best.bbox == (60, 40, 76, 56)
    assert best.center == (68.0, 48.0)

    matches_supplied = svc.find_all_matches(
        str(tpl_path), region=roi, threshold=0.95, source=frame
    )
    assert svc.snapshot_calls == 1
    assert len(matches_supplied) == 2
