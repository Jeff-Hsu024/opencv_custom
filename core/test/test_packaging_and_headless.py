"""Tests for PKG-01: installable package, headless imports, and legacy wrappers."""

import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def _run_python(code: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", code],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=False,
    )


def test_adb_import_without_pyautogui():
    code = (
        "import sys; sys.modules['pyautogui'] = None; "
        "from service.platform.adb.adb import Adb; "
        "from service.platform.adb.adb_platform import AdbPlatform; "
        "from service.core.opencv.open_cv_service import OpenCvService; "
        "assert Adb is not None and AdbPlatform is not None and OpenCvService is not None"
    )
    res = _run_python(code)
    assert res.returncode == 0, f"stderr: {res.stderr}"


def test_robot_platform_lazy_import_without_pyautogui():
    code = (
        "import sys\n"
        "sys.modules['pyautogui'] = None\n"
        "from service.platform.robot.robot_platform import RobotPlatform\n"
        "from service.core.opencv.open_cv_service import OpenCvService\n"
        "try:\n"
        "    RobotPlatform(OpenCvService())\n"
        "except ImportError as exc:\n"
        "    assert 'desktop' in str(exc)\n"
        "else:\n"
        "    raise AssertionError('Expected ImportError when pyautogui is missing')\n"
    )
    res = _run_python(code)
    assert res.returncode == 0, f"stderr: {res.stderr}"


def test_legacy_entry_and_scripts_import_without_pyautogui():
    code = (
        "import sys\n"
        "sys.modules['pyautogui'] = None\n"
        "import entry, run_script\n"
        "assert hasattr(entry, 'main') or hasattr(entry, 'run_test_log')\n"
        "assert hasattr(run_script, 'run_gear_script')\n"
    )
    res = _run_python(code)
    assert res.returncode == 0, f"stderr: {res.stderr}"
