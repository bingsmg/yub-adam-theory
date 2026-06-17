"""
Source selection strategies.

Configurable via settings.DATA_SOURCE_STRATEGY and DATA_SOURCE_ORDER.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import pandas as pd
from loguru import logger

from .base import DataSource


def _resolve_source(name: str) -> Optional[DataSource]:
    """Resolve a source name string to an instance."""
    from .baostock_source import BaostockDataSource
    from .akshare_source import AkshareDataSource
    from .ef_source import EfinanceDataSource

    registry = {
        "baostock": BaostockDataSource,
        "akshare": AkshareDataSource,
        "efinance": EfinanceDataSource,
    }

    cls = registry.get(name.lower())
    if cls is None:
        logger.warning(f"Unknown data source: {name}")
        return None

    source = cls()
    if not source.is_available():
        logger.info(f"Data source '{name}' is not available (not installed)")
        return None

    return source


def get_available_sources(order: Optional[list[str]] = None) -> list[DataSource]:
    """Return all available sources in the requested order.

    Sources that fail is_available() are silently skipped.
    """
    if order is None:
        from config.settings import settings
        order = list(settings.DATA_SOURCE_ORDER)

    sources: list[DataSource] = []
    for name in order:
        src = _resolve_source(name)
        if src is not None:
            sources.append(src)

    if not sources:
        raise RuntimeError(
            f"No available data sources from order={order}. "
            f"Install baostock and/or akshare."
        )

    return sources


def select_source(strategy: str = "priority") -> DataSource:
    """Select a single data source based on the configured strategy.

    Strategies:
      - 'priority': Return the first available source in DATA_SOURCE_ORDER.
      - 'fastest_first': Benchmark latency, pick the fastest responding source.
    """
    sources = get_available_sources()

    if strategy == "priority":
        best = sources[0]
        logger.info(f"Selected data source: {best.name} (priority strategy)")
        return best

    if strategy == "fastest_first":
        # Quick health check — fetch one known stock to measure latency
        test_symbol = "600519"  # Kweichow Moutai
        test_start = "2026-06-01"
        test_end = "2026-06-10"

        best_source = sources[0]
        best_time = float("inf")

        for src in sources:
            t0 = time.time()
            df = src.fetch_daily_kline(test_symbol, test_start, test_end)
            elapsed = time.time() - t0
            if df is not None and not df.empty and elapsed < best_time:
                best_time = elapsed
                best_source = src
            logger.info(f"  {src.name}: {elapsed:.2f}s {'(ok)' if df is not None else '(fail)'}")

        logger.info(f"Selected data source: {best_source.name} ({best_time:.2f}s fastest)")
        return best_source

    # Default: priority
    logger.warning(f"Unknown strategy '{strategy}', falling back to priority")
    return sources[0]


def fetch_with_fallback(
    symbol: str,
    start_date: str,
    end_date: str,
    sources: Optional[list[DataSource]] = None,
) -> Optional[pd.DataFrame]:
    """Try sources in order; return the first successful result."""
    if sources is None:
        sources = get_available_sources()

    for src in sources:
        try:
            df = src.fetch_daily_kline(symbol, start_date, end_date)
            if df is not None and not df.empty:
                return df
        except Exception:
            continue

    return None


def race_fetch(
    symbol: str,
    start_date: str,
    end_date: str,
    sources: Optional[list[DataSource]] = None,
) -> Optional[pd.DataFrame]:
    """Query all sources in parallel; return the fastest successful result."""
    if sources is None:
        sources = get_available_sources()

    if len(sources) == 1:
        return sources[0].fetch_daily_kline(symbol, start_date, end_date)

    def _fetch(src: DataSource):
        try:
            return src.fetch_daily_kline(symbol, start_date, end_date)
        except Exception:
            return None

    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        futures = {pool.submit(_fetch, src): src for src in sources}
        for future in as_completed(futures):
            result = future.result()
            if result is not None and not result.empty:
                src = futures[future]
                logger.debug(f"race: {src.name} won for {symbol}")
                # Cancel remaining futures (best-effort)
                for f in futures:
                    f.cancel()
                return result

    return None
