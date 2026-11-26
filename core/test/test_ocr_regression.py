"""Regression tests for template-based OCR (CORE-07)."""
import cv2
import numpy as np
import pytest

from service.core.opencv.dto import OcrRegion
from service.core.opencv.ocr.character_ocr import CharacterOCR
from service.core.opencv.ocr.pattern_ocr import PatternOCR
from service.core.opencv.open_cv_service import OpenCvService


def _make_digit_templates(tmp_path):
    """Create simple synthetic 12x12 grayscale PNG templates '1' and '2'."""
    t1 = np.zeros((12, 12), dtype=np.uint8)
    t1[2:10, 5:7] = 255

    t2 = np.zeros((12, 12), dtype=np.uint8)
    t2[2:4, 2:10] = 255
    t2[5:7, 2:10] = 255
    t2[8:10, 2:10] = 255
    t2[2:6, 8:10] = 255
    t2[5:10, 2:4] = 255

    cv2.imwrite(str(tmp_path / "1.png"), t1)
    cv2.imwrite(str(tmp_path / "2.png"), t2)
    return t1, t2


def _make_scene_with_templates(t1, t2):
    """Create a grayscale scene containing t1 at x=10 and t2 at x=40."""
    gray = np.zeros((30, 70), dtype=np.uint8)
    gray[8:20, 10:22] = t1
    gray[8:20, 40:52] = t2
    bgr = cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
    return gray, bgr


def test_character_ocr_bgr_and_gray_same_result(tmp_path):
    t1, t2 = _make_digit_templates(tmp_path)
    gray, bgr = _make_scene_with_templates(t1, t2)

    ocr = CharacterOCR()
    res_gray = ocr.execute_ocr(str(tmp_path), gray, 0.9)
    res_bgr = ocr.execute_ocr(str(tmp_path), bgr, 0.9)

    assert res_gray == "12"
    assert res_bgr == res_gray


def test_pattern_ocr_bgr_and_gray_same_result(tmp_path):
    t1, t2 = _make_digit_templates(tmp_path)
    gray, bgr = _make_scene_with_templates(t1, t2)

    ocr = PatternOCR()
    res_gray = ocr.execute_ocr(str(tmp_path), gray, 0.9)
    res_bgr = ocr.execute_ocr(str(tmp_path), bgr, 0.9)

    assert res_gray == res_bgr
    assert "1" in res_bgr and "2" in res_bgr


def test_opencv_service_ocr_from_mat_bgr_and_gray(tmp_path):
    t1, t2 = _make_digit_templates(tmp_path)
    gray, bgr = _make_scene_with_templates(t1, t2)
    region = OcrRegion(0, 0, 70, 30)

    svc = OpenCvService()
    assert svc.ocr_character_from_mat(str(tmp_path), bgr, region, 0.9) == "12"
    assert svc.ocr_character_from_mat(str(tmp_path), gray, region, 0.9) == "12"
    assert svc.ocr_pattern_from_mat(str(tmp_path), bgr, region, 0.9) == svc.ocr_pattern_from_mat(
        str(tmp_path), gray, region, 0.9
    )


def test_ocr_empty_templates_returns_empty_string(tmp_path):
    img = np.zeros((30, 30, 3), dtype=np.uint8)
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    missing_dir = tmp_path / "missing"

    for ocr in (CharacterOCR(), PatternOCR()):
        assert ocr.execute_ocr(str(empty_dir), img, 0.8) == ""
        assert ocr.execute_ocr(str(missing_dir), img, 0.8) == ""


def test_pattern_ocr_zero_threshold_and_constant_image_bounded(tmp_path):
    _make_digit_templates(tmp_path)
    constant_bgr = np.full((30, 40, 3), 128, dtype=np.uint8)

    ocr = PatternOCR()
    # Previously hung forever when threshold == 0.0
    result = ocr.execute_ocr(str(tmp_path), constant_bgr, 0.0)
    assert isinstance(result, str)


def test_ocr_validation_rejects_invalid_inputs(tmp_path):
    valid_img = np.zeros((20, 20, 3), dtype=np.uint8)
    for ocr in (CharacterOCR(), PatternOCR()):
        with pytest.raises(ValueError):
            ocr.execute_ocr(str(tmp_path), np.array([]), 0.8)
        with pytest.raises(ValueError):
            ocr.execute_ocr(str(tmp_path), valid_img, -0.1)
        with pytest.raises(ValueError):
            ocr.execute_ocr(str(tmp_path), valid_img, 1.5)
        with pytest.raises(ValueError):
            ocr.execute_ocr(str(tmp_path), valid_img, True)
