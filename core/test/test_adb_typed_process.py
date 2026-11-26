import subprocess
from unittest.mock import MagicMock, patch

from service.core.opencv.open_cv_service import OpenCvService
from service.platform.adb.adb import Adb, AdbProcessResult
from service.platform.adb.adb_command import AdbCommand
from service.platform.adb.adb_key_code import AdbKeyCode
from service.platform.adb.adb_platform import AdbPlatform


def test_nonzero_without_error_text_fails():
    adb = Adb(device_id="127.0.0.1:16480")
    cv = MagicMock(spec=OpenCvService)
    platform = AdbPlatform(adb, cv)

    completed = subprocess.CompletedProcess(
        args=["adb"],
        returncode=1,
        stdout="some benign output",
        stderr="",
    )
    with patch("service.platform.adb.adb.subprocess.run", return_value=completed) as run_mock:
        assert platform.click(10, 20) is False
        assert run_mock.call_args.kwargs["shell"] is False


def test_warning_or_error_word_on_zero_exit_succeeds():
    adb = Adb(device_id="127.0.0.1:16480")
    cv = MagicMock(spec=OpenCvService)
    platform = AdbPlatform(adb, cv)

    completed = subprocess.CompletedProcess(
        args=["adb"],
        returncode=0,
        stdout="Warning: error-free fallback used",
        stderr="WARNING: something",
    )
    with patch("service.platform.adb.adb.subprocess.run", return_value=completed):
        assert platform.click(10, 20) is True


def test_timeout_returns_typed_failure():
    adb = Adb(device_id="127.0.0.1:16480")
    cv = MagicMock(spec=OpenCvService)
    platform = AdbPlatform(adb, cv)

    exc = subprocess.TimeoutExpired(cmd=["adb"], timeout=1.5, output=b"partial", stderr=b"")
    with patch("service.platform.adb.adb.subprocess.run", side_effect=exc):
        result = adb.run_argv(["adb", "devices"], timeout=1.5)
        assert isinstance(result, AdbProcessResult)
        assert result.timed_out is True
        assert result.ok is False
        assert platform.click(1, 2) is False


def test_literal_arguments_preserved_without_shell():
    adb = Adb(device_id="127.0.0.1:16480")
    cv = MagicMock(spec=OpenCvService)
    platform = AdbPlatform(adb, cv)
    literal = "hello world & echo injected"

    completed = subprocess.CompletedProcess(args=["adb"], returncode=0, stdout="", stderr="")
    with patch("service.platform.adb.adb.subprocess.run", return_value=completed) as run_mock:
        assert platform.type_text(literal) is True
        argv = run_mock.call_args.args[0]
        assert argv[-1] == literal
        assert run_mock.call_args.kwargs["shell"] is False


def test_explicit_serial_and_key_event_argv():
    adb = Adb()
    completed = subprocess.CompletedProcess(args=["adb"], returncode=0, stdout="", stderr="")
    with patch("service.platform.adb.adb.subprocess.run", return_value=completed) as run_mock:
        result = adb.run_argv(["adb", "devices"], serial="127.0.0.1:16480")
        assert result.ok is True
        assert run_mock.call_args.args[0][:3] == ["adb", "-s", "127.0.0.1:16480"]

    argv = AdbKeyCode.KEYCODE_HOME.get_argv("127.0.0.1:16480")
    assert argv[1:] == ["-s", "127.0.0.1:16480", "shell", "input", "keyevent", "3"]


def test_raw_exec_compatibility():
    adb = Adb(device_id="emulator-5554")
    completed = subprocess.CompletedProcess(args="adb", returncode=0, stdout="ok", stderr="")
    with patch("service.platform.adb.adb.subprocess.run", return_value=completed) as run_mock:
        out = adb.exec("adb devices")
        assert out == "ok"
        assert run_mock.call_args.kwargs["shell"] is True
