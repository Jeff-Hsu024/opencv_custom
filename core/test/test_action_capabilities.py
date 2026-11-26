"""Unit tests for generic action capabilities, long press, and safe desktop defaults."""
from unittest.mock import MagicMock, patch
import pytest

from service.platform.adb.adb import Adb, AdbProcessResult
from service.core.opencv.open_cv_service import OpenCvService
from service.platform.adb.adb_platform import AdbPlatform
from service.platform.robot.robot_platform import RobotPlatform


def _make_adb_platform(serial: str = "127.0.0.1:16480") -> tuple[AdbPlatform, MagicMock]:
    adb = MagicMock(spec=Adb)
    adb.run_argv.return_value = AdbProcessResult(
        argv=["adb"],
        returncode=0,
        stdout="",
        stderr="",
    )
    platform = AdbPlatform(adb, OpenCvService())
    platform.set_device_id(serial)
    return platform, adb


def test_adb_capabilities_and_long_press():
    platform, adb = _make_adb_platform()
    caps = platform.capabilities()
    assert caps["long_press"] is True
    assert caps["unicode_text"] is False

    assert platform.long_press(120, 340, duration=1500) is True
    adb.run_argv.assert_called_once()
    argv = adb.run_argv.call_args.args[0]
    assert argv[-8:] == ["shell", "input", "swipe", "120", "340", "120", "340", "1500"]
    assert "127.0.0.1:16480" in argv
    assert argv[-5:] == ["120", "340", "120", "340", "1500"]


def test_adb_invalid_duration_raises():
    platform, adb = _make_adb_platform()
    with pytest.raises(ValueError, match="duration"):
        platform.long_press(10, 20, duration=0)
    with pytest.raises(ValueError, match="duration"):
        platform.long_press(10, 20, duration=-100)
    with pytest.raises(ValueError, match="duration"):
        platform.swipe(10, 20, 30, 40, duration=0)
    adb.run_argv.assert_not_called()


def test_robot_failsafe_default_and_opt_out():
    ocv = OpenCvService()
    with patch("service.platform.robot.robot_platform.pyautogui") as mock_gui:
        robot_default = RobotPlatform(ocv)
        assert robot_default.failsafe is True
        assert mock_gui.FAILSAFE is True
        assert robot_default.capabilities()["failsafe"] is True
        assert robot_default.capabilities()["long_press"] is False
        assert robot_default.capabilities()["unicode_text"] is False

        robot_opt_out = RobotPlatform(ocv, failsafe=False)
        assert robot_opt_out.failsafe is False
        assert mock_gui.FAILSAFE is False
        assert robot_opt_out.capabilities()["failsafe"] is False


def test_robot_long_press_unsupported_and_swipe_mocked():
    ocv = OpenCvService()
    with patch("service.platform.robot.robot_platform.pyautogui") as mock_gui:
        robot = RobotPlatform(ocv)
        with pytest.raises(NotImplementedError, match="long_press"):
            robot.long_press(100, 200, duration=800)

        with pytest.raises(ValueError, match="duration"):
            robot.swipe(10, 20, 30, 40, duration=-1)

        assert robot.swipe(10, 20, 30, 40, duration=250) is True
        mock_gui.moveTo.assert_called_once_with(10, 20)
        mock_gui.dragTo.assert_called_once_with(30, 40, duration=0.25)
