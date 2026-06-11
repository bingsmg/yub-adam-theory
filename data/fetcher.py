"""akshare data fetching wrapper with rate limiting, retry, and batch support."""

from __future__ import annotations

import random
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import date, datetime, timedelta

import pandas as pd
from loguru import logger

from config.settings import settings
from utils.timer import rate_limiter


def _validate_hist_df(df: pd.DataFrame, symbol: str) -> pd.DataFrame | None:
    """Validate and clean a historical data DataFrame from akshare."""
    if df is None or df.empty:
        return None

    required_cols = ["日期", "开盘", "收盘", "最高", "最低", "成交量", "成交额"]
    for col in required_cols:
        if col not in df.columns:
            logger.warning("{} missing column '{}' — skipping", symbol, col)
            return None

    # Rename to English
    col_map = {
        "日期": "date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "涨跌幅": "change_pct",
        "换手率": "turnover_rate",
        "振幅": "amplitude",
    }
    existing_map = {k: v for k, v in col_map.items() if k in df.columns}
    df = df.rename(columns=existing_map)

    # Ensure correct types
    df["date"] = pd.to_datetime(df["date"])
    df["symbol"] = symbol

    # Drop rows with null close
    df = df.dropna(subset=["close"])

    # Ensure high >= low, close between high/low
    df = df[df["high"] >= df["low"]]

    if df.empty:
        return None

    return df.reset_index(drop=True)


def fetch_stock_hist(
    symbol: str,
    start_date: str | None = None,
    end_date: str | None = None,
    adjust: str = "qfq",
    max_retries: int = 3,
) -> pd.DataFrame | None:
    """
    Fetch daily historical OHLCV data for a single A-share stock.

    Args:
        symbol: 6-digit stock code (no exchange suffix)
        start_date: "YYYYMMDD" or None (all available history)
        end_date: "YYYYMMDD" or None (up to today)
        adjust: "hfq" (后复权, recommended), "qfq" (前复权), "" (none)
        max_retries: Number of retries with exponential backoff.

    Returns:
        Cleaned DataFrame with English column names, or None on failure.
    """
    import akshare as ak

    if start_date is None:
        start_date = "20100101"
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    last_error = None
    for attempt in range(max_retries):
        try:
            rate_limiter.wait()

            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust,
            )

            result = _validate_hist_df(df, symbol)
            if result is not None:
                return result

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_s = (attempt + 1) * 5  # 5s, 10s, 15s backoff
                logger.warning("Fetch failed for {} (attempt {}/{}): {}. Retrying in {}s...",
                               symbol, attempt + 1, max_retries, e, wait_s)
                time.sleep(wait_s)

    logger.error("Fetch failed for {} after {} retries: {}", symbol, max_retries, last_error)
    return None


def fetch_index_hist(
    symbol: str = "000300",
    start_date: str | None = None,
    end_date: str | None = None,
) -> pd.DataFrame | None:
    """
    Fetch daily index data (e.g., CSI 300 = '000300').

    Returns cleaned DataFrame or None on failure.
    """
    try:
        import akshare as ak

        rate_limiter.wait()

        df = ak.index_zh_a_hist(
            symbol=symbol,
            period="daily",
            start_date=start_date or "20200101",
            end_date=end_date or datetime.now().strftime("%Y%m%d"),
        )

        if df is None or df.empty:
            return None

        col_map = {
            "日期": "date",
            "开盘": "open",
            "收盘": "close",
            "最高": "high",
            "最低": "low",
            "成交量": "volume",
            "成交额": "amount",
        }
        existing = {k: v for k, v in col_map.items() if k in df.columns}
        df = df.rename(columns=existing)
        df["date"] = pd.to_datetime(df["date"])
        return df.sort_values("date").reset_index(drop=True)

    except Exception as e:
        logger.error("Fetch index {} failed: {}", symbol, e)
        return None


def fetch_spot_list() -> pd.DataFrame | None:
    """
    Fetch the full A-share spot list with real-time snapshot.

    Returns DataFrame with columns: code, name, latest_price, change_pct,
    volume, amount, market_cap, pe, pb, etc.
    """
    try:
        import akshare as ak

        rate_limiter.wait()
        df = ak.stock_zh_a_spot_em()
        if df is None or df.empty:
            logger.error("Empty spot list returned")
            return None

        logger.info("Spot list: {} stocks fetched", len(df))
        return df

    except Exception as e:
        logger.error("Fetch spot list failed: {}", e)
        return None


# ── Batch fetching ───────────────────────────────────────────────────

def fetch_batch_sequential(
    symbols: list[str],
    start_date: str = "20200101",
    end_date: str | None = None,
    adjust: str = "qfq",
    show_progress: bool = True,
) -> dict[str, pd.DataFrame]:
    """
    Fetch historical data for multiple symbols sequentially.
    Slower but safer — respects rate limits strictly.

    Returns: {symbol: DataFrame}
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    results: dict[str, pd.DataFrame] = {}
    total = len(symbols)

    for i, symbol in enumerate(symbols):
        if show_progress and i % 10 == 0:
            logger.info("Fetch progress: {}/{} ({:.0f}%)", i, total, 100 * i / total)

        df = fetch_stock_hist(symbol, start_date=start_date, end_date=end_date, adjust=adjust)
        if df is not None:
            results[symbol] = df

        # Extra spacing for large batches — prevent aggressive rate limiting
        if i > 0 and i % 50 == 0:
            wait = random.uniform(3, 6)
            logger.debug("Batch pause {}s at {}/{}", wait, i, total)
            time.sleep(wait)

    logger.info("Batch fetch complete: {}/{} succeeded", len(results), total)
    return results


def fetch_batch_parallel(
    symbols: list[str],
    start_date: str = "20200101",
    end_date: str | None = None,
    adjust: str = "qfq",
    max_workers: int | None = None,
) -> dict[str, pd.DataFrame]:
    """
    Fetch historical data for multiple symbols using ProcessPoolExecutor.
    Faster but may trigger rate limits if too many workers.

    Returns: {symbol: DataFrame}
    """
    if max_workers is None:
        max_workers = settings.PARALLEL_WORKERS
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    results: dict[str, pd.DataFrame] = {}

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                fetch_stock_hist, symbol,
                start_date=start_date, end_date=end_date, adjust=adjust
            ): symbol
            for symbol in symbols
        }

        for future in as_completed(futures):
            symbol = futures[future]
            try:
                df = future.result(timeout=180)
                if df is not None:
                    results[symbol] = df
            except Exception as e:
                logger.error("Parallel fetch failed for {}: {}", symbol, e)

    logger.info("Parallel fetch complete: {}/{} succeeded", len(results), len(symbols))
    return results
