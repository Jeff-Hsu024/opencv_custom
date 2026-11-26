"""
OpenCV 服務 - 提供影像匹配與 OCR 功能
"""
import cv2
import numpy as np
from typing import Optional, Union
from .mat_utility import MatUtility
from .dto import MatchPattern, MatchResult, OcrRegion
from .ocr.character_ocr import CharacterOCR
from .ocr.pattern_ocr import PatternOCR


class OpenCvService:
    """OpenCV 服務類別"""
    
    def __init__(self):
        self.character_ocr = CharacterOCR()
        self.pattern_ocr = PatternOCR()
    
    def find_match(self, source: np.ndarray, target: np.ndarray) -> MatchPattern:
        """
        在來源影像中尋找目標影像
        
        Args:
            source: 來源影像 Mat
            target: 目標影像 Mat
            
        Returns:
            MatchPattern 物件
        """
        match_method = cv2.TM_SQDIFF_NORMED
        
        result = cv2.matchTemplate(source, target, match_method)
        min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(result)
        
        # 計算中心點
        point = (min_loc[0] + target.shape[1] / 2.0, 
                 min_loc[1] + target.shape[0] / 2.0)
        
        return MatchPattern(min_val, point)

    @staticmethod
    def _validate_image(img: np.ndarray, name: str) -> None:
        if not isinstance(img, np.ndarray) or img.size == 0:
            raise ValueError(f"{name} must be a non-empty numpy.ndarray")
        if img.ndim not in (2, 3):
            raise ValueError(f"{name} must be 2D or 3D array, got {img.ndim}D")
        if img.shape[0] <= 0 or img.shape[1] <= 0:
            raise ValueError(f"{name} must have positive height and width, got {img.shape}")
        if img.ndim == 3 and img.shape[2] not in (1, 3, 4):
            raise ValueError(f"{name} must have 1, 3, or 4 channels, got {img.shape[2]}")

    @staticmethod
    def _to_gray(img: np.ndarray) -> np.ndarray:
        if img.ndim == 2:
            return img
        if img.shape[2] == 1:
            return img[:, :, 0]
        if img.shape[2] == 3:
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)

    @staticmethod
    def _to_bgr(img: np.ndarray, name: str) -> np.ndarray:
        if img.ndim != 3 or img.shape[2] not in (3, 4):
            raise ValueError(f"{name} must be a 3-channel BGR (or 4-channel BGRA) image for color_mode='bgr'")
        if img.shape[2] == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
        return img

    def match_template(
        self,
        source: np.ndarray,
        target: np.ndarray,
        threshold: float = 0.8,
        color_mode: str = "gray",
    ) -> Optional[MatchResult]:
        """Match target template within source image and return a structured result.

        Args:
            source: Source image array.
            target: Target template image array.
            threshold: Minimum similarity score in [0.0, 1.0] (higher is better).
            color_mode: Explicit color space for matching: 'gray' or 'bgr'.

        Returns:
            MatchResult if best score >= threshold, else None.
        """
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not (0.0 <= float(threshold) <= 1.0):
            raise ValueError(f"threshold must be a float in [0.0, 1.0], got {threshold!r}")
        if color_mode not in ("gray", "bgr"):
            raise ValueError(f"color_mode must be 'gray' or 'bgr', got {color_mode!r}")

        self._validate_image(source, "source")
        self._validate_image(target, "target")

        sh, sw = source.shape[:2]
        th, tw = target.shape[:2]
        if th > sh or tw > sw:
            raise ValueError(
                f"target size ({tw}x{th}) cannot exceed source size ({sw}x{sh})"
            )

        if color_mode == "gray":
            src_mat = self._to_gray(source)
            tgt_mat = self._to_gray(target)
        else:
            src_mat = self._to_bgr(source, "source")
            tgt_mat = self._to_bgr(target, "target")

        result = cv2.matchTemplate(src_mat, tgt_mat, cv2.TM_SQDIFF_NORMED)
        min_val, _, min_loc, _ = cv2.minMaxLoc(result)
        score = max(0.0, min(1.0, 1.0 - float(min_val)))

        if score < float(threshold):
            return None

        x1, y1 = int(min_loc[0]), int(min_loc[1])
        x2, y2 = x1 + int(tw), y1 + int(th)
        center = (x1 + tw / 2.0, y1 + th / 2.0)
        return MatchResult(score=score, bbox=(x1, y1, x2, y2), center=center)
    
    def ocr_character(self, 
                     ocr_templates_path: str, 
                     source_path: str, 
                     ocr_region: OcrRegion, 
                     threshold: float) -> str:
        """
        從來源影像路徑進行 OCR 字元辨識
        
        Args:
            ocr_templates_path: OCR 模板基礎路徑
            source_path: 來源影像路徑
            ocr_region: OCR 區域
            threshold: 閾值
            
        Returns:
            OCR 辨識結果
        """
        target_img = MatUtility.slice_region_mat(source_path, ocr_region)
        character_ocr = CharacterOCR()
        return character_ocr.execute_ocr(ocr_templates_path, target_img, threshold)
    
    def ocr_character_from_mat(self, 
                               ocr_templates_path: str, 
                               source: np.ndarray, 
                               ocr_region: OcrRegion, 
                               threshold: float) -> str:
        """
        從來源 Mat 進行 OCR 字元辨識
        
        Args:
            ocr_templates_path: OCR 模板基礎路徑
            source: 來源影像 Mat
            ocr_region: OCR 區域
            threshold: 閾值
            
        Returns:
            OCR 辨識結果
        """
        target_img = MatUtility.slice_region_mat_from_source(source, ocr_region)
        return self.character_ocr.execute_ocr(ocr_templates_path, target_img, threshold)
    
    def ocr_pattern(self, 
                   ocr_templates_path: str, 
                   source_path: str, 
                   ocr_region: OcrRegion, 
                   threshold: float) -> str:
        """
        從來源影像路徑進行 OCR 圖案辨識
        
        Args:
            ocr_templates_path: OCR 模板基礎路徑
            source_path: 來源影像路徑
            ocr_region: OCR 區域
            threshold: 閾值
            
        Returns:
            OCR 辨識結果
        """
        target_img = MatUtility.slice_region_mat(source_path, ocr_region)
        return self.pattern_ocr.execute_ocr(ocr_templates_path, target_img, threshold)
    
    def ocr_pattern_from_mat(self, 
                            ocr_templates_path: str, 
                            source: np.ndarray, 
                            ocr_region: OcrRegion, 
                            threshold: float) -> str:
        """
        從來源 Mat 進行 OCR 圖案辨識
        
        Args:
            ocr_templates_path: OCR 模板基礎路徑
            source: 來源影像 Mat
            ocr_region: OCR 區域
            threshold: 閾值
            
        Returns:
            OCR 辨識結果
        """
        target_img = MatUtility.slice_region_mat_from_source(source, ocr_region)
        return self.pattern_ocr.execute_ocr(ocr_templates_path, target_img, threshold)

