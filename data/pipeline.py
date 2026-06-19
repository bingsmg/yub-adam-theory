"""
数据管道编排 — 全量回填与增量更新。

协调数据源、并行获取和存储，生成 output/stocks/ 下按股票分区的 parquet 文件。
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
    force: bool = False,
) -> int:
    """
    下载所有股票的日线数据，保存到 output/stocks/ 下按股票分区的文件。
    使用分块并行获取与增量保存 — 若中断，断点续传将跳过已保存的股票。

    Args:
        stock_list: 来自 get_stock_list() 的 DataFrame。
        start_date: 'YYYY-MM-DD'。
        end_date: 'YYYY-MM-DD'。
        output_path: 忽略（保留以兼容）。
        fetcher: 可选 DataSource。若为 None，则使用 get_fetcher()。
        chunk_size: 每块股票数量（每块后保存）。

    Returns:
        成功获取并保存的股票数量。
    """
    if fetcher is None:
        from data.sources import get_fetcher
        fetcher = get_fetcher()

    stocks_dir = str(settings.STOCKS_DIR)
    os.makedirs(stocks_dir, exist_ok=True)

    # 断点续传：检查已下载的股票文件
    existing_symbols = set()
    if not force and os.path.isdir(stocks_dir):
        for fname in os.listdir(stocks_dir):
            if fname.endswith('.parquet'):
                existing_symbols.add(fname.replace('.parquet', ''))
        if existing_symbols:
            logger.info(f"断点续传：{len(existing_symbols)} 只股票已存在于 {stocks_dir}")

    if force:
        logger.info("强制模式：重新下载所有股票")

    remaining = stock_list[~stock_list['symbol'].isin(existing_symbols)] if not force else stock_list
    if remaining.empty:
        logger.info("所有股票已下载完成！")
        return len(existing_symbols)

    total = len(remaining)
    logger.info(f"开始构建：{total} 只股票需获取，数据源 {fetcher.name}，{start_date} → {end_date}")
    logger.info(f"块大小：{chunk_size}，最大并发数：{settings.FETCH_MAX_WORKERS}，延迟：{settings.FETCH_DELAY_SECONDS}s")

    name_map = dict(zip(stock_list['symbol'], stock_list['name']))

    from data.sources.parallel import fetch_batch_parallel

    def _fetch_one(sym: str, s: str, e: str):
        """使用 fetch_with_fallback，每只股票 60 秒超时。"""
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
    获取新的交易日数据并保存为按股票分区的 parquet 文件。

    不加载全部数据，而是检查每个股票文件的最后日期以找出过期股票。
    对大规模股票池效率更高。

    Args:
        stock_list: 包含 [symbol, name, code] 列的 DataFrame。
        master_path: 忽略（保留以兼容）。
        fetcher: 可选 DataSource。若为 None，则使用 get_fetcher()。

    Returns:
        所有股票的完整合并 DataFrame（同 load_all_stocks()）。
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
