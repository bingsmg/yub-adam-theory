"""General-purpose decorators: retry, fallback, timeout."""

from __future__ import annotations

import time
from collections.abc import Callable
from functools import wraps

from loguru import logger


def safe_fetch(default_return: Callable | None = None, max_retries: int = 2):
    """
    Decorator: wrap API-calling functions with retry + graceful fallback.

    On persistent failure after all retries, returns default_return() or None.
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception: Exception | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        wait = (attempt + 1) * 2  # 2s, 4s
                        logger.warning(
                            "Retry {}/{} for {}: {}",
                            attempt + 1, max_retries, func.__name__, e
                        )
                        time.sleep(wait)
            logger.error(
                "All {} retries failed for {}: {}",
                max_retries, func.__name__, last_exception
            )
            if default_return is not None:
                return default_return()
            return None
        return wrapper
    return decorator
