"""
Consolidated single-file store for all A-share stocks.

Stores ALL stocks in one Parquet file: output/all_stocks.parquet
Columns: symbol, name, date, open, high, low, close, volume, amount

Supports:
  - Full backfill of 5000+ stocks via baostock (no rate limits)
  - Incremental daily update (fetch only new trading days)
  - Fast bulk loading for analysis
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
from loguru import logger

from config.settings import settings


def _baostock_code(symbol: str) -> str:
    """Convert 6-digit code to baostock format: 600519 -> sh.600519"""
    code = str(symbol).zfill(6)
    if code.startswith(("60", "68")):
        return f"sh.{code}"
    elif code.startswith(("00", "30", "002")):
        return f"sz.{code}"
    elif code.startswith(("8", "4")):
        return f"bj.{code}"
    return f"sz.{code}"


def get_stock_list_baostock() -> pd.DataFrame:
    """
    Get full A-share stock list via baostock.
    Returns DataFrame with columns: symbol, name, code
    """
    import baostock as bs

    bs.login()

    # query_stock_basic() without code_name returns ALL securities
    rs = bs.query_stock_basic()
    all_data = []
    while (rs.error_code == '0') & rs.next():
        all_data.append(rs.get_row_data())

    bs.logout()

    if not all_data:
        raise RuntimeError("baostock returned empty stock list")

    df = pd.DataFrame(all_data, columns=['code', 'name', 'ipo_date', 'out_date', 'type', 'status'])

    # Filter: type='1' = stock (not index/ETF), status='1' = listed
    df = df[(df['type'] == '1') & (df['status'] == '1')]

    # Extract symbol from code like 'sh.600519' -> '600519'
    df['symbol'] = df['code'].str.replace(r'^(sh|sz|bj)\.', '', regex=True)

    logger.info(f"Stock list: {len(df)} stocks")
    return df[['symbol', 'name', 'code']].reset_index(drop=True)


def build_all_stocks_parquet(
    stock_list: pd.DataFrame,
    start_date: str,
    end_date: str,
    output_path: str | None = None,
) -> int:
    """
    Download ALL stocks' daily data sequentially with a single baostock session.

    Single session is the only reliable approach — baostock does not support
    concurrent logins from the same IP. Progressive save every 500 stocks
    prevents data loss on interruption.

    ~1.5s/stock → 5200 stocks ≈ 2.2 hours for full download.

    Args:
        stock_list: DataFrame from get_stock_list_baostock().
        start_date: 'YYYY-MM-DD'.
        end_date: 'YYYY-MM-DD'.
        output_path: Parquet path.

    Returns:
        Number of stocks successfully fetched, 0 if resuming from existing.
    """
    import baostock as bs
    import time, os

    if output_path is None:
        output_path = str(settings.ALL_STOCKS_PATH)

    total = len(stock_list)

    # Resume from existing file if present
    existing_symbols = set()
    if os.path.exists(output_path):
        existing = pd.read_parquet(output_path)
        existing_symbols = set(existing['symbol'].unique())
        logger.info(f"Resuming: {len(existing_symbols)} stocks already in {output_path}")

    remaining = stock_list[~stock_list['symbol'].isin(existing_symbols)]
    if remaining.empty:
        logger.info("All stocks already downloaded!")
        return len(existing_symbols)

    total = len(remaining)
    logger.info(f"Building: {total} stocks to fetch (single session), {start_date} → {end_date}")

    bs.login()
    t0 = time.time()
    success = 0
    fail = 0
    batch_dfs = []

    # Load existing data if resuming
    if os.path.exists(output_path):
        batch_dfs.append(pd.read_parquet(output_path))

    for i, (_, row) in enumerate(remaining.iterrows()):
        baocode = row['code']
        symbol = row['symbol']
        name = row['name']

        try:
            rs = bs.query_history_k_data_plus(
                baocode, 'date,open,high,low,close,volume,amount',
                start_date, end_date, frequency='d', adjustflag='2')
            data = []
            while rs.error_code == '0' and rs.next():
                data.append(rs.get_row_data())

            if data:
                df_stock = pd.DataFrame(data, columns=['date','open','high','low','close','volume','amount'])
                df_stock['symbol'] = symbol
                df_stock['name'] = name
                for c in ['open','high','low','close','volume','amount']:
                    df_stock[c] = pd.to_numeric(df_stock[c], errors='coerce')
                df_stock = df_stock.dropna(subset=['close'])
                if len(df_stock) >= 30:
                    batch_dfs.append(df_stock)
                    success += 1
                else:
                    fail += 1
            else:
                fail += 1
        except Exception as e:
            fail += 1

        # Progress + save checkpoint every 500 stocks
        done = success + fail
        if done % 500 == 0 or done == total:
            elapsed = time.time() - t0
            rate = done / elapsed if elapsed > 0 else 0
            remaining = (total - done) / rate if rate > 0 else 0
            logger.info(f"  {done}/{total} ({done*100//total}%) — "
                        f"{success} ok, {fail} fail — "
                        f"{elapsed/60:.0f}min elapsed, ~{remaining/60:.0f}min left")

            # Progressive save
            if batch_dfs:
                master = pd.concat(batch_dfs, ignore_index=True)
                master['date'] = pd.to_datetime(master['date'])
                master = master.sort_values(['symbol','date']).drop_duplicates(subset=['symbol','date'], keep='last')
                master.to_parquet(output_path, index=False)

    bs.logout()

    # Final save
    if batch_dfs:
        master = pd.concat(batch_dfs, ignore_index=True)
        master['date'] = pd.to_datetime(master['date'])
        master = master.sort_values(['symbol','date']).drop_duplicates(subset=['symbol','date'], keep='last')
        master.to_parquet(output_path, index=False)

    elapsed = time.time() - t0
    logger.info(f"Done: {success} stocks saved to {output_path} in {elapsed/60:.0f}min")

    return success


def load_all_stocks(path: str | None = None) -> pd.DataFrame:
    """Load the consolidated parquet file."""
    if path is None:
        path = str(settings.ALL_STOCKS_PATH)
    return pd.read_parquet(path)


def update_latest_days(
    stock_list: pd.DataFrame,
    master_path: str | None = None,
) -> pd.DataFrame:
    """
    Fetch only new trading days since the last date in the parquet.
    Uses single baostock session — short date range is fast (~0.15s per stock).

    Returns the updated master DataFrame (also saved to disk).
    """
    import baostock as bs
    import time

    if master_path is None:
        master_path = str(settings.ALL_STOCKS_PATH)

    master = load_all_stocks(master_path)
    latest_date = master['date'].max()
    end_date = datetime.now().strftime('%Y-%m-%d')

    symbol_dates = master.groupby('symbol')['date'].max()
    needs_update = symbol_dates[symbol_dates < pd.Timestamp(end_date)]

    if needs_update.empty:
        logger.info(f"All stocks up to date (latest: {latest_date.date()})")
        return master

    total = len(needs_update)
    logger.info(f"Updating {total} stocks from {latest_date.date()} to {end_date}")

    name_map = dict(zip(stock_list['symbol'], stock_list['name']))
    bs.login()
    new_rows = []
    success = 0
    t0 = time.time()

    for i, (sym, last_d) in enumerate(needs_update.items()):
        try:
            rs = bs.query_history_k_data_plus(
                _baostock_code(sym),
                'date,open,high,low,close,volume,amount',
                start_date=last_d.strftime('%Y-%m-%d'), end_date=end_date,
                frequency='d', adjustflag='2'
            )
            data = []
            while (rs.error_code == '0') & rs.next():
                data.append(rs.get_row_data())

            if data:
                df = pd.DataFrame(data, columns=['date','open','high','low','close','volume','amount'])
                df['symbol'] = sym
                df['name'] = name_map.get(sym, '')
                for col in ['open','high','low','close','volume','amount']:
                    df[col] = pd.to_numeric(df[col], errors='coerce')
                new_rows.append(df)
                success += 1

        except Exception:
            pass

        if (i + 1) % 1000 == 0:
            elapsed = time.time() - t0
            logger.info(f"  Update: {i+1}/{total} — {elapsed:.0f}s elapsed")

    bs.logout()

    if new_rows:
        new_data = pd.concat(new_rows, ignore_index=True)
        new_data['date'] = pd.to_datetime(new_data['date'])
        master = pd.concat([master, new_data], ignore_index=True)
        master = master.drop_duplicates(subset=['symbol', 'date'], keep='last')
        master = master.sort_values(['symbol', 'date']).reset_index(drop=True)
        master.to_parquet(master_path, index=False)
        logger.info(f"Updated: {success} stocks, {len(new_data)} rows in {time.time()-t0:.0f}s")
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

    # Activity score
    latest['_score'] = latest['volume'].fillna(0) * latest['close'].fillna(0)
    latest = latest.sort_values('_score', ascending=False)
    latest = latest.head(top_n)

    return latest[['symbol', 'name', 'close']].to_dict('records')
