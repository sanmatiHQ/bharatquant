"""
Simple token-bucket rate limiter.
"""
from __future__ import annotations
import time
from collections import deque
from typing import Deque


class RateLimiter:
    """Token bucket limiter for request pacing.

    Example:
        limiter = RateLimiter(max_per_sec=3, max_per_min=180)
        if limiter.allow():
            # proceed
            ...
    """

    def __init__(self, max_per_sec: int, max_per_min: int) -> None:
        self.max_per_sec = max_per_sec
        self.max_per_min = max_per_min
        self._sec_window: Deque[float] = deque()
        self._min_window: Deque[float] = deque()

    def allow(self) -> bool:
        now = time.monotonic()
        self._cleanup(now)
        if len(self._sec_window) < self.max_per_sec and len(self._min_window) < self.max_per_min:
            self._sec_window.append(now)
            self._min_window.append(now)
            return True
        return False

    def _cleanup(self, now: float) -> None:
        one_sec_ago = now - 1.0
        one_min_ago = now - 60.0
        while self._sec_window and self._sec_window[0] <= one_sec_ago:
            self._sec_window.popleft()
        while self._min_window and self._min_window[0] <= one_min_ago:
            self._min_window.popleft()
