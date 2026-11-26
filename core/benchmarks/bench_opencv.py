"""Benchmark and profile OpenCV template matching, comparison, and caching."""
from __future__ import annotations

import time
from typing import Dict, List, Tuple
import numpy as np

from service.core.opencv.open_cv_service import OpenCvService


def make_synthetic_scene(
    width: int = 1280,
    height: int = 720,
    template_size: Tuple[int, int] = (64, 64),
    seed: int = 42,
) -> Tuple[np.ndarray, np.ndarray]:
    """Create a deterministic synthetic BGR scene and embedded template."""
    rng = np.random.default_rng(seed)
    source = rng.integers(0, 256, size=(height, width, 3), dtype=np.uint8)
    tw, th = template_size
    x1, y1 = width // 3, height // 3
    template = source[y1 : y1 + th, x1 : x1 + tw].copy()
    return source, template


def benchmark_operation(name: str, fn, iterations: int = 10) -> Dict[str, float]:
    """Run fn() for iterations and return timing statistics in milliseconds."""
    # Warmup
    fn()
    times_ms: List[float] = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        fn()
        t1 = time.perf_counter()
        times_ms.append((t1 - t0) * 1000.0)
    return {
        "name": name,
        "iterations": float(iterations),
        "mean_ms": sum(times_ms) / len(times_ms),
        "min_ms": min(times_ms),
        "max_ms": max(times_ms),
    }


def run_benchmarks(iterations: int = 10) -> List[Dict[str, float]]:
    """Run standard OpenCvService benchmarks on 1280x720 synthetic frames."""
    svc = OpenCvService()
    source, template = make_synthetic_scene(1280, 720, (64, 64))
    source_b = source.copy()

    results = [
        benchmark_operation(
            "match_template(gray, 1280x720, 64x64)",
            lambda: svc.match_template(source, template, threshold=0.8, color_mode="gray"),
            iterations=iterations,
        ),
        benchmark_operation(
            "match_template(bgr, 1280x720, 64x64)",
            lambda: svc.match_template(source, template, threshold=0.8, color_mode="bgr"),
            iterations=iterations,
        ),
        benchmark_operation(
            "find_all(gray, 1280x720, 64x64)",
            lambda: svc.find_all(source, template, threshold=0.8, max_results=5, color_mode="gray"),
            iterations=iterations,
        ),
        benchmark_operation(
            "compare_images(1280x720)",
            lambda: svc.compare_images(source, source_b, pixel_tolerance=0, max_changed_ratio=0.0),
            iterations=iterations,
        ),
    ]
    return results


if __name__ == "__main__":
    for row in run_benchmarks(iterations=10):
        print(
            f"{row['name']}: mean={row['mean_ms']:.2f}ms "
            f"(min={row['min_ms']:.2f}ms, max={row['max_ms']:.2f}ms)"
        )
