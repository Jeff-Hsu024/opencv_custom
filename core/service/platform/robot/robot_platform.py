"""
Robot 平台服務 - 使用 pyautogui 控制本機桌面
"""
import uuid
import os
from typing import Optional, Tuple, Union
import numpy as np
from PIL import Image
import cv2

pyautogui = None


def _get_pyautogui():
    """Lazily import pyautogui so headless/ADB environments do not require it."""
    global pyautogui
    if pyautogui is None:
        try:
            import pyautogui as _pyautogui
            pyautogui = _pyautogui
        except ImportError as exc:
            raise ImportError(
                "pyautogui is required for RobotPlatform. "
                "Install desktop extras with: pip install .[desktop]"
            ) from exc
    return pyautogui
from ..platform_service import PlatformService
from service.core.opencv.open_cv_service import OpenCvService
from service.core.opencv.mat_utility import MatUtility
from service.core.opencv.dto import MatchPattern


class RobotPlatform(PlatformService):
    """Robot 平台服務類別 (Desktop)"""
    
    def __init__(self, open_cv_service: OpenCvService, failsafe: bool = True):
        """Initialize RobotPlatform.

        Args:
            open_cv_service: OpenCV service instance.
            failsafe: Enable pyautogui fail-safe (moving mouse to top-left corner
                aborts). Enabled by default for safety; pass ``failsafe=False``
                to explicitly opt out.
        """
        super().__init__(open_cv_service)
        self.failsafe = bool(failsafe)
        _get_pyautogui().FAILSAFE = self.failsafe

    def capabilities(self) -> dict:
        """Report Robot platform action capabilities and known limitations."""
        return {
            "long_press": False,
            "unicode_text": False,
            "failsafe": self.failsafe,
        }
    
    # --- 平台生命週期 ---
    
    def start(self) -> bool:
        return True

    def stop(self) -> bool:
        return True

    # --- 平台原子操作實作 ---

    def snapshot(self) -> Optional[np.ndarray]:
        """獲取螢幕截圖 Mat (BGR 格式)"""
        try:
            screenshot = _get_pyautogui().screenshot()
            screenshot_np = np.array(screenshot)
            # RGB 轉 BGR
            return cv2.cvtColor(screenshot_np, cv2.COLOR_RGB2BGR)
        except Exception as e:
            print(f"[Robot] Snapshot failed: {e}")
            return None

    def click(self, x: int, y: int) -> bool:
        """點擊本機座標"""
        try:
            _get_pyautogui().click(x, y)
            return True
        except Exception:
            return False

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> bool:
        """模擬拖曳/滑動"""
        if duration < 0:
            raise ValueError(f"duration must be non-negative, got {duration}")
        try:
            # duration 轉為秒
            pg = _get_pyautogui()
            pg.moveTo(x1, y1)
            pg.dragTo(x2, y2, duration=duration/1000.0)
            return True
        except Exception:
            return False

    def type_text(self, text: str) -> bool:
        """模擬鍵盤文字輸入"""
        try:
            _get_pyautogui().write(text)
            return True
        except Exception:
            return False

    def key_event(self, key_code: Union[int, str]) -> bool:
        """模擬按鍵事件"""
        try:
            # pyautogui.press 支援 'enter', 'esc' 等字串
            _get_pyautogui().press(str(key_code))
            return True
        except Exception:
            return False

