"""
Business filtering and classification for A-share stocks.

Board classification, stock list retrieval, staleness detection,
and pre-screen active-stock filtering — all independent of storage I/O.
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
from loguru import logger

from config.settings import settings


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


def get_stale_stocks(
    stock_list: pd.DataFrame,
    stocks_dir: str | None = None,
    reference_date: str | None = None,
) -> dict[str, pd.Timestamp | None]:
    """Find stocks whose last data date is before the reference date.

    Reads only the 'date' column from each stock file to find its max date.
    Much faster than loading all data.

    Returns dict mapping symbol -> last_date (None if file does not exist).
    """
    if stocks_dir is None:
        stocks_dir = str(settings.STOCKS_DIR)
    if reference_date is None:
        reference_date = datetime.now().strftime('%Y-%m-%d')

    from data.store import _stock_file_path

    ref_dt = pd.Timestamp(reference_date)
    stale: dict[str, pd.Timestamp | None] = {}

    for _, row in stock_list.iterrows():
        sym = row['symbol']
        path = _stock_file_path(sym, stocks_dir)
        if not os.path.exists(path):
            stale[sym] = None
            continue
        try:
            dates = pd.read_parquet(path, columns=['date'])
            last_date = dates['date'].max()
            if pd.isna(last_date) or last_date < ref_dt:
                stale[sym] = last_date
        except Exception:
            stale[sym] = None

    return stale


def filter_active_stocks(
    master: pd.DataFrame | None = None,
    top_n: int | None = None,
) -> list[dict]:
    """
    Filter to the most active stocks for analysis.

    Active = highest (volume × close) on the most recent date.

    If master is None, uses load_latest_snapshot() which reads only the
    last row of each stock file — much faster than loading all data.

    Returns list of dicts: [{symbol, name, close, ...}]
    """
    if top_n is None:
        top_n = settings.MAX_STOCKS_TO_ANALYZE

    from data.store import load_latest_snapshot

    if master is not None:
        latest_date = master['date'].max()
        latest = master[master['date'] == latest_date].copy()
    else:
        latest = load_latest_snapshot()

    if latest.empty:
        return []

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
