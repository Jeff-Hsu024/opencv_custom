import numpy as np
import pytest

from core.service.core.opencv.dto import MatchPattern, MatchResult
from core.service.core.opencv.open_cv_service import OpenCvService


@pytest.fixture
def opencv_service():
    return OpenCvService()


def test_match_template_bgr_distinguishes_color(opencv_service):
    # Blue and red have different BGR values; create a source with both
    source = np.zeros((100, 160, 3), dtype=np.uint8)
    # Blue square at (10, 20) .. (40, 50)
    source[20:50, 10:40] = (255, 0, 0)
    # Red square at (90, 20) .. (120, 50)
    source[20:50, 90:120] = (0, 0, 255)

    red_target = np.zeros((30, 30, 3), dtype=np.uint8)
    red_target[:] = (0, 0, 255)

    res = opencv_service.match_template(source, red_target, threshold=0.9, color_mode="bgr")
    assert isinstance(res, MatchResult)
    assert 0.99 <= res.score <= 1.0
    assert res.bbox == (90, 20, 120, 50)
    assert res.center == (105.0, 35.0)
    assert res.scale is None


def test_match_template_gray_accepts_bgr_and_gray(opencv_service):
    source_bgr = np.zeros((80, 80, 3), dtype=np.uint8)
    source_bgr[10:30, 20:45] = (200, 200, 200)
    target_gray = np.full((20, 25), 200, dtype=np.uint8)

    res = opencv_service.match_template(source_bgr, target_gray, threshold=0.9, color_mode="gray")
    assert res is not None
    assert res.score >= 0.99
    assert res.bbox == (20, 10, 45, 30)
    assert res.center == (32.5, 20.0)


def test_match_template_no_match_returns_none(opencv_service):
    source = np.zeros((60, 60, 3), dtype=np.uint8)
    target = np.full((20, 20, 3), 255, dtype=np.uint8)

    res = opencv_service.match_template(source, target, threshold=0.9, color_mode="bgr")
    assert res is None


@pytest.mark.parametrize("bad_threshold", [-0.1, 1.1, True, "0.8"])
def test_match_template_invalid_threshold_raises(opencv_service, bad_threshold):
    source = np.zeros((40, 40, 3), dtype=np.uint8)
    target = np.zeros((10, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="threshold"):
        opencv_service.match_template(source, target, threshold=bad_threshold)


def test_match_template_invalid_color_mode_raises(opencv_service):
    source = np.zeros((40, 40, 3), dtype=np.uint8)
    target = np.zeros((10, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="color_mode"):
        opencv_service.match_template(source, target, color_mode="rgb")


def test_match_template_oversized_target_raises(opencv_service):
    source = np.zeros((20, 20, 3), dtype=np.uint8)
    target = np.zeros((25, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="cannot exceed source size"):
        opencv_service.match_template(source, target)


def test_match_template_empty_or_none_raises(opencv_service):
    valid = np.zeros((20, 20, 3), dtype=np.uint8)
    empty = np.zeros((0, 0, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        opencv_service.match_template(empty, valid)
    with pytest.raises(ValueError):
        opencv_service.match_template(valid, None)


def test_match_template_bgr_rejects_grayscale_input(opencv_service):
    source_gray = np.zeros((40, 40), dtype=np.uint8)
    target_bgr = np.zeros((10, 10, 3), dtype=np.uint8)
    with pytest.raises(ValueError, match="3-channel BGR"):
        opencv_service.match_template(source_gray, target_bgr, color_mode="bgr")


def test_legacy_match_pattern_preserved():
    mp = MatchPattern(similar=0.15, point=(10.0, 20.0))
    assert mp.similar == 0.15
    assert mp.point == (10.0, 20.0)
    assert mp.get_similar() == pytest.approx(0.85)
