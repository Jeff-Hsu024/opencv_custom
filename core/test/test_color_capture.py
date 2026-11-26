"""Tests for color capture and BGR/grayscale decoding."""
import cv2
import numpy as np
from unittest.mock import MagicMock, patch

from service.core.opencv.mat_utility import MatUtility
from service.platform.adb.adb_platform import AdbPlatform
from service.platform.robot.robot_platform import RobotPlatform


def _make_synthetic_bgr_png(width: int = 8, height: int = 6) -> bytes:
    """Create a synthetic BGR PNG with distinct B, G, R channel values."""
    img = np.zeros((height, width, 3), dtype=np.uint8)
    img[:, :] = (10, 120, 240)  # B=10, G=120, R=240
    ok, buf = cv2.imencode(".png", img)
    assert ok
    return buf.tobytes()


class TestColorCaptureAndDecode:
    def test_convert_bytes_to_bgr_mat_synthetic_png(self):
        png_bytes = _make_synthetic_bgr_png(12, 8)
        mat = MatUtility.convert_bytes_to_bgr_mat(png_bytes)

        assert mat is not None
        assert mat.shape == (8, 12, 3)
        assert mat.dtype == np.uint8
        assert tuple(mat[0, 0]) == (10, 120, 240)

    def test_legacy_convert_bytes_to_mat_preserves_grayscale(self):
        png_bytes = _make_synthetic_bgr_png(12, 8)
        mat = MatUtility.convert_bytes_to_mat(png_bytes)

        assert mat is not None
        assert mat.shape == (8, 12)
        assert mat.dtype == np.uint8

    def test_adb_platform_snapshot_returns_bgr(self):
        mock_adb = MagicMock()
        mock_adb.device_id = "test-device"
        mock_adb.get_snapshot.return_value = _make_synthetic_bgr_png(10, 5)
        mock_opencv = MagicMock()

        platform = AdbPlatform(mock_adb, mock_opencv)
        mat = platform.snapshot()

        assert mat is not None
        assert mat.shape == (5, 10, 3)
        assert mat.dtype == np.uint8
        assert tuple(mat[0, 0]) == (10, 120, 240)

    @patch("pyautogui.screenshot")
    def test_robot_platform_snapshot_returns_bgr(self, mock_screenshot):
        # pyautogui.screenshot() returns RGB; RobotPlatform converts to BGR
        rgb_img = np.zeros((5, 10, 3), dtype=np.uint8)
        rgb_img[:, :] = (240, 120, 10)  # R=240, G=120, B=10
        mock_screenshot.return_value = rgb_img
        mock_opencv = MagicMock()

        platform = RobotPlatform(mock_opencv)
        mat = platform.snapshot()

        assert mat is not None
        assert mat.shape == (5, 10, 3)
        assert mat.dtype == np.uint8
        assert tuple(mat[0, 0]) == (10, 120, 240)

    def test_decode_failure_cases(self):
        assert MatUtility.convert_bytes_to_bgr_mat(None) is None
        assert MatUtility.convert_bytes_to_bgr_mat(b"") is None
        assert MatUtility.convert_bytes_to_bgr_mat(b"not-a-valid-png") is None

        assert MatUtility.convert_bytes_to_mat(None) is None
        assert MatUtility.convert_bytes_to_mat(b"") is None
        assert MatUtility.convert_bytes_to_mat(b"not-a-valid-png") is None

        mock_adb = MagicMock()
        mock_adb.device_id = "test-device"
        mock_opencv = MagicMock()
        platform = AdbPlatform(mock_adb, mock_opencv)

        mock_adb.get_snapshot.return_value = None
        assert platform.snapshot() is None

        mock_adb.get_snapshot.return_value = b"corrupted-bytes"
        assert platform.snapshot() is None
