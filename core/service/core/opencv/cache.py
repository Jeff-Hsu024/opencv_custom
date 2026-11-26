"""Bounded LRU cache with content-based invalidation for OpenCV preprocessing."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
from typing import Any, Dict, Hashable, Optional, Tuple
import numpy as np


def compute_image_digest(img: np.ndarray) -> Tuple[Tuple[int, ...], str, bytes]:
    """Compute a deterministic content digest for a NumPy image array."""
    contiguous = np.ascontiguousarray(img)
    digest = hashlib.blake2b(contiguous.view(np.uint8), digest_size=16).digest()
    return (tuple(img.shape), str(img.dtype), digest)


class BoundedImageCache:
    """Bounded LRU cache with explicit and content-based invalidation."""

    def __init__(self, max_entries: int = 64) -> None:
        if isinstance(max_entries, bool) or not isinstance(max_entries, int) or max_entries < 0:
            raise ValueError(f"max_entries must be a non-negative integer, got {max_entries!r}")
        self._max_entries = max_entries
        self._entries: OrderedDict[Hashable, Any] = OrderedDict()
        self._hits = 0
        self._misses = 0
        self._evictions = 0

    @property
    def max_entries(self) -> int:
        return self._max_entries

    @property
    def stats(self) -> Dict[str, int]:
        return {
            "hits": self._hits,
            "misses": self._misses,
            "evictions": self._evictions,
            "size": len(self._entries),
            "max_entries": self._max_entries,
        }

    def get(self, key: Hashable) -> Optional[Any]:
        """Return cached value for key, or None on miss."""
        if self._max_entries == 0:
            self._misses += 1
            return None
        if key in self._entries:
            self._entries.move_to_end(key)
            self._hits += 1
            return self._entries[key]
        self._misses += 1
        return None

    def put(self, key: Hashable, value: Any) -> None:
        """Insert or update key in cache, evicting LRU entry if bounded."""
        if self._max_entries == 0:
            return
        if key in self._entries:
            self._entries.move_to_end(key)
            self._entries[key] = value
            return
        self._entries[key] = value
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)
            self._evictions += 1

    def invalidate(self, key: Hashable) -> bool:
        """Remove a specific key from the cache. Returns True if removed."""
        if key in self._entries:
            del self._entries[key]
            return True
        return False

    def clear(self) -> None:
        """Remove all entries from the cache."""
        self._entries.clear()
