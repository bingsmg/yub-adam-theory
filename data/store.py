"""
Stock-partitioned Parquet storage layer — pure I/O.

Primary storage: output/stocks/{symbol}.parquet (one file per stock)
Legacy fallback: output/daily/*.parquet (date-partitioned), output/all_stocks.parquet

All functions are stateless — paths are passed in or read from settings.
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
from loguru import logger

from config.settings import settings


# ── Path helpers ──────────────────────────────────────────────────────────

def _stock_file_path(symbol: str, stocks_dir: str | None = None) -> str:
    """Build the path for a stock-partitioned parquet file."""
    if stocks_dir is None:
        stocks_dir = str(settings.STOCKS_DIR)
    return os.path.join(stocks_dir, f"{symbol}.parquet")


# ── Single-stock I/O ──────────────────────────────────────────────────────

def _save_stock(symbol: str, df: pd.DataFrame, stocks_dir: str | None = None) -> None:
    """Save/replace a single stock's data to its stock-partitioned file.

    Drops 'symbol' (redundant — encoded in filename) and 'amount' (unused).
    Sorts by date, deduplicates, writes parquet.
    """
    if stocks_dir is None:
        stocks_dir = str(settings.STOCKS_DIR)

    df = df.copy()

    for col in ['symbol', 'amount']:
        if col in df.columns:
            df = df.drop(columns=[col])

    df['date'] = pd.to_datetime(df['date'])
    df = df.sort_values('date').drop_duplicates(subset=['date'], keep='last')
    df = df.reset_index(drop=True)

    path = _stock_file_path(symbol, stocks_dir)
    df.to_parquet(path, index=False)


def _save_results_to_stocks(
    results: dict[str, pd.DataFrame],
    name_map: dict[str, str],
    stocks_dir: str | None = None,
) -> int:
    """Save fetched results to stock-partitioned parquet files.

    For each stock in results, merges new rows with existing file data
    (or creates a new file), deduplicates by date, and sorts ascending.

    Returns count of stocks actually saved (with >= 30 bars).
    """
    if stocks_dir is None:
        stocks_dir = str(settings.STOCKS_DIR)
    if not results:
        return 0

    os.makedirs(stocks_dir, exist_ok=True)
    count = 0

    for sym, df in results.items():
        if df is None or df.empty:
            continue

        # 增量更新可能只拉 1-2 天数据（<30 行），需要合并已有文件判定
        df = df.copy()
        if 'name' not in df.columns or df['name'].isna().all():
            df['name'] = name_map.get(sym, '')

        existing_path = _stock_file_path(sym, stocks_dir)
        if os.path.exists(existing_path):
            try:
                existing = pd.read_parquet(existing_path)
                df = pd.concat([existing, df], ignore_index=True)
            except Exception:
                pass
        elif len(df) < 30:
            # 新股票首次拉取，数据不足 30 根 K 线则跳过
            continue

        _save_stock(sym, df, stocks_dir)
        count += 1

    return count


def load_stock(
    symbol: str,
    stocks_dir: str | None = None,
) -> pd.DataFrame:
    """Load the full history for a single stock from its stock-partitioned file.

    Returns DataFrame with columns: date, open, high, low, close, volume, name
    (no 'symbol' column — symbol is encoded in the filename).

    Raises FileNotFoundError if the stock file does not exist.
    """
    if stocks_dir is None:
        stocks_dir = str(settings.STOCKS_DIR)

    path = _stock_file_path(symbol, stocks_dir)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No data for stock {symbol} at {path}")

    df = pd.read_parquet(path)
    df['date'] = pd.to_datetime(df['date'])
    return df


# ── Bulk loading ──────────────────────────────────────────────────────────

def load_latest_snapshot(
    stocks_dir: str | None = None,
) -> pd.DataFrame:
    """Load only the latest row for each stock (fast pre-screen).

    Reads each stock file and keeps only the last row (by date).
    O(n_stocks * 1 row) instead of O(n_stocks * n_days).

    Returns DataFrame with columns: symbol, date, open, high, low, close, volume, name.
    Falls back to legacy load_all_stocks() if STOCKS_DIR does not exist.
    """
    if stocks_dir is None:
        stocks_dir = str(settings.STOCKS_DIR)

    if not os.path.isdir(stocks_dir) or not any(
        f.endswith('.parquet') for f in os.listdir(stocks_dir)
    ):
        try:
            master = load_all_stocks()
            if master.empty:
                return master
            latest_date = master['date'].max()
            return master[master['date'] == latest_date].copy()
        except Exception:
            return pd.DataFrame()

    rows = []
    for fname in sorted(os.listdir(stocks_dir)):
        if not fname.endswith('.parquet'):
            continue
        sym = fname.replace('.parquet', '')
        path = os.path.join(stocks_dir, fname)
        try:
            df = pd.read_parquet(path)
            if df.empty:
                continue
            last = df.iloc[-1:].copy()
            last['symbol'] = sym
            rows.append(last)
        except Exception:
            logger.warning(f"Could not read {path}, skipping")
            continue

    if not rows:
        return pd.DataFrame()

    result = pd.concat(rows, ignore_index=True)
    result['date'] = pd.to_datetime(result['date'])
    return result


def load_all_stocks(path: str | None = None, daily_dir: str | None = None) -> pd.DataFrame:
    """Load all stock data, preferring stock-partitioned files if available.

    Resolution order:
      1. output/stocks/*.parquet (stock-partitioned — primary)
      2. output/daily/*.parquet (date-partitioned — legacy)
      3. output/all_stocks.parquet (single file — legacy)

    Returns DataFrame with columns: date, open, high, low, close, volume, name, symbol.
    """
    # Try 1: stock-partitioned (primary)
    stocks_dir = str(settings.STOCKS_DIR)
    if os.path.isdir(stocks_dir):
        stock_files = [f for f in os.listdir(stocks_dir) if f.endswith('.parquet')]
        if stock_files:
            chunks = []
            for fname in sorted(stock_files):
                sym = fname.replace('.parquet', '')
                try:
                    df = pd.read_parquet(os.path.join(stocks_dir, fname))
                    df['symbol'] = sym
                    chunks.append(df)
                except Exception:
                    logger.warning(f"Could not read {fname}, skipping")
                    continue
            if chunks:
                result = pd.concat(chunks, ignore_index=True)
                result['date'] = pd.to_datetime(result['date'])
                return result

    # Try 2: date-partitioned (legacy)
    if daily_dir is None:
        daily_dir = str(settings.DAILY_DIR)
    if os.path.isdir(daily_dir):
        files = [os.path.join(daily_dir, f) for f in os.listdir(daily_dir) if f.endswith('.parquet')]
        if files:
            df = pd.read_parquet(daily_dir)
            df['date'] = pd.to_datetime(df['date'])
            return df

    # Try 3: single consolidated file (legacy)
    if path is None:
        path = str(settings.ALL_STOCKS_PATH)
    if os.path.exists(path):
        return pd.read_parquet(path)

    raise FileNotFoundError(f"No data found in {stocks_dir}, {daily_dir}, or {path}")


def get_latest_date(stocks_dir: str | None = None) -> pd.Timestamp | None:
    """Find the latest date across all stock files."""
    try:
        snapshot = load_latest_snapshot(stocks_dir)
        if snapshot.empty:
            return None
        return snapshot['date'].max()
    except Exception:
        return None
