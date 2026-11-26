"""
OpenCV DTOs (Data Transfer Objects)
"""
from dataclasses import dataclass
from typing import Optional, Tuple


@dataclass
class MatchPattern:
    """影像匹配結果 (legacy)

    Attributes:
        similar: TM_SQDIFF_NORMED distance in [0.0, 1.0] (lower is better; 0.0 = exact match).
        point: Center coordinates (x, y) of the best match.
    """
    similar: float  # 相似度距離 (0-1, 越小越相似)
    point: Tuple[float, float]  # 匹配點座標 (x, y)

    def get_similar(self) -> float:
        """取得相似度 (轉換為 1.0 - similar，越大越相似，範圍 0.0..1.0)"""
        return 1.0 - self.similar


@dataclass
class MatchResult:
    """Structured template match result.

    Attributes:
        score: Normalized similarity score in [0.0, 1.0] (higher is better).
        bbox: Half-open integer bounding box (x1, y1, x2, y2).
        center: Center coordinates (x, y) of the matched region.
        scale: Optional scale factor used during matching.
    """
    score: float
    bbox: Tuple[int, int, int, int]
    center: Tuple[float, float]
    scale: Optional[float] = None


@dataclass
class CompareResult:
    """Structured image comparison result.

    Attributes:
        changed_ratio: Fraction of pixels differing beyond pixel_tolerance in [0.0, 1.0].
        changed_pixels: Number of differing pixels.
        total_pixels: Total number of pixels compared.
        pixel_tolerance: Per-channel absolute difference tolerance used.
        max_changed_ratio: Maximum allowed changed_ratio for within_tolerance.
        within_tolerance: True if changed_ratio <= max_changed_ratio.
    """
    changed_ratio: float
    changed_pixels: int
    total_pixels: int
    pixel_tolerance: int
    max_changed_ratio: float
    within_tolerance: bool


@dataclass
class Region:
    """Half-open integer ROI (x1, y1, x2, y2) with positive area."""
    x1: int
    y1: int
    x2: int
    y2: int

    def __post_init__(self) -> None:
        for name, val in (("x1", self.x1), ("y1", self.y1), ("x2", self.x2), ("y2", self.y2)):
            if not isinstance(val, int) or isinstance(val, bool):
                raise ValueError(f"Region.{name} must be an integer, got {type(val).__name__}")
        if self.x1 < 0 or self.y1 < 0:
            raise ValueError(f"Region coordinates must be non-negative: ({self.x1}, {self.y1}, {self.x2}, {self.y2})")
        if self.x2 <= self.x1 or self.y2 <= self.y1:
            raise ValueError(f"Region must have positive area (x2 > x1 and y2 > y1): ({self.x1}, {self.y1}, {self.x2}, {self.y2})")

    @property
    def width(self) -> int:
        return self.x2 - self.x1

    @property
    def height(self) -> int:
        return self.y2 - self.y1

    @property
    def area(self) -> int:
        return self.width * self.height

    def validate_bounds(self, width: int, height: int) -> None:
        """Validate that this region fits within [0, width) x [0, height)."""
        if self.x2 > width or self.y2 > height:
            raise ValueError(
                f"Region ({self.x1}, {self.y1}, {self.x2}, {self.y2}) out of bounds for size ({width}, {height})"
            )


@dataclass
class OcrRegion(Region):
    """OCR 區域定義 (Region 相容別名)"""

