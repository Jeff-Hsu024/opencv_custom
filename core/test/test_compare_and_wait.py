"""Tests for CORE-08: generic image compare and monotonic bounded wait_image."""
from typing import Optional, Tuple
import numpy as np
import pytest

from service.core.opencv.open_cv_service import OpenCvService
from service.platform import platform_service as platform_service_module
from service.platform.platform_service import PlatformService


class _DummyPlatform(PlatformService):
    def __init__(self, opencv_service: OpenCvService, find_results):
        super().__init__(opencv_service)
        self._find_results = list(find_results)
        self.find_calls = 0

    def start(self) -> bool:
        return True

    def stop(self) -> bool:
        return True

    def snapshot(self) -> Optional[np.ndarray]:
        return None

    def click(self, x: int, y: int) -> bool:
        return True

    def swipe(self, x1: int, y1: int, x2: int, y2: int, duration: int = 500) -> bool:
        return True

    def type_text(self, text: str) -> bool:
        return True

    def key_event(self, key_code) -> bool:
        return True

    def find_image(
        self,
        image_path: str,
        region=None,
        threshold: float = 0.9,
    ) -> Optional[Tuple[float, float]]:
        self.find_calls += 1
        if self.find_calls <= len(self._find_results):
            return self._find_results[self.find_calls - 1]
        return None


def test_compare_images_known_diff_ratios():
    svc = OpenCvService()
    img_a = np.zeros((2, 2, 3), dtype=np.uint8)
    img_b = np.zeros((2, 2, 3), dtype=np.uint8)

    res_same = svc.compare_images(img_a, img_b)
    assert res_same.changed_ratio == 0.0
    assert res_same.changed_pixels == 0
    assert res_same.total_pixels == 4
    assert res_same.within_tolerance is True

    # Change 1 of 4 pixels -> 0.25
    img_b[0, 0] = [10, 0, 0]
    res_quarter = svc.compare_images(img_a, img_b, pixel_tolerance=0, max_changed_ratio=0.25)
    assert res_quarter.changed_ratio == pytest.approx(0.25)
    assert res_quarter.changed_pixels == 1
    assert res_quarter.within_tolerance is True

    # Pixel tolerance=10 ignores diff of 10
    res_tol = svc.compare_images(img_a, img_b, pixel_tolerance=10, max_changed_ratio=0.0)
    assert res_tol.changed_ratio == 0.0
    assert res_tol.within_tolerance is True

    # Exceeds max_changed_ratio
    res_fail = svc.compare_images(img_a, img_b, pixel_tolerance=5, max_changed_ratio=0.1)
    assert res_fail.changed_ratio == pytest.approx(0.25)
    assert res_fail.within_tolerance is False


def test_compare_images_2d_grayscale():
    svc = OpenCvService()
    a = np.full((2, 2), 100, dtype=np.uint8)
    b = np.full((2, 2), 100, dtype=np.uint8)
    b[1, :] = 120  # 2 of 4 pixels changed
    res = svc.compare_images(a, b, pixel_tolerance=5, max_changed_ratio=0.5)
    assert res.changed_ratio == pytest.approx(0.5)
    assert res.changed_pixels == 2
    assert res.within_tolerance is True


def test_compare_images_invalid_shape_and_params():
    svc = OpenCvService()
    a = np.zeros((4, 4, 3), dtype=np.uint8)
    b_diff_size = np.zeros((4, 5, 3), dtype=np.uint8)
    b_diff_ch = np.zeros((4, 4, 1), dtype=np.uint8)

    with pytest.raises(ValueError, match="shapes must match"):
        svc.compare_images(a, b_diff_size)
    with pytest.raises(ValueError, match="shapes must match"):
        svc.compare_images(a, b_diff_ch)
    with pytest.raises(ValueError):
        svc.compare_images(np.array([], dtype=np.uint8), a)
    with pytest.raises(ValueError):
        svc.compare_images(a, a, pixel_tolerance=-1)
    with pytest.raises(ValueError):
        svc.compare_images(a, a, max_changed_ratio=1.5)


def test_wait_image_fake_clock_timeout_and_bounded_polling(monkeypatch):
    now = [100.0]
    sleeps = []

    def fake_monotonic():
        return now[0]

    def fake_sleep(dt: float):
        sleeps.append(dt)
        now[0] += dt

    monkeypatch.setattr(platform_service_module.time, "monotonic", fake_monotonic)
    monkeypatch.setattr(platform_service_module.time, "sleep", fake_sleep)

    platform = _DummyPlatform(OpenCvService(), [None, None, None, None])
    result = platform.wait_image("dummy.png", timeout=1.0, frequency=0.4)

    assert result is None
    assert platform.find_calls == 4
    assert sleeps == pytest.approx([0.4, 0.4, 0.2])


def test_wait_image_finds_on_second_attempt_and_max_attempts(monkeypatch):
    now = [0.0]
    sleeps = []

    monkeypatch.setattr(platform_service_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(platform_service_module.time, "sleep", lambda dt: (sleeps.append(dt), now.__setitem__(0, now[0] + dt)))

    platform = _DummyPlatform(OpenCvService(), [None, (12.0, 34.0)])
    pos = platform.wait_image("dummy.png", timeout=5.0, frequency=0.5)
    assert pos == (12.0, 34.0)
    assert platform.find_calls == 2
    assert sleeps == [0.5]

    # Bounded by max_attempts even when timeout is large
    platform2 = _DummyPlatform(OpenCvService(), [None, None, None])
    res2 = platform2.wait_image("dummy.png", timeout=100.0, frequency=0.5, max_attempts=2)
    assert res2 is None
    assert platform2.find_calls == 2


def test_wait_image_zero_timeout_and_invalid_args(monkeypatch):
    now = [50.0]
    sleeps = []
    monkeypatch.setattr(platform_service_module.time, "monotonic", lambda: now[0])
    monkeypatch.setattr(platform_service_module.time, "sleep", lambda dt: sleeps.append(dt))

    platform = _DummyPlatform(OpenCvService(), [None])
    assert platform.wait_image("dummy.png", timeout=0, frequency=0.5) is None
    assert platform.find_calls == 1
    assert sleeps == []

    with pytest.raises(ValueError):
        platform.wait_image("dummy.png", timeout=-1)
    with pytest.raises(ValueError):
        platform.wait_image("dummy.png", timeout=1, frequency=0)
    with pytest.raises(ValueError):
        platform.wait_image("dummy.png", timeout=1, frequency=0.5, max_attempts=0)
