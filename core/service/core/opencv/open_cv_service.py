"""
OpenCV 服務 - 提供影像匹配與 OCR 功能
"""
import cv2
import numpy as np
from typing import List, Optional, Sequence, Tuple, Union
from .cache import BoundedImageCache, compute_image_digest
from .mat_utility import MatUtility
from .dto import CompareResult, MatchPattern, MatchResult, OcrRegion
from .ocr.character_ocr import CharacterOCR
from .ocr.pattern_ocr import PatternOCR


class OpenCvService:
    """OpenCV 服務類別"""
    
    def __init__(self, cache_max_entries: int = 0):
        self.character_ocr = CharacterOCR()
        self.pattern_ocr = PatternOCR()
        self.cache = BoundedImageCache(max_entries=cache_max_entries)
    
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

    @staticmethod
    def _to_hsv(img: np.ndarray, name: str) -> np.ndarray:
        bgr = OpenCvService._to_bgr(img, name)
        return cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    def _convert_color(self, img: np.ndarray, color_mode: str, name: str) -> np.ndarray:
        if self.cache.max_entries > 0:
            key = ("color", color_mode, compute_image_digest(img))
            cached = self.cache.get(key)
            if cached is not None:
                return cached
        if color_mode == "gray":
            converted = self._to_gray(img)
        elif color_mode == "bgr":
            converted = self._to_bgr(img, name)
        else:
            converted = self._to_hsv(img, name)
        if self.cache.max_entries > 0:
            self.cache.put(key, converted)
        return converted

    def _prepare_and_match(
        self,
        source: np.ndarray,
        target: np.ndarray,
        threshold: float,
        color_mode: str,
    ) -> Tuple[np.ndarray, int, int]:
        """Validate inputs, convert color space, and compute TM_SQDIFF_NORMED score map."""
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not (0.0 <= float(threshold) <= 1.0):
            raise ValueError(f"threshold must be a float in [0.0, 1.0], got {threshold!r}")
        if color_mode not in ("gray", "bgr", "hsv"):
            raise ValueError(f"color_mode must be 'gray', 'bgr', or 'hsv', got {color_mode!r}")

        self._validate_image(source, "source")
        self._validate_image(target, "target")

        sh, sw = source.shape[:2]
        th, tw = target.shape[:2]
        if th > sh or tw > sw:
            raise ValueError(
                f"target size ({tw}x{th}) cannot exceed source size ({sw}x{sh})"
            )

        src_mat = self._convert_color(source, color_mode, "source")
        tgt_mat = self._convert_color(target, color_mode, "target")

        result = cv2.matchTemplate(src_mat, tgt_mat, cv2.TM_SQDIFF_NORMED)
        return result, int(tw), int(th)

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
        result, tw, th = self._prepare_and_match(source, target, threshold, color_mode)
        min_val, _, min_loc, _ = cv2.minMaxLoc(result)
        score = max(0.0, min(1.0, 1.0 - float(min_val)))

        if score < float(threshold):
            return None

        x1, y1 = int(min_loc[0]), int(min_loc[1])
        x2, y2 = x1 + tw, y1 + th
        center = (x1 + tw / 2.0, y1 + th / 2.0)
        return MatchResult(score=score, bbox=(x1, y1, x2, y2), center=center)

    def match_template_multiscale(
        self,
        source: np.ndarray,
        target: np.ndarray,
        scales: Sequence[float] = (0.8, 0.9, 1.0, 1.1, 1.2),
        threshold: float = 0.8,
        color_mode: str = "gray",
    ) -> Optional[MatchResult]:
        """Match target across multiple scale factors and return the best MatchResult.

        Args:
            source: Source image array.
            target: Target template image array.
            scales: Sequence of positive scale factors to evaluate.
            threshold: Minimum similarity score in [0.0, 1.0] (higher is better).
            color_mode: Explicit color space for matching: 'gray', 'bgr', or 'hsv'.

        Returns:
            Best MatchResult with populated scale if score >= threshold, else None.
        """
        if not scales:
            raise ValueError("scales must be a non-empty sequence of positive numbers")
        self._validate_image(source, "source")
        self._validate_image(target, "target")
        sh, sw = source.shape[:2]
        th, tw = target.shape[:2]

        best: Optional[MatchResult] = None
        for raw_scale in scales:
            if isinstance(raw_scale, bool) or not isinstance(raw_scale, (int, float)) or float(raw_scale) <= 0.0:
                raise ValueError(f"Each scale must be a positive number, got {raw_scale!r}")
            scale = float(raw_scale)
            scaled_w = max(1, int(round(tw * scale)))
            scaled_h = max(1, int(round(th * scale)))
            if scaled_w > sw or scaled_h > sh:
                continue
            if scale == 1.0:
                scaled_target = target
            else:
                interp = cv2.INTER_AREA if scale < 1.0 else cv2.INTER_LINEAR
                scaled_target = cv2.resize(target, (scaled_w, scaled_h), interpolation=interp)

            candidate = self.match_template(
                source,
                scaled_target,
                threshold=threshold,
                color_mode=color_mode,
            )
            if candidate is not None and (best is None or candidate.score > best.score):
                best = MatchResult(
                    score=candidate.score,
                    bbox=candidate.bbox,
                    center=candidate.center,
                    scale=scale,
                )
        return best

    def find_all(
        self,
        source: np.ndarray,
        target: np.ndarray,
        threshold: float = 0.8,
        max_results: int = 10,
        iou_threshold: float = 0.5,
        color_mode: str = "gray",
    ) -> List[MatchResult]:
        """Find all template matches above threshold with deterministic NMS.

        Args:
            source: Source image array.
            target: Target template image array.
            threshold: Minimum similarity score in [0.0, 1.0] (higher is better).
            max_results: Maximum number of matches to return (>= 1).
            iou_threshold: IoU threshold in [0.0, 1.0] for non-maximum suppression.
            color_mode: Explicit color space for matching: 'gray' or 'bgr'.

        Returns:
            List of MatchResult ordered by (-score, y1, x1), bounded by max_results.
        """
        if isinstance(max_results, bool) or not isinstance(max_results, int) or max_results < 1:
            raise ValueError(f"max_results must be an integer >= 1, got {max_results!r}")
        if isinstance(iou_threshold, bool) or not isinstance(iou_threshold, (int, float)) or not (0.0 <= float(iou_threshold) <= 1.0):
            raise ValueError(f"iou_threshold must be a float in [0.0, 1.0], got {iou_threshold!r}")

        result, tw, th = self._prepare_and_match(source, target, threshold, color_mode)
        score_map = np.clip(1.0 - result, 0.0, 1.0)
        ys, xs = np.where(score_map >= float(threshold))
        if len(xs) == 0:
            return []

        candidates = [
            (float(score_map[y, x]), int(x), int(y), int(x) + tw, int(y) + th)
            for y, x in zip(ys, xs)
        ]
        # Deterministic ordering: highest score first, then top-to-bottom, left-to-right.
        candidates.sort(key=lambda c: (-c[0], c[2], c[1]))

        kept: List[MatchResult] = []
        iou_thresh = float(iou_threshold)
        area_box = tw * th
        for score, x1, y1, x2, y2 in candidates:
            if len(kept) >= max_results:
                break
            suppressed = False
            for prev in kept:
                px1, py1, px2, py2 = prev.bbox
                inter_w = max(0, min(x2, px2) - max(x1, px1))
                inter_h = max(0, min(y2, py2) - max(y1, py1))
                inter_area = inter_w * inter_h
                if inter_area > 0:
                    union_area = 2 * area_box - inter_area
                    iou = inter_area / union_area if union_area > 0 else 0.0
                    if iou > iou_thresh:
                        suppressed = True
                        break
            if not suppressed:
                kept.append(
                    MatchResult(
                        score=score,
                        bbox=(x1, y1, x2, y2),
                        center=(x1 + tw / 2.0, y1 + th / 2.0),
                    )
                )
        return kept

    def compare_images(
        self,
        image_a: np.ndarray,
        image_b: np.ndarray,
        pixel_tolerance: int = 0,
        max_changed_ratio: float = 0.0,
    ) -> CompareResult:
        """Compare two images pixel-by-pixel and report changed-pixel ratio and tolerance.

        Args:
            image_a: First image array (2D or 3D with 1, 3, or 4 channels).
            image_b: Second image array with identical shape to image_a.
            pixel_tolerance: Non-negative per-channel absolute difference tolerance.
            max_changed_ratio: Maximum allowed changed-pixel ratio in [0.0, 1.0].

        Returns:
            CompareResult with changed_ratio, counts, tolerance, and within_tolerance.
        """
        if isinstance(pixel_tolerance, bool) or not isinstance(pixel_tolerance, int) or pixel_tolerance < 0:
            raise ValueError(f"pixel_tolerance must be a non-negative integer, got {pixel_tolerance!r}")
        if (
            isinstance(max_changed_ratio, bool)
            or not isinstance(max_changed_ratio, (int, float))
            or not (0.0 <= float(max_changed_ratio) <= 1.0)
        ):
            raise ValueError(f"max_changed_ratio must be a float in [0.0, 1.0], got {max_changed_ratio!r}")

        self._validate_image(image_a, "image_a")
        self._validate_image(image_b, "image_b")
        if image_a.shape != image_b.shape:
            raise ValueError(f"Image shapes must match: {image_a.shape} != {image_b.shape}")

        diff = np.abs(image_a.astype(np.int16) - image_b.astype(np.int16))
        if diff.ndim == 3:
            changed_mask = np.any(diff > pixel_tolerance, axis=2)
        else:
            changed_mask = diff > pixel_tolerance

        changed_pixels = int(np.count_nonzero(changed_mask))
        total_pixels = int(image_a.shape[0] * image_a.shape[1])
        changed_ratio = changed_pixels / total_pixels
        max_ratio_f = float(max_changed_ratio)
        return CompareResult(
            changed_ratio=changed_ratio,
            changed_pixels=changed_pixels,
            total_pixels=total_pixels,
            pixel_tolerance=pixel_tolerance,
            max_changed_ratio=max_ratio_f,
            within_tolerance=changed_ratio <= max_ratio_f,
        )
    
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

