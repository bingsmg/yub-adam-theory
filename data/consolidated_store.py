"""
Consolidated single-file store for all A-share stocks.

Stores ALL stocks in date-partitioned Parquet files: output/daily/YYYY-MM-DD.parquet
Columns: symbol, name, date, open, high, low, close, volume, amount

Supports:
  - Full backfill of 5000+ stocks via pluggable data sources
  - Incremental daily update (fetch only new trading days)
  - Fast bulk loading for analysis
"""

from __future__ import annotations

import os
import time
from datetime import date, datetime, timedelta

import pandas as pd
from loguru import logger

from config.settings import settings


def _baostock_code(symbol: str) -> str:
    """Convert 6-digit code to baostock format: 600519 -> sh.600519

    Kept as a utility — used by BaostockDataSource internally, and as a
    reference for exchange-prefixed code format.
    """
    code = str(symbol).zfill(6)
    if code.startswith(("60", "68")):
        return f"sh.{code}"
    elif code.startswith(("00", "30", "002")):
        return f"sz.{code}"
    elif code.startswith(("8", "4")):
        return f"bj.{code}"
    return f"sz.{code}"


def get_board(symbol: str) -> str:
    """Determine the trading board from a 6-digit A-share symbol.

    Returns one of: 'main', 'chinext', 'star', 'bse'
    """
    code = str(symbol).zfill(6)
    if code.startswith(('300', '301')):
        return 'chinext'
    elif code.startswith(('688', '689')):
        return 'star'
    elif code.startswith(('8', '4')):
        return 'bse'
    return 'main'


def get_stock_list(fetcher=None) -> pd.DataFrame:
    """Get full A-share stock list via the configured data source.

    Args:
        fetcher: Optional DataSource instance.  If None, uses get_fetcher()
                 which reads DATA_SOURCE_ORDER from config.

    Returns DataFrame with columns: symbol, name, code
    """
    if fetcher is None:
        from data.sources import get_fetcher
        fetcher = get_fetcher()
    return fetcher.get_stock_list()


def get_stock_list_baostock() -> pd.DataFrame:
    """Get full A-share stock list via baostock (legacy — prefer get_stock_list()).

    Kept for backward compatibility.  Now delegates to the fetcher.
    """
    from data.sources import get_fetcher
    # Force baostock for this legacy function
    fetcher = get_fetcher(order=["baostock"])
    return fetcher.get_stock_list()


