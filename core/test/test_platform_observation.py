import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np

from core.script.script_interface import ScriptInterface
from core.service.core.opencv.dto import OcrRegion
from core.service.core.opencv.mat_utility import MatUtility
from core.service.platform.platform_service import PlatformService


class _StubPlatform(PlatformService):
    def __init__(self, frame=None):
        super().__init__(open_cv_service=MagicMock())
        self._frame = frame
        self.snapshot_calls = 0

    def start(self) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def snapshot(self):
        self.snapshot_calls += 1
        return self._frame

    def click(self, x: int, y: int) -> bool:
        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> bool:
        return True

    def type_text(self, text: str) -> bool:
        return True

    def key_event(self, key_code) -> bool:
        return True


class _DummyScript(ScriptInterface):
    def execute(self) -> None:
        pass


class TestPlatformObservation(unittest.TestCase):
    def setUp(self):
        self.frame = np.zeros((100, 120, 3), dtype=np.uint8)
        self.frame[10:30, 20:50] = (10, 20, 30)
        self.frame[40:70, 60:100] = (40, 50, 60)

    def test_snapshot_region_single_capture_and_crop(self):
        platform = _StubPlatform(self.frame)
        region = OcrRegion(20, 10, 50, 30)

        crop = platform.snapshot_region(region)

        self.assertEqual(platform.snapshot_calls, 1)
        self.assertIsNotNone(crop)
        self.assertEqual(crop.shape, (20, 30, 3))
        self.assertTrue(np.array_equal(crop, self.frame[10:30, 20:50]))

    def test_snapshot_region_failure_returns_none(self):
        platform = _StubPlatform(None)
        region = OcrRegion(0, 0, 10, 10)

        self.assertIsNone(platform.snapshot_region(region))
        self.assertEqual(platform.snapshot_calls, 1)

    def test_snapshot_region_invalid_bounds_raises(self):
        platform = _StubPlatform(self.frame)
        with self.assertRaises(ValueError):
            platform.snapshot_region(OcrRegion(0, 0, 200, 50))

    def test_save_snapshot_full_and_region_unicode_path(self):
        platform = _StubPlatform(self.frame)
        with tempfile.TemporaryDirectory() as tmpdir:
            full_path = Path(tmpdir) / "截圖_full.png"
            saved_full = platform.save_snapshot(full_path)

            self.assertEqual(platform.snapshot_calls, 1)
            self.assertEqual(saved_full, full_path)
            loaded_full = MatUtility.load(full_path)
            self.assertTrue(np.array_equal(loaded_full, self.frame))

            region_path = Path(tmpdir) / "截圖_crop.png"
            region = OcrRegion(60, 40, 100, 70)
            saved_region = platform.save_snapshot(region_path, region=region)

            self.assertEqual(platform.snapshot_calls, 2)
            self.assertEqual(saved_region, region_path)
            loaded_region = MatUtility.load(region_path)
            self.assertEqual(loaded_region.shape, (30, 40, 3))
            self.assertTrue(np.array_equal(loaded_region, self.frame[40:70, 60:100]))

    def test_save_snapshot_failure_returns_none(self):
        platform = _StubPlatform(None)
        with tempfile.TemporaryDirectory() as tmpdir:
            out_path = Path(tmpdir) / "missing.png"
            self.assertIsNone(platform.save_snapshot(out_path))
            self.assertEqual(platform.snapshot_calls, 1)
            self.assertFalse(out_path.exists())

    def test_snapshot_regions_single_capture_multiple_crops(self):
        platform = _StubPlatform(self.frame)
        regions = [OcrRegion(20, 10, 50, 30), OcrRegion(60, 40, 100, 70)]

        crops = platform.snapshot_regions(regions)

        self.assertEqual(platform.snapshot_calls, 1)
        self.assertIsNotNone(crops)
        self.assertEqual(len(crops), 2)
        self.assertTrue(np.array_equal(crops[0], self.frame[10:30, 20:50]))
        self.assertTrue(np.array_equal(crops[1], self.frame[40:70, 60:100]))

    def test_snapshot_regions_failure_returns_none(self):
        platform = _StubPlatform(None)
        self.assertIsNone(platform.snapshot_regions([OcrRegion(0, 0, 10, 10)]))
        self.assertEqual(platform.snapshot_calls, 1)

    def test_old_script_interface_methods_intact(self):
        mock_platform = MagicMock()
        mock_platform.device_id = "127.0.0.1:16480"
        script = _DummyScript(mock_platform)

        for method_name in (
            "click",
            "swipe",
            "find",
            "tap",
            "wait_tap",
            "ocr_text",
            "ocr_pattern",
            "sleep",
            "log",
        ):
            self.assertTrue(callable(getattr(script, method_name)))


if __name__ == "__main__":
    unittest.main()
