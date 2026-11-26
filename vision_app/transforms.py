"""Composable coordinate transforms from frame-local to source coordinates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Tuple


@dataclass(frozen=True)
class CoordinateTransform:
    """Affine axis-aligned transform mapping local (x, y) to source (x, y).

    Mapping formula:
        source_x = offset_x + local_x * scale_x
        source_y = offset_y + local_y * scale_y

    Pixel coordinates are rounded to nearest integer via ``round()`` when
    converting to discrete pixel indices.
    """

    offset_x: float = 0.0
    offset_y: float = 0.0
    scale_x: float = 1.0
    scale_y: float = 1.0

    def compose(self, child: CoordinateTransform) -> CoordinateTransform:
        """Compose this transform (parent->source) with a child transform (child->parent)."""
        return CoordinateTransform(
            offset_x=self.offset_x + child.offset_x * self.scale_x,
            offset_y=self.offset_y + child.offset_y * self.scale_y,
            scale_x=self.scale_x * child.scale_x,
            scale_y=self.scale_y * child.scale_y,
        )

    @classmethod
    def for_crop(cls, x1: int, y1: int) -> CoordinateTransform:
        """Return a local-to-parent transform for a crop starting at (x1, y1)."""
        return cls(offset_x=float(x1), offset_y=float(y1), scale_x=1.0, scale_y=1.0)

    @classmethod
    def for_resize(
        cls,
        src_width: int,
        src_height: int,
        dst_width: int,
        dst_height: int,
    ) -> CoordinateTransform:
        """Return a local-to-parent transform for resizing (src -> dst)."""
        if dst_width <= 0 or dst_height <= 0:
            raise ValueError(f"Destination dimensions must be positive, got ({dst_width}, {dst_height})")
        if src_width <= 0 or src_height <= 0:
            raise ValueError(f"Source dimensions must be positive, got ({src_width}, {src_height})")
        return cls(
            offset_x=0.0,
            offset_y=0.0,
            scale_x=src_width / dst_width,
            scale_y=src_height / dst_height,
        )

    def map_point(self, x: float, y: float) -> Tuple[int, int]:
        """Map a local (x, y) point to rounded integer source coordinates."""
        return (int(round(self.offset_x + x * self.scale_x)), int(round(self.offset_y + y * self.scale_y)))

    def map_region(self, x1: int, y1: int, x2: int, y2: int) -> Tuple[int, int, int, int]:
        """Map a half-open local region [x1, y1, x2, y2) to source coordinates."""
        sx1, sy1 = self.map_point(x1, y1)
        sx2, sy2 = self.map_point(x2, y2)
        return (sx1, sy1, sx2, sy2)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "scale_x": self.scale_x,
            "scale_y": self.scale_y,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CoordinateTransform:
        return cls(
            offset_x=float(data.get("offset_x", 0.0)),
            offset_y=float(data.get("offset_y", 0.0)),
            scale_x=float(data.get("scale_x", 1.0)),
            scale_y=float(data.get("scale_y", 1.0)),
        )