def build_all_stocks_parquet(
    stock_list: pd.DataFrame,
    start_date: str,
    end_date: str,
    output_path: str | None = None,
    fetcher=None,
) -> int:
    """
    Download ALL stocks' daily data, saving to date-partitioned
    daily files under output/daily/. Uses parallel fetch when available.

    Args:
        stock_list: DataFrame from get_stock_list().
        start_date: 'YYYY-MM-DD'.
        end_date: 'YYYY-MM-DD'.
        output_path: Ignored (kept for compatibility). Uses daily dir.
        fetcher: Optional DataSource.  If None, uses get_fetcher().

    Returns:
        Number of stocks successfully fetched.
    """
    if fetcher is None:
        from data.sources import get_fetcher
        fetcher = get_fetcher()

    daily_dir = str(settings.DAILY_DIR)
    os.makedirs(daily_dir, exist_ok=True)

    # Resume: check existing daily files for already-downloaded symbols
    existing_symbols = set()
    if os.path.isdir(daily_dir):
        try:
            existing = load_all_stocks()
            existing_symbols = set(existing['symbol'].unique())
            logger.info(f"Resuming: {len(existing_symbols)} stocks already in {daily_dir}")
        except Exception:
            pass

    remaining = stock_list[~stock_list['symbol'].isin(existing_symbols)]
    if remaining.empty:
        logger.info("All stocks already downloaded!")
        return len(existing_symbols)

    total = len(remaining)
    logger.info(f"Building: {total} stocks to fetch via {fetcher.name}, {start_date} → {end_date}")

    # Use parallel fetch for speed (sequential fallback if max_workers=1)
    from data.sources.parallel import fetch_batch_parallel

    def _fetch_one(sym: str, s: str, e: str):
        """Closure capturing stock_list for name lookup."""
        name = stock_list.loc[stock_list['symbol'] == sym, 'name']
        name_val = name.iloc[0] if not name.empty else ''
        df = fetcher.fetch_daily_kline(sym, s, e)
        if df is not None and not df.empty:
            if 'symbol' not in df.columns:
                df['symbol'] = sym
            if 'name' not in df.columns:
                df['name'] = name_val
        return df

    t0 = time.time()
    symbols_to_fetch = remaining['symbol'].tolist()

    results = fetch_batch_parallel(
        fetch_fn=_fetch_one,
        symbols=symbols_to_fetch,
        start_date=start_date,
        end_date=end_date,
        max_workers=settings.FETCH_MAX_WORKERS,
        delay_per_worker=settings.FETCH_DELAY_SECONDS,
        progress_every=200,
    )

    # Write results to daily parquet files
    if results:
        all_new = []
        for sym, df in results.items():
            if len(df) >= 30:
                all_new.append(df)

        if all_new:
            new_data = pd.concat(all_new, ignore_index=True)
            new_data['date'] = pd.to_datetime(new_data['date'])

            for date_val, group in new_data.groupby('date'):
                date_str = pd.Timestamp(date_val).strftime('%Y-%m-%d')
                daily_path = os.path.join(daily_dir, f'{date_str}.parquet')
                if os.path.exists(daily_path):
                    existing_day = pd.read_parquet(daily_path)
                    group = pd.concat([existing_day, group], ignore_index=True)
                    group = group.drop_duplicates(subset=['symbol'], keep='last')
                group.to_parquet(daily_path, index=False)

    success = len(results)
    elapsed = time.time() - t0
    logger.info(f"Done: {success} stocks saved to {daily_dir} in {elapsed/60:.0f}min")

    return success


def load_all_stocks(path: str | None = None, daily_dir: str | None = None) -> pd.DataFrame:
    """Load all stock data, preferring date-partitioned daily files if available.

    If output/daily/ exists with .parquet files, reads them all together.
    Otherwise falls back to the single consolidated file.
    """
    if daily_dir is None:
        daily_dir = str(settings.DAILY_DIR)

    if os.path.isdir(daily_dir):
        files = [os.path.join(daily_dir, f) for f in os.listdir(daily_dir) if f.endswith('.parquet')]
        if files:
            df = pd.read_parquet(daily_dir)
            df['date'] = pd.to_datetime(df['date'])
            return df

    # Fallback to single file
    if path is None:
        path = str(settings.ALL_STOCKS_PATH)
    if os.path.exists(path):
        return pd.read_parquet(path)
    raise FileNotFoundError(f"No data found at {daily_dir} or {path}")


def migrate_to_daily(source_path: str | None = None, daily_dir: str | None = None) -> int:
    """Split existing consolidated parquet into daily files under output/daily/.

    Returns number of daily files created.
    """
    if source_path is None:
        source_path = str(settings.ALL_STOCKS_PATH)
    if daily_dir is None:
        daily_dir = str(settings.DAILY_DIR)

    os.makedirs(daily_dir, exist_ok=True)

    df = pd.read_parquet(source_path)
    df['date'] = pd.to_datetime(df['date'])

    count = 0
    for date_val, group in df.groupby('date'):
        date_str = pd.Timestamp(date_val).strftime('%Y-%m-%d')
        out_path = os.path.join(daily_dir, f'{date_str}.parquet')
        group.to_parquet(out_path, index=False)
        count += 1

    logger.info(f"Migrated {len(df):,} rows ({df.symbol.nunique()} stocks) into {count} daily files")
    return count


