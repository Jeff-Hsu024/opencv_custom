"""
ADB 處理器 - 執行 ADB 命令
"""
from dataclasses import dataclass
import subprocess
from typing import Optional, Sequence
from .adb_command import AdbCommand


@dataclass(frozen=True)
class AdbProcessResult:
    """Typed result for an ADB subprocess invocation."""

    argv: list[str]
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out and self.error is None



class Adb:
    """ADB 處理器類別"""

    def __init__(self, device_id: str = None):
        self.device_id = device_id

    def connect(self):
        """嘗試連線至裝置 (如果是 IP)"""
        if self.device_id and ":" in self.device_id:
             self.exec(f"adb connect {self.device_id}")

    def _get_adb_bin(self) -> str:
        """取得 ADB 執行檔路徑"""
        from .adb_command import AdbCommand
        # 借用 AdbCommand 的路徑解析邏輯，但去掉尾端空格
        return AdbCommand.DEVICE_LIST._get_adb_platform().strip()

    def run_argv(
        self,
        argv: Sequence[str],
        *,
        timeout: Optional[float] = 30.0,
        serial: Optional[str] = None,
    ) -> AdbProcessResult:
        """Execute an ADB command using explicit argv without shell interpolation."""
        cmd = [str(part) for part in argv]
        if not cmd:
            raise ValueError("argv must not be empty")

        target_serial = serial if serial is not None else self.device_id
        if target_serial and "-s" not in cmd:
            cmd[1:1] = ["-s", target_serial]

        try:
            result = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
            )
            return AdbProcessResult(
                argv=cmd,
                returncode=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )
        except subprocess.TimeoutExpired as exc:
            stdout = exc.stdout if isinstance(exc.stdout, str) else (exc.stdout.decode("utf-8", errors="replace") if exc.stdout else "")
            stderr = exc.stderr if isinstance(exc.stderr, str) else (exc.stderr.decode("utf-8", errors="replace") if exc.stderr else "")
            return AdbProcessResult(
                argv=cmd,
                returncode=-1,
                stdout=stdout,
                stderr=stderr,
                timed_out=True,
                error=f"Command timed out after {timeout}s",
            )
        except OSError as exc:
            return AdbProcessResult(
                argv=cmd,
                returncode=-1,
                stdout="",
                stderr=str(exc),
                timed_out=False,
                error=str(exc),
            )

    def exec(self, command: str) -> str:
        """
        執行 ADB 命令
        
        Args:
            command: ADB 命令字串
            
        Returns:
            標準輸出字串
        """
        adb_bin = self._get_adb_bin()
        
        # 1. 統一將 "adb " 換成完整的 adb_bin 路徑
        if command.strip().startswith("adb "):
            command = command.strip().replace("adb ", f"{adb_bin} ", 1)
        
        # 2. 如果有指定 device_id 且命令中還沒有 -s，則注入 -s
        if self.device_id and adb_bin in command and " -s " not in command:
            # 在 adb_bin 後注入 -s id
            command = command.replace(adb_bin, f"{adb_bin} -s {self.device_id}", 1)
        
        try:
            result = subprocess.run(
                command,
                shell=True,
                capture_output=True,
                text=True,
                encoding='utf-8',
                errors='replace'  # 使用 replace 來處理編碼錯誤
            )
            stdout = result.stdout if result.stdout else result.stderr
            return stdout if stdout else ""
        except Exception as e:
            print(f"Error executing command: {e}")
            return f"something error : {e}"
    
    def get_snapshot(self, device_id: str, timeout: Optional[float] = 10.0) -> Optional[bytes]:
        """
        取得 Android 裝置截圖
        
        Args:
            device_id: ADB 裝置 ID
            timeout: 命令超時秒數
            
        Returns:
            截圖位元組陣列，失敗時返回 None
        """
        try:
            argv = AdbCommand.SCREEN_CAP.get_argv(device_id=device_id)
            result = subprocess.run(
                argv,
                shell=False,
                capture_output=True,
                timeout=timeout,
            )
            if result.returncode != 0:
                print(f"截圖命令失敗，返回碼: {result.returncode}")
            return result.stdout if result.returncode == 0 and result.stdout else None
        except subprocess.TimeoutExpired:
            print("DEBUG: 截圖命令超時")
            return None
        except Exception as e:
            print(f"Error getting snapshot: {e}")
            import traceback
            traceback.print_exc()
            return None

