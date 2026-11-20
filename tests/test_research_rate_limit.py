from __future__ import annotations

from tg_assistant.research.access import is_allowed
from tg_assistant.research.rate_limit import SlidingWindowLimiter


def test_allowlist():
    allowed = frozenset({100, 200})
    assert is_allowed(100, allowed)
    assert not is_allowed(300, allowed)
    assert not is_allowed(None, allowed)
    assert not is_allowed(100, frozenset())


def test_sliding_window_limiter():
    limiter = SlidingWindowLimiter(max_calls=2, window_seconds=10)
    assert limiter.check(1, now=0.0).allowed
    assert limiter.check(1, now=1.0).allowed
    denied = limiter.check(1, now=2.0)
    assert denied.allowed is False
    assert denied.retry_after == 8.0
    # other user is independent
    assert limiter.check(2, now=2.0).allowed
    # after the window the first event expires
    assert limiter.check(1, now=10.01).allowed
