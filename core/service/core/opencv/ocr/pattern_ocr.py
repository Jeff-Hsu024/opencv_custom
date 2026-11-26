"""
圖案 OCR - 用於辨識圖案
"""
import cv2
import numpy as np
from .match_ocr_adaptor import MatchOCRAdaptor


class PatternOCR(MatchOCRAdaptor):
    """圖案 OCR 類別"""
    
    def execute_ocr(self, ocr_templates_path: str, target_img: np.ndarray, threshold: float) -> str:
        """
        執行圖案 OCR
        
        Args:
            ocr_templates_path: OCR 模板基礎路徑
            target_img: 目標影像
            threshold: 閾值
            
        Returns:
            辨識出的圖案名稱
        """
        self._validate_ocr_inputs(target_img, threshold)
        templates = self.load_template_mat_map(ocr_templates_path)
        
        if not templates:
            return ""
        
        target_gray = self._to_gray(target_img)
        result = ""
        
        # 遍歷所有模板進行匹配
        for pattern, template in templates.items():
            if template is None or template.size == 0:
                continue
            template_gray = self._to_gray(template)
            # 確保模板尺寸不超過目標影像
            if template_gray.shape[0] > target_gray.shape[0] or template_gray.shape[1] > target_gray.shape[1]:
                continue
            
            w = template_gray.shape[1]
            h = template_gray.shape[0]
            
            res = cv2.matchTemplate(target_gray, template_gray, cv2.TM_CCOEFF_NORMED)
            
            # 尋找所有匹配度高於閾值的位置（以矩陣大小為上限，並以 -2.0 遮罩避免 threshold=0 時無窮迴圈）
            found_positions = []
            max_iterations = res.size
            for _ in range(max_iterations):
                min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)
                if max_val >= threshold:
                    match_loc = max_loc
                    found_positions.append(match_loc[0])  # store x coordinate
                    cv2.rectangle(res, match_loc, (match_loc[0] + w, match_loc[1] + h), -2.0, -1)
                else:
                    break
            
            # 根據 x 座標排序並加到結果 (簡化版，假設只有一種 pattern)
            found_positions.sort()
            for _ in found_positions:
                result += pattern
        
        return result

