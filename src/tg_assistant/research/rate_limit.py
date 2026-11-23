from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass


@dataclass
class RateLimitResult:
    allowed: bool
    retry_after: float = 0.0


class SlidingWindowLimiter:
    def __init__(self, max_calls: int, window_seconds: int):
        self.max_calls = max(1, max_calls)
        self.window_seconds = max(1, window_seconds)
        self._events: dict[int, deque[float]] = defaultdict(deque)

    def check(self, key: int, now: float | None = None) -> RateLimitResult:
        current = now if now is not None else time.monotonic()
        bucket = self._events[key]
        cutoff = current - self.window_seconds
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= self.max_calls:
            retry_after = max(0.0, self.window_seconds - (current - bucket[0]))
            return RateLimitResult(allowed=False, retry_after=retry_after)
        bucket.append(current)
        return RateLimitResult(allowed=True)
