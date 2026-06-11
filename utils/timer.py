"""Rate limiting and timing utilities for akshare API calls."""

from __future__ import annotations

import random
import time
from collections.abc import Callable
from functools import wraps

from config.settings import settings


class RateLimiter:
    """Enforce minimum delay between API calls, with jitter."""

    def __init__(
        self,
        min_delay: float | None = None,
        max_delay: float | None = None,
    ):
        self.min_delay = min_delay if min_delay is not None else settings.AKSHARE_DELAY_MIN
        self.max_delay = max_delay if max_delay is not None else settings.AKSHARE_DELAY_MAX
        self._last_call: float = 0.0

    def wait(self) -> None:
        """Sleep if needed to maintain rate limit."""
        elapsed = time.time() - self._last_call
        if elapsed < self.min_delay:
            sleep_time = random.uniform(self.min_delay, self.max_delay)
            time.sleep(sleep_time)
        self._last_call = time.time()

    def reset(self) -> None:
        self._last_call = 0.0


# Global rate limiter instance
rate_limiter = RateLimiter()


def rate_limited(func: Callable) -> Callable:
    """Decorator: apply rate limiting to an API-calling function."""
    @wraps(func)
    def wrapper(*args, **kwargs):
        rate_limiter.wait()
        return func(*args, **kwargs)
    return wrapper
