"""
Data pipeline orchestration — full backfill and incremental update.

Orchestrates data sources, parallel fetching, and storage to produce
stock-partitioned parquet files under output/stocks/.
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timedelta

from loguru import logger

from config.settings import settings
from data.store import (
    _save_results_to_stocks,
    _stock_file_path,
    get_latest_date,
    load_all_stocks,
)
from data.filters import get_stale_stocks


def build_all_stocks_parquet(
    stock_list,
    start_date: str,
    end_date: str,
    output_path: str | None = None,
    fetcher=None,
    chunk_size: int = 200,
) -> int:
    """
    Download ALL stocks' daily data, saving to stock-partitioned
    files under output/stocks/. Uses chunked parallel fetch with
    incremental saves — if interrupted, resume will skip already-saved stocks.

    Args:
        stock_list: DataFrame from get_stock_list().
        start_date: 'YYYY-MM-DD'.
        end_date: 'YYYY-MM-DD'.
        output_path: Ignored (kept for compatibility).
        fetcher: Optional DataSource.  If None, uses get_fetcher().
        chunk_size: Symbols per chunk (save after each chunk).

    Returns:
        Number of stocks successfully fetched and saved.
    """
    if fetcher is None:
        from data.sources import get_fetcher
        fetcher = get_fetcher()

    stocks_dir = str(settings.STOCKS_DIR)
    os.makedirs(stocks_dir, exist_ok=True)

    # Resume: check existing stock files for already-downloaded symbols
    existing_symbols = set()
    if os.path.isdir(stocks_dir):
        for fname in os.listdir(stocks_dir):
            if fname.endswith('.parquet'):
                existing_symbols.add(fname.replace('.parquet', ''))
        if existing_symbols:
            logger.info(f"Resuming: {len(existing_symbols)} stocks already in {stocks_dir}")

    remaining = stock_list[~stock_list['symbol'].isin(existing_symbols)]
    if remaining.empty:
        logger.info("All stocks already downloaded!")
        return len(existing_symbols)

    total = len(remaining)
    logger.info(f"Building: {total} stocks to fetch via {fetcher.name}, {start_date} → {end_date}")
    logger.info(f"Chunk size: {chunk_size}, max workers: {settings.FETCH_MAX_WORKERS}, delay: {settings.FETCH_DELAY_SECONDS}s")

    name_map = dict(zip(stock_list['symbol'], stock_list['name']))

    from data.sources.parallel import fetch_batch_parallel

    def _fetch_one(sym: str, s: str, e: str):
        """Uses fetch_with_fallback with a 60s timeout per stock."""
        from data.sources.strategy import fetch_with_fallback
        from concurrent.futures import ThreadPoolExecutor, TimeoutError

        def _do_fetch():
            df = fetch_with_fallback(sym, s, e)
            if df is not None and not df.empty:
                if 'symbol' not in df.columns:
                    df['symbol'] = sym
                if 'name' not in df.columns:
                    df['name'] = name_map.get(sym, '')
            return df

        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(_do_fetch)
                return future.result(timeout=60)
        except TimeoutError:
            logger.warning(f"Timeout fetching {sym} after 60s")
            return None
        except Exception as exc:
            logger.debug(f"Error fetching {sym}: {exc}")
            return None

    t0 = time.time()
    symbols_to_fetch = remaining['symbol'].tolist()
    total_saved = 0
    total_fetched = 0

    for chunk_start in range(0, len(symbols_to_fetch), chunk_size):
        chunk = symbols_to_fetch[chunk_start:chunk_start + chunk_size]
        chunk_num = chunk_start // chunk_size + 1
        total_chunks = (len(symbols_to_fetch) + chunk_size - 1) // chunk_size

        logger.info(f"Chunk {chunk_num}/{total_chunks}: {len(chunk)} symbols starting at {chunk[0]}")

        results = fetch_batch_parallel(
            fetch_fn=_fetch_one,
            symbols=chunk,
            start_date=start_date,
            end_date=end_date,
            max_workers=settings.FETCH_MAX_WORKERS,
            delay_per_worker=settings.FETCH_DELAY_SECONDS,
            progress_every=chunk_size,
        )

        total_fetched += len(results)

        saved = _save_results_to_stocks(results, name_map, stocks_dir)
        total_saved += saved

        elapsed = time.time() - t0
        rate = total_fetched / elapsed if elapsed > 0 else 0
        remaining_stocks = len(symbols_to_fetch) - total_fetched
        eta = remaining_stocks / rate if rate > 0 else 0

        logger.info(
            f"Progress: {total_fetched}/{len(symbols_to_fetch)} fetched, "
            f"{total_saved} saved, {elapsed/60:.0f}min elapsed, ~{eta/60:.0f}min left"
        )

    elapsed = time.time() - t0
    logger.info(f"Done: {total_saved} stocks saved to {stocks_dir} in {elapsed/60:.0f}min")

    return total_saved


def update_latest_days(
    stock_list,
    master_path: str | None = None,
    fetcher=None,
):
    """
    Fetch new trading days and save as stock-partitioned parquet files.

    Instead of loading ALL data, checks each stock file's last date
    to find stale stocks. Much more efficient for large universes.

    Args:
        stock_list: DataFrame with [symbol, name, code] columns.
        master_path: Ignored (kept for compatibility).
        fetcher: Optional DataSource.  If None, uses get_fetcher().

    Returns:
        Full merged DataFrame of all stocks (same as load_all_stocks()).
    """
    if fetcher is None:
        from data.sources import get_fetcher
        fetcher = get_fetcher()

    stocks_dir = str(settings.STOCKS_DIR)
    os.makedirs(stocks_dir, exist_ok=True)

    end_date = datetime.now().strftime('%Y-%m-%d')

    stale = get_stale_stocks(stock_list, stocks_dir, end_date)

    if not stale:
        latest = get_latest_date(stocks_dir)
        logger.info(f"All stocks up to date (latest: {latest.date() if latest is not None else 'N/A'})")
        return load_all_stocks()

    last_dates = [ld for ld in stale.values() if ld is not None]
    if last_dates:
        global_start = min(last_dates).strftime('%Y-%m-%d')
    else:
        global_start = (datetime.now() - timedelta(days=730)).strftime('%Y-%m-%d')

    symbols_to_fetch = list(stale.keys())
    logger.info(f"Updating {len(symbols_to_fetch)} stocks via {fetcher.name} from {global_start} to {end_date}")

    name_map = dict(zip(stock_list['symbol'], stock_list['name']))
    t0 = time.time()

    from data.sources.parallel import fetch_batch_parallel

    def _fetch_one(sym: str, s: str, e: str):
        from data.sources.strategy import fetch_with_fallback
        df = fetch_with_fallback(sym, s, e)
        if df is not None and not df.empty:
            if 'symbol' not in df.columns:
                df['symbol'] = sym
            if 'name' not in df.columns:
                df['name'] = name_map.get(sym, '')
        return df

    results = fetch_batch_parallel(
        fetch_fn=_fetch_one,
        symbols=symbols_to_fetch,
        start_date=global_start,
        end_date=end_date,
        max_workers=settings.FETCH_MAX_WORKERS,
        delay_per_worker=settings.FETCH_DELAY_SECONDS,
        progress_every=200,
    )

    if results:
        saved = _save_results_to_stocks(results, name_map, stocks_dir)
        new_rows = sum(len(v) for v in results.values() if v is not None)
        logger.info(f"Updated: {saved} stocks, ~{new_rows} new rows in {time.time()-t0:.0f}s")
    else:
        logger.info("No new data to add")

    return load_all_stocks()
