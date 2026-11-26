"""Tests for OPT-01: bounded invalidating cache, color/multiscale matching, and benchmarks."""
import cv2
import numpy as np
import pytest

from benchmarks.bench_opencv import run_benchmarks
from service.core.opencv.cache import BoundedImageCache, compute_image_digest
from service.core.opencv.open_cv_service import OpenCvService


def test_bounded_cache_eviction_and_invalidation():
    cache = BoundedImageCache(max_entries=2)
    cache.put("a", 1)
    cache.put("b", 2)
    assert cache.get("a") == 1  # "a" is now most recently used
    cache.put("c", 3)  # evicts "b"
    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
    assert cache.stats["evictions"] == 1
    assert cache.invalidate("a") is True
    assert cache.get("a") is None
    cache.clear()
    assert cache.stats["size"] == 0


def test_cached_match_invalidates_on_image_change():
    svc = OpenCvService(cache_max_entries=8)
    rng = np.random.default_rng(7)
    source = rng.integers(0, 256, size=(200, 300, 3), dtype=np.uint8)
    template = source[40:80, 60:110].copy()

    res1 = svc.match_template(source, template, threshold=0.95, color_mode="gray")
    assert res1 is not None
    assert res1.bbox == (60, 40, 110, 80)

    # Repeat same call -> cache hits
    hits_before = svc.cache.stats["hits"]
    res2 = svc.match_template(source, template, threshold=0.95, color_mode="gray")
    assert res2 == res1
    assert svc.cache.stats["hits"] > hits_before

    # Mutate source content -> content digest changes -> automatic invalidation
    mutated = source.copy()
    mutated[40:80, 60:110] = 0
    res3 = svc.match_template(mutated, template, threshold=0.95, color_mode="gray")
    assert res3 is None


def test_hsv_color_mode_distinguishes_hue():
    svc = OpenCvService()
    # Two patches with identical grayscale luminance but distinct hues (blue vs red)
    source = np.zeros((120, 200, 3), dtype=np.uint8)
    # Blue-ish patch at (20, 20)
    source[20:60, 20:60] = (200, 50, 50)
    # Red-ish patch at (120, 20)
    source[20:60, 120:160] = (50, 50, 200)
    target = np.full((40, 40, 3), (50, 50, 200), dtype=np.uint8)

    res = svc.match_template(source, target, threshold=0.95, color_mode="hsv")
    assert res is not None
    assert res.bbox == (120, 20, 160, 60)


def test_multiscale_match_finds_scaled_template():
    svc = OpenCvService()
    rng = np.random.default_rng(123)
    source = rng.integers(0, 256, size=(240, 320, 3), dtype=np.uint8)
    base_template = rng.integers(0, 256, size=(40, 40, 3), dtype=np.uint8)
    scaled_patch = cv2.resize(base_template, (60, 60), interpolation=cv2.INTER_LINEAR)
    source[80:140, 100:160] = scaled_patch

    res = svc.match_template_multiscale(
        source,
        base_template,
        scales=(1.0, 1.5, 2.0),
        threshold=0.85,
        color_mode="bgr",
    )
    assert res is not None
    assert res.scale == pytest.approx(1.5)
    assert res.bbox == (100, 80, 160, 140)


def test_multiscale_rejects_invalid_scales():
    svc = OpenCvService()
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        svc.match_template_multiscale(img, img, scales=())
    with pytest.raises(ValueError):
        svc.match_template_multiscale(img, img, scales=(0.0, 1.0))


def test_benchmark_runner_smoke():
    rows = run_benchmarks(iterations=2)
    assert len(rows) == 4
    for row in rows:
        assert row["mean_ms"] >= 0.0
