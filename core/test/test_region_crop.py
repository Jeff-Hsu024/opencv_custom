"""
Tests for Region / OcrRegion validation and MatUtility.crop / slice_region_mat_from_source.
"""
import numpy as np
import pytest

from core.service.core.opencv.dto import OcrRegion, Region
from core.service.core.opencv.mat_utility import MatUtility


class TestRegionAndOcrRegion:
    def test_ocr_region_is_region_compatible(self):
        r1 = Region(10, 20, 110, 70)
        r2 = OcrRegion(10, 20, 110, 70)
        r3 = OcrRegion(x1=10, y1=20, x2=110, y2=70)

        assert isinstance(r2, Region)
        assert isinstance(r3, Region)
        assert r1 == Region(10, 20, 110, 70)
        assert (r2.x1, r2.y1, r2.x2, r2.y2) == (10, 20, 110, 70)
        assert r2.width == 100
        assert r2.height == 50
        assert r2.area == 5000

    @pytest.mark.parametrize(
        "args",
        [
            (-1, 0, 10, 10),
            (0, -1, 10, 10),
            (10, 0, 10, 10),   # empty width
            (0, 10, 10, 10),   # empty height
            (20, 0, 10, 10),   # inverted x
            (0, 20, 10, 10),   # inverted y
            (0.0, 0, 10, 10),  # float
            (True, 0, 10, 10), # bool
        ],
    )
    def test_invalid_region_rejected(self, args):
        with pytest.raises(ValueError):
            Region(*args)
        with pytest.raises(ValueError):
            OcrRegion(*args)

    def test_validate_bounds(self):
        r = Region(0, 0, 100, 50)
        r.validate_bounds(100, 50)
        with pytest.raises(ValueError):
            r.validate_bounds(99, 50)
        with pytest.raises(ValueError):
            r.validate_bounds(100, 49)


class TestCropValidationAndCopy:
    def _make_bgr(self, height: int = 200, width: int = 300) -> np.ndarray:
        img = np.zeros((height, width, 3), dtype=np.uint8)
        img[:, :, 0] = (np.arange(width) % 256).astype(np.uint8)[None, :]
        img[:, :, 1] = (np.arange(height) % 256).astype(np.uint8)[:, None]
        img[:, :, 2] = 42
        return img

    def test_full_and_edge_roi(self):
        src = self._make_bgr(200, 300)

        full = MatUtility.crop(src, Region(0, 0, 300, 200))
        assert full.shape == (200, 300, 3)
        assert np.array_equal(full, src)

        top_left = MatUtility.crop(src, Region(0, 0, 1, 1))
        assert top_left.shape == (1, 1, 3)
        assert np.array_equal(top_left, src[0:1, 0:1])

        bottom_right = MatUtility.crop(src, OcrRegion(299, 199, 300, 200))
        assert bottom_right.shape == (1, 1, 3)
        assert np.array_equal(bottom_right, src[199:200, 299:300])

    def test_half_open_and_nested_crop(self):
        # 720x1280 (w=720, h=1280) -> crop [100, 300, 400, 500] => 300x200 (h=200, w=300)
        src = self._make_bgr(1280, 720)
        roi1 = Region(100, 300, 400, 500)
        crop1 = MatUtility.crop(src, roi1)
        assert crop1.shape == (200, 300, 3)
        assert np.array_equal(crop1, src[300:500, 100:400])

        # Nested crop local to crop1: [60, 80, 160, 180] => 100x100, corresponds to [160, 380, 260, 480] in src
        roi2 = Region(60, 80, 160, 180)
        crop2 = MatUtility.slice_region_mat_from_source(crop1, roi2)
        assert crop2.shape == (100, 100, 3)
        assert np.array_equal(crop2, src[380:480, 160:260])

    def test_oob_and_invalid_crop_rejected(self):
        src = self._make_bgr(100, 120)

        with pytest.raises(ValueError):
            MatUtility.crop(src, Region(0, 0, 121, 100))
        with pytest.raises(ValueError):
            MatUtility.crop(src, Region(0, 0, 120, 101))
        with pytest.raises(ValueError):
            MatUtility.crop(src, None)
        with pytest.raises(ValueError):
            MatUtility.crop(np.empty((0, 0, 3), dtype=np.uint8), Region(0, 0, 1, 1))

        # Duck-typed inverted/negative region without Region.__post_init__
        class RawRegion:
            def __init__(self, x1, y1, x2, y2):
                self.x1, self.y1, self.x2, self.y2 = x1, y1, x2, y2

        with pytest.raises(ValueError):
            MatUtility.slice_region_mat_from_source(src, RawRegion(50, 10, 10, 50))
        with pytest.raises(ValueError):
            MatUtility.slice_region_mat_from_source(src, RawRegion(-1, 0, 10, 10))

    def test_crop_returns_independent_copy_source_unchanged(self):
        src = self._make_bgr(100, 100)
        src_snapshot = src.copy()

        cropped = MatUtility.crop(src, Region(10, 20, 50, 60))
        assert not np.shares_memory(src, cropped)

        cropped.fill(0)
        assert np.array_equal(src, src_snapshot)

        cropped2 = MatUtility.slice_region_mat_from_source(src, OcrRegion(10, 20, 50, 60))
        src.fill(255)
        assert np.array_equal(cropped2, src_snapshot[20:60, 10:50])
