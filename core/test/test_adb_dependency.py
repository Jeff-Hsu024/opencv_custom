import io
import importlib.util
from pathlib import Path
from unittest.mock import patch
import zipfile
import pytest

from service.platform.adb.adb_command import AdbCommand
from service.platform.adb.adb_key_code import AdbKeyCode

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("install_platform_tools", ROOT / "tools/install_platform_tools.py")
installer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(installer)

def archive(entries):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for path, content in entries.items():
            z.writestr(path, content)
    buf.seek(0)
    return buf

def test_installer_uses_official_url_and_reuses_download(tmp_path):
    with patch.object(installer.platform, "system", return_value="Windows"), patch.object(
        installer.urllib.request, "urlopen", return_value=archive({"platform-tools/adb.exe": b"fixture"})
    ) as download, patch.object(installer.subprocess, "run") as check:
        path = installer.install(tmp_path)
        assert path.read_bytes() == b"fixture"
        assert installer.install(tmp_path) == path
        download.assert_called_once_with(installer.BASE + "platform-tools-latest-windows.zip", timeout=60)
        check.assert_called_once()

def test_installer_rejects_traversal(tmp_path):
    with patch.object(installer.platform, "system", return_value="Windows"), patch.object(
        installer.urllib.request, "urlopen", return_value=archive({"../escape.txt": b"bad"})
    ):
        with pytest.raises(RuntimeError, match="Unsafe archive path"):
            installer.install(tmp_path)
    assert not (tmp_path / "platform-tools").exists()

def test_key_event_uses_same_resolver():
    with patch.object(AdbCommand, "_get_adb_platform", return_value='"custom adb" '):
        assert AdbKeyCode.KEYCODE_HOME.get_command("serial") == '"custom adb" -s serial shell input keyevent 3'
