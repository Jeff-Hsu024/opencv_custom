"""
ADB 命令列枚舉
"""
from enum import Enum
import os


class AdbCommand(Enum):
    """ADB 命令列枚舉"""
    
    DAEMON_START = "start-server"
    DAEMON_CLOSE = "kill-server"
    DEVICE_LIST = "devices"
    CONNECT = "connect %s"
    SCREEN_CAP = "-s %s exec-out screencap -p"
    TAP = "-s %s shell input tap %s %s"
    SWIPE = "-s %s shell input swipe %s %s %s %s %s"
    DRAG_DROP = "-s %s shell input draganddrop %s %s %s %s %s"
    START_APP = "-s %s shell am start -n %s"
    STOP_APP = "-s %s shell am force-stop %s"
    GET_APPS = "-s %s shell pm list packages"
    GET_ACTIVITY_BY_PACKAGE = "-s %s shell cmd package resolve-activity --brief %s"
    CLEAN_PACKAGE_DATA = "-s %s shell pm clear %s"
    INPUT_TEXT = "-s %s shell input text %s"
    PULL_DATA = "-s %s pull %s %s "
    PUSH_DATA = "-s %s push %s %s "
    
    def _get_adb_platform(self) -> str:
        """取得 ADB 平台路徑"""
        from pathlib import Path
        import shutil
        import sys

        name = "adb.exe" if os.name == "nt" else "adb"
        root = Path(__file__).resolve().parents[4]
        candidates = [root / "platform-tools" / name]
        if getattr(sys, "frozen", False):
            candidates.insert(0, Path(sys.executable).resolve().parent / "platform-tools" / name)
        for key in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
            if os.environ.get(key):
                candidates.append(Path(os.environ[key]) / "platform-tools" / name)
        for candidate in candidates:
            if candidate.is_file():
                return f'"{candidate}" '
        found = shutil.which("adb")
        if found:
            return f'"{found}" '
        # Keep command construction usable for mock tests; execution fails clearly if absent.
        return "adb "

    def get_command(self) -> str:
        """取得命令字串"""
        return self._get_adb_platform() + self.value
    
    def get_command_with_device(self, device_id: str) -> str:
        """取得帶裝置 ID 的命令字串"""
        return (self._get_adb_platform() + self.value) % device_id
    
    def get_command_with_device_package(self, device_id: str, app_package: str) -> str:
        """取得帶裝置 ID 和應用套件名稱的命令字串"""
        return (self._get_adb_platform() + self.value) % (device_id, app_package)
    
    def get_command_with_device_coords(self, device_id: str, x: int, y: int) -> str:
        """取得帶裝置 ID 和座標的命令字串"""
        return (self._get_adb_platform() + self.value) % (device_id, x, y)
    
    def get_command_with_device_paths(self, device_id: str, path1: str, path2: str) -> str:
        """取得帶裝置 ID 和路徑的命令字串"""
        return (self._get_adb_platform() + self.value) % (device_id, path1, path2)
    
    def get_command_with_device_swipe(self, device_id: str, x1: int, y1: int, x2: int, y2: int, durations: int) -> str:
        """取得帶裝置 ID 和滑動參數的命令字串"""
        return (self._get_adb_platform() + self.value) % (device_id, x1, y1, x2, y2, durations)