def update_latest_days(
    stock_list: pd.DataFrame,
    master_path: str | None = None,
    fetcher=None,
) -> pd.DataFrame:
    """
    Fetch new trading days and save as date-partitioned parquet files.

    Each day's data is written to output/daily/{date}.parquet.
    Returns the full merged DataFrame.

    Args:
        stock_list: DataFrame with [symbol, name, code] columns.
        master_path: Ignored (kept for compatibility).
        fetcher: Optional DataSource.  If None, uses get_fetcher().
    """
    if fetcher is None:
        from data.sources import get_fetcher
        fetcher = get_fetcher()

    daily_dir = str(settings.DAILY_DIR)
    os.makedirs(daily_dir, exist_ok=True)

    master = load_all_stocks()
    latest_date = master['date'].max()
    end_date = datetime.now().strftime('%Y-%m-%d')

    symbol_dates = master.groupby('symbol')['date'].max()
    needs_update = symbol_dates[symbol_dates < pd.Timestamp(end_date)]

    if needs_update.empty:
        logger.info(f"All stocks up to date (latest: {latest_date.date()})")
        return master

    total = len(needs_update)
    logger.info(f"Updating {total} stocks via {fetcher.name} from {latest_date.date()} to {end_date}")

    name_map = dict(zip(stock_list['symbol'], stock_list['name']))
    t0 = time.time()

    # Use parallel fetch for daily updates too
    from data.sources.parallel import fetch_batch_parallel

    def _fetch_one(sym: str, s: str, e: str):
        df = fetcher.fetch_daily_kline(sym, s, e)
        if df is not None and not df.empty:
            if 'symbol' not in df.columns:
                df['symbol'] = sym
            if 'name' not in df.columns:
                df['name'] = name_map.get(sym, '')
        return df

    symbols_to_fetch = []
    for sym, last_d in needs_update.items():
        symbols_to_fetch.append(sym)

    results = fetch_batch_parallel(
        fetch_fn=_fetch_one,
        symbols=symbols_to_fetch,
        start_date=latest_date.strftime('%Y-%m-%d'),
        end_date=end_date,
        max_workers=settings.FETCH_MAX_WORKERS,
        delay_per_worker=settings.FETCH_DELAY_SECONDS,
        progress_every=200,
    )

    if results:
        all_new = list(results.values())
        new_data = pd.concat(all_new, ignore_index=True)
        new_data['date'] = pd.to_datetime(new_data['date'])

        for date_val, group in new_data.groupby('date'):
            date_str = pd.Timestamp(date_val).strftime('%Y-%m-%d')
            daily_path = os.path.join(daily_dir, f'{date_str}.parquet')

            if os.path.exists(daily_path):
                existing = pd.read_parquet(daily_path)
                group = pd.concat([existing, group], ignore_index=True)
                group = group.drop_duplicates(subset=['symbol'], keep='last')

            group.to_parquet(daily_path, index=False)

        master = load_all_stocks()
        logger.info(f"Updated: {len(results)} stocks, {len(new_data)} new rows in {time.time()-t0:.0f}s")
    else:
        logger.info("No new data to add")

    return master


def filter_active_stocks(
    master: pd.DataFrame,
    top_n: int | None = None,
) -> list[dict]:
    """
    Filter to the most active stocks for analysis.

    Active = highest (volume × close) on the most recent date.

    Returns list of dicts: [{symbol, name, close, ...}]
    """
    if top_n is None:
        top_n = settings.MAX_STOCKS_TO_ANALYZE

    latest_date = master['date'].max()
    latest = master[master['date'] == latest_date].copy()

    # Exclude ST
    if 'name' in latest.columns:
        latest = latest[~latest['name'].str.contains('ST|退', na=False)]

    # Exclude penny stocks
    latest = latest[latest['close'] >= settings.MIN_PRICE]
    latest = latest[latest['volume'] > 0]

    # Exclude boards without trading permission
    if not settings.ALLOW_CHINEXT:
        latest = latest[~latest['symbol'].astype(str).str.match(r'^30[01]')]
    if not settings.ALLOW_STAR_MARKET:
        latest = latest[~latest['symbol'].astype(str).str.match(r'^68[89]')]
    if not settings.ALLOW_BSE:
        latest = latest[~latest['symbol'].astype(str).str.match(r'^[84]')]

    # Activity score
    latest['_score'] = latest['volume'].fillna(0) * latest['close'].fillna(0)
    latest = latest.sort_values('_score', ascending=False)
    latest = latest.head(top_n)

    return latest[['symbol', 'name', 'close']].to_dict('records')
