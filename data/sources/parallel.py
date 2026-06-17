"""
Parallel batch fetch — source-agnostic concurrent fetching.

Uses ThreadPoolExecutor to query multiple symbols simultaneously.
Respects per-source rate limits via inter-request delay.
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

import pandas as pd
from loguru import logger


def fetch_batch_parallel(
    fetch_fn: Callable[[str, str, str], pd.DataFrame | None],
    symbols: list[str],
    start_date: str,
    end_date: str,
    max_workers: int = 8,
    delay_per_worker: float = 1.0,
    progress_every: int = 500,
) -> dict[str, pd.DataFrame]:
    """Fetch multiple symbols in parallel using a thread pool.

    The per-worker delay helps avoid triggering rate limits on
    shared-IP scrapers (akshare, efinance).

    Args:
        fetch_fn: Function (symbol, start, end) -> DataFrame | None.
        symbols: List of 6-digit stock codes.
        start_date, end_date: 'YYYY-MM-DD'.
        max_workers: Thread pool size.
        delay_per_worker: Delay BEFORE each fetch to spread load.
        progress_every: Log progress every N symbols.

    Returns:
        dict mapping symbol → DataFrame (failed symbols omitted).
    """
    if max_workers <= 1:
        # Fall back to sequential — simpler logging, same result
        results: dict[str, pd.DataFrame] = {}
        for i, sym in enumerate(symbols):
            if delay_per_worker > 0:
                time.sleep(delay_per_worker)
            df = fetch_fn(sym, start_date, end_date)
            if df is not None and not df.empty:
                results[sym] = df
            if (i + 1) % progress_every == 0:
                logger.info(f"  parallel: {i+1}/{len(symbols)} — {len(results)} ok")
        return results

    results: dict[str, pd.DataFrame] = {}
    done = 0
    t0 = time.time()

    def _worker(sym: str):
        # Each worker adds its own pre-request delay
        if delay_per_worker > 0:
            time.sleep(delay_per_worker)
        try:
            return sym, fetch_fn(sym, start_date, end_date)
        except Exception:
            return sym, None

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_worker, s): s for s in symbols}

        for future in as_completed(futures):
            done += 1
            try:
                sym, df = future.result()
                if df is not None and not df.empty:
                    results[sym] = df
            except Exception:
                pass

            if done % progress_every == 0 or done == len(symbols):
                elapsed = time.time() - t0
                rate = done / elapsed if elapsed > 0 else 0
                remaining = (len(symbols) - done) / rate if rate > 0 else 0
                logger.info(
                    f"  parallel: {done}/{len(symbols)} — "
                    f"{len(results)} ok — {elapsed:.0f}s elapsed, ~{remaining:.0f}s left"
                )

    logger.info(f"parallel: batch done — {len(results)}/{len(symbols)} fetched in {time.time()-t0:.0f}s")
    return results
