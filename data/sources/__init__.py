"""
Data source abstraction layer.

Public API:
    get_fetcher()        → Return the best DataSource per config
    get_available_sources() → All available source instances
    DataSource            → ABC for custom implementations
"""

from __future__ import annotations

from .base import DataSource, normalize_columns, OUTPUT_COLUMNS
from .strategy import (
    get_available_sources,
    select_source,
    fetch_with_fallback,
    race_fetch,
)
from .parallel import fetch_batch_parallel


def get_fetcher(strategy: str | None = None, order: list[str] | None = None) -> DataSource:
    """Return the best available data source based on configuration.

    Uses config.settings.DATA_SOURCE_STRATEGY and DATA_SOURCE_ORDER
    unless overridden by arguments.

    Examples:
        fetcher = get_fetcher()                         # From config
        fetcher = get_fetcher(strategy="priority")      # Explicit strategy
        fetcher = get_fetcher(order=["baostock"])       # Force baostock
    """
    from config.settings import settings
    from .strategy import _resolve_source

    # If explicit order given, use it directly
    if order is not None:
        for name in order:
            src = _resolve_source(name)
            if src is not None:
                return src
        raise RuntimeError(f"No available source from order={order}")

    # Otherwise use config
    strat = strategy or settings.DATA_SOURCE_STRATEGY
    return select_source(strategy=strat)


__all__ = [
    "DataSource",
    "get_fetcher",
    "get_available_sources",
    "select_source",
    "fetch_with_fallback",
    "race_fetch",
    "fetch_batch_parallel",
    "normalize_columns",
    "OUTPUT_COLUMNS",
]
