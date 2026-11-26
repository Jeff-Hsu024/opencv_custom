"""
Mat 工具類別 - 提供 OpenCV Mat 相關工具函數
"""
import math
import cv2
import numpy as np
from pathlib import Path
from typing import Optional, Tuple, Union


class MatUtility:
    """OpenCV Mat 工具類別"""
    
    @staticmethod
    def get_mat_from_file(file_path: str) -> np.ndarray:
        """
        從檔案路徑載入 Mat 物件（灰階）
        支援中文路徑
        """
        # 使用 numpy fromfile 繞過 cv2.imread 對中文路徑的限制
        img_array = np.fromfile(file_path, np.uint8)
        return cv2.imdecode(img_array, cv2.IMREAD_GRAYSCALE)
    
    @staticmethod
    def get_mat_from_file_with_mask(file_path: str) -> np.ndarray:
        """
        從檔案路徑載入 Mat 物件（支援 Alpha 通道遮罩）
        支援中文路徑
        """
        # 使用 numpy fromfile 繞過 cv2.imread 對中文路徑的限制
        img_array = np.fromfile(file_path, np.uint8)
        img = cv2.imdecode(img_array, cv2.IMREAD_UNCHANGED)
        
        if img is None:
            raise RuntimeError(f"Error: Could not load image {file_path}")
        
        # 如果有 Alpha 通道（4 通道 RGBA）
        if len(img.shape) == 3 and img.shape[2] == 4:
            # 提取 Alpha 通道作為遮罩
            alpha = img[:, :, 3]
            # 轉換為 BGR
            bgr = cv2.cvtColor(img[:, :, :3], cv2.COLOR_BGRA2BGR)
            # 轉換為灰階
            gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
            # 創建白色背景
            processed_mat = np.full(gray.shape, 255, dtype=np.uint8)
            # 將前景複製到白色背景上（使用 Alpha 遮罩）
            processed_mat[alpha > 0] = gray[alpha > 0]
            return processed_mat
        else:
            # 直接載入為灰階
            return cv2.cvtColor(img, cv2.COLOR_BGR2GRAY) if len(img.shape) == 3 else img
    
    @staticmethod
    def convert_bytes_to_mat(bytes_data: bytes) -> Optional[np.ndarray]:
        """
        將位元組陣列轉換為 Mat 物件（灰階，保留相容性）
        
        Args:
            bytes_data: 位元組陣列
            
        Returns:
            灰階 Mat 物件，失敗時返回 None
        """
        if not bytes_data:
            return None
        nparr = np.frombuffer(bytes_data, np.uint8)
        decoded = cv2.imdecode(nparr, cv2.IMREAD_GRAYSCALE)
        return decoded

    @staticmethod
    def convert_bytes_to_bgr_mat(bytes_data: bytes) -> Optional[np.ndarray]:
        """
        將位元組陣列轉換為 BGR 彩色 Mat 物件

        Args:
            bytes_data: 位元組陣列

        Returns:
            BGR Mat 物件 (H, W, 3)，失敗時返回 None
        """
        if not bytes_data:
            return None
        nparr = np.frombuffer(bytes_data, np.uint8)
        decoded = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        return decoded
    
    @staticmethod
    def crop(source: np.ndarray, region) -> np.ndarray:
        """
        Crop a half-open Region (x1, y1, x2, y2) from source Mat, returning an independent copy.
        """
        if not isinstance(source, np.ndarray) or source.ndim not in (2, 3) or source.size == 0:
            raise ValueError("source must be a non-empty 2D or 3D numpy.ndarray")
        if region is None:
            raise ValueError("region must not be None")

        x1, y1, x2, y2 = region.x1, region.y1, region.x2, region.y2
        for name, val in (("x1", x1), ("y1", y1), ("x2", x2), ("y2", y2)):
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValueError(f"region.{name} must be an integer, got {type(val).__name__}")

        if x1 < 0 or y1 < 0:
            raise ValueError(f"region coordinates must be non-negative: ({x1}, {y1}, {x2}, {y2})")
        if x2 <= x1 or y2 <= y1:
            raise ValueError(f"region must have positive area (x2 > x1 and y2 > y1): ({x1}, {y1}, {x2}, {y2})")

        h, w = source.shape[:2]
        if x2 > w or y2 > h:
            raise ValueError(f"region ({x1}, {y1}, {x2}, {y2}) out of bounds for image size ({w}, {h})")

        return source[y1:y2, x1:x2].copy()

    @staticmethod
    def slice_region_mat(source_path: str, region) -> np.ndarray:
        """
        從來源影像中切片指定區域
        
        Args:
            source_path: 來源影像路徑
            region: Region 或 OcrRegion 物件
            
        Returns:
            切片後的 Mat (獨立複本)
        """
        source = MatUtility.get_mat_from_file_with_mask(source_path)
        return MatUtility.crop(source, region)
    
    @staticmethod
    def slice_region_mat_from_source(source: np.ndarray, region) -> np.ndarray:
        """
        從來源 Mat 中切片指定區域
        
        Args:
            source: 來源 Mat
            region: Region 或 OcrRegion 物件
            
        Returns:
            切片後的 Mat (獨立複本)
        """
        return MatUtility.crop(source, region)
    
    @staticmethod
    def save_slice_region_mat(source_path: str, region, file_name: str) -> None:
        """
        從來源影像中切片指定區域並儲存
        
        Args:
            source_path: 來源影像路徑
            region: OcrRegion 物件
            file_name: 儲存檔名
        """
        sliced = MatUtility.slice_region_mat(source_path, region)
        MatUtility.write_to_file(file_name, sliced)
    
    @staticmethod
    def write_to_file(file_path: str, mat: np.ndarray) -> Path:
        """
        將 Mat 寫入檔案 (支援中文路徑)
        """
        is_success, im_buf_arr = cv2.imencode(Path(file_path).suffix, mat)
        if not is_success:
            raise RuntimeError("error when encode image")
        im_buf_arr.tofile(file_path)
        return Path(file_path)

    @staticmethod
    def _validate_mat(mat: np.ndarray, name: str = "mat") -> None:
        """Validate that mat is a non-empty 2D or 3D uint8 numpy.ndarray."""
        if not isinstance(mat, np.ndarray):
            raise ValueError(f"{name} must be a numpy.ndarray, got {type(mat).__name__}")
        if mat.ndim not in (2, 3):
            raise ValueError(f"{name} must be 2D or 3D, got {mat.ndim}D")
        if mat.size == 0:
            raise ValueError(f"{name} must not be empty")
        if mat.dtype != np.uint8:
            raise ValueError(f"{name} must have dtype uint8, got {mat.dtype}")
        if mat.ndim == 3 and mat.shape[2] not in (1, 3, 4):
            raise ValueError(f"{name} must have 1, 3, or 4 channels, got {mat.shape[2]}")

    @staticmethod
    def resize(
        source: np.ndarray,
        *,
        size: Optional[Tuple[int, int]] = None,
        scale: Optional[float] = None,
        interpolation: int = cv2.INTER_LINEAR,
    ) -> np.ndarray:
        """
        Resize a Mat by explicit (width, height) size or uniform scale factor.
        Exactly one of size or scale must be provided.
        """
        MatUtility._validate_mat(source, "source")
        if (size is None) == (scale is None):
            raise ValueError("Exactly one of 'size' or 'scale' must be provided")

        if size is not None:
            if not isinstance(size, (tuple, list)) or len(size) != 2:
                raise ValueError("size must be a (width, height) tuple of 2 integers")
            w, h = size
            if not isinstance(w, int) or isinstance(w, bool) or not isinstance(h, int) or isinstance(h, bool):
                raise ValueError("size dimensions must be integers")
            if w <= 0 or h <= 0:
                raise ValueError(f"size dimensions must be positive, got ({w}, {h})")
            target_size = (w, h)
        else:
            if not isinstance(scale, (int, float)) or isinstance(scale, bool):
                raise ValueError(f"scale must be a number, got {type(scale).__name__}")
            if not math.isfinite(scale) or scale <= 0:
                raise ValueError(f"scale must be a positive finite number, got {scale}")
            src_h, src_w = source.shape[:2]
            new_w = max(1, int(round(src_w * scale)))
            new_h = max(1, int(round(src_h * scale)))
            target_size = (new_w, new_h)

        return cv2.resize(source, target_size, interpolation=interpolation)

    @staticmethod
    def encode_png(mat: np.ndarray) -> bytes:
        """Encode a Mat to PNG bytes, preserving color channels."""
        MatUtility._validate_mat(mat, "mat")
        ok, buf = cv2.imencode(".png", mat)
        if not ok:
            raise RuntimeError("Failed to encode image as PNG")
        return buf.tobytes()

    @staticmethod
    def decode_png(data: bytes) -> np.ndarray:
        """Decode PNG bytes to a Mat, preserving color channels."""
        if not isinstance(data, (bytes, bytearray)) or len(data) == 0:
            raise ValueError("data must be non-empty bytes")
        nparr = np.frombuffer(data, dtype=np.uint8)
        mat = cv2.imdecode(nparr, cv2.IMREAD_UNCHANGED)
        if mat is None:
            raise ValueError("Failed to decode PNG bytes")
        return mat

    @staticmethod
    def encode_jpeg(mat: np.ndarray, quality: int = 95) -> bytes:
        """Encode a Mat to JPEG bytes with explicit quality (0..100)."""
        MatUtility._validate_mat(mat, "mat")
        if not isinstance(quality, int) or isinstance(quality, bool) or not (0 <= quality <= 100):
            raise ValueError(f"quality must be an integer between 0 and 100, got {quality!r}")
        ok, buf = cv2.imencode(".jpg", mat, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
        if not ok:
            raise RuntimeError("Failed to encode image as JPEG")
        return buf.tobytes()

    @staticmethod
    def save(
        file_path: Union[str, Path],
        mat: np.ndarray,
        *,
        quality: Optional[int] = None,
    ) -> Path:
        """
        Save a Mat to file_path (supporting Unicode paths and optional JPEG quality).
        """
        MatUtility._validate_mat(mat, "mat")
        if not isinstance(file_path, (str, Path)) or not str(file_path).strip():
            raise ValueError("file_path must be a non-empty string or Path")
        path = Path(file_path)
        ext = path.suffix.lower()
        if not ext:
            raise ValueError("file_path must have an image extension (e.g. .png, .jpg)")

        params = []
        if quality is not None:
            if not isinstance(quality, int) or isinstance(quality, bool) or not (0 <= quality <= 100):
                raise ValueError(f"quality must be an integer between 0 and 100, got {quality!r}")
            if ext not in (".jpg", ".jpeg"):
                raise ValueError("quality is only supported for JPEG (.jpg/.jpeg) files")
            params = [int(cv2.IMWRITE_JPEG_QUALITY), quality]

        if path.parent and str(path.parent) != ".":
            path.parent.mkdir(parents=True, exist_ok=True)

        ok, buf = cv2.imencode(ext, mat, params)
        if not ok:
            raise RuntimeError(f"Failed to encode image for {path}")
        buf.tofile(str(path))
        return path

    @staticmethod
    def load(
        file_path: Union[str, Path],
        *,
        flags: int = cv2.IMREAD_UNCHANGED,
    ) -> np.ndarray:
        """
        Load a Mat from file_path (supporting Unicode paths).
        """
        if not isinstance(file_path, (str, Path)) or not str(file_path).strip():
            raise ValueError("file_path must be a non-empty string or Path")
        path = Path(file_path)
        if not path.is_file():
            raise FileNotFoundError(f"Image file not found: {path}")
        img_array = np.fromfile(str(path), dtype=np.uint8)
        if img_array.size == 0:
            raise ValueError(f"Image file is empty: {path}")
        mat = cv2.imdecode(img_array, flags)
        if mat is None:
            raise ValueError(f"Failed to decode image file: {path}")
        return mat

