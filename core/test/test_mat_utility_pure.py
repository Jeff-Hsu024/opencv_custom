import numpy as np
import pytest

from core.service.core.opencv.mat_utility import MatUtility


def _make_bgr(h: int = 20, w: int = 30) -> np.ndarray:
    img = np.zeros((h, w, 3), dtype=np.uint8)
    img[:, :, 0] = 10   # B
    img[:, :, 1] = 120  # G
    img[:, :, 2] = 240  # R
    return img


def test_resize_by_size_and_scale():
    bgr = _make_bgr(20, 40)

    resized_size = MatUtility.resize(bgr, size=(10, 5))
    assert resized_size.shape == (5, 10, 3)
    assert resized_size.dtype == np.uint8

    resized_down = MatUtility.resize(bgr, scale=0.5)
    assert resized_down.shape == (10, 20, 3)

    resized_up = MatUtility.resize(bgr, scale=2.0)
    assert resized_up.shape == (40, 80, 3)

    gray = np.full((12, 16), 128, dtype=np.uint8)
    resized_gray = MatUtility.resize(gray, size=(8, 6))
    assert resized_gray.shape == (6, 8)


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"size": (10, 10), "scale": 0.5},
        {"size": (0, 10)},
        {"size": (10, -1)},
        {"size": (True, 10)},
        {"size": (10.5, 10)},
        {"size": (10,)},
        {"scale": 0},
        {"scale": -0.5},
        {"scale": float("nan")},
        {"scale": float("inf")},
        {"scale": True},
    ],
)
def test_resize_invalid_args(kwargs):
    bgr = _make_bgr(10, 10)
    with pytest.raises(ValueError):
        MatUtility.resize(bgr, **kwargs)


@pytest.mark.parametrize(
    "bad_mat",
    [
        None,
        np.array([], dtype=np.uint8),
        np.zeros((10, 10), dtype=np.float32),
        np.zeros((10,), dtype=np.uint8),
        np.zeros((10, 10, 2), dtype=np.uint8),
    ],
)
def test_validate_mat_rejects_invalid_inputs(bad_mat):
    with pytest.raises(ValueError):
        MatUtility.resize(bad_mat, scale=1.0)
    with pytest.raises(ValueError):
        MatUtility.encode_png(bad_mat)


def test_png_round_trip_preserves_color():
    bgr = _make_bgr(16, 24)
    bgr[3, 7] = [255, 0, 128]
    data = MatUtility.encode_png(bgr)
    assert isinstance(data, bytes) and len(data) > 0

    decoded = MatUtility.decode_png(data)
    assert decoded.shape == bgr.shape
    assert decoded.dtype == np.uint8
    assert np.array_equal(decoded, bgr)


def test_decode_png_invalid_bytes():
    with pytest.raises(ValueError):
        MatUtility.decode_png(b"")
    with pytest.raises(ValueError):
        MatUtility.decode_png(b"not-a-png")


def test_encode_jpeg_and_quality_validation():
    bgr = _make_bgr(16, 16)
    high_q = MatUtility.encode_jpeg(bgr, quality=95)
    low_q = MatUtility.encode_jpeg(bgr, quality=10)
    assert len(high_q) > 0 and len(low_q) > 0

    with pytest.raises(ValueError):
        MatUtility.encode_jpeg(bgr, quality=101)
    with pytest.raises(ValueError):
        MatUtility.encode_jpeg(bgr, quality=-1)
    with pytest.raises(ValueError):
        MatUtility.encode_jpeg(bgr, quality=True)


def test_save_and_load_unicode_path(tmp_path):
    bgr = _make_bgr(18, 22)
    bgr[0, 0] = [12, 34, 56]
    target = tmp_path / "中文資料夾" / "測試圖檔_日本語.png"

    saved_path = MatUtility.save(target, bgr)
    assert saved_path == target
    assert target.is_file()

    loaded = MatUtility.load(target)
    assert loaded.shape == bgr.shape
    assert np.array_equal(loaded, bgr)


def test_save_jpeg_with_quality_and_invalid_args(tmp_path):
    bgr = _make_bgr(16, 16)
    jpg_path = tmp_path / "out.jpg"
    MatUtility.save(jpg_path, bgr, quality=80)
    assert jpg_path.is_file()

    with pytest.raises(ValueError):
        MatUtility.save(tmp_path / "no_ext", bgr)
    with pytest.raises(ValueError):
        MatUtility.save(tmp_path / "out.png", bgr, quality=80)
    with pytest.raises(FileNotFoundError):
        MatUtility.load(tmp_path / "missing.png")
