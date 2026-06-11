"""
Stock universe management: fetch the full stock list, filter/pre-screen candidates
for deep analysis.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd
from loguru import logger

from config.settings import settings
from data.fetcher import fetch_spot_list
from data.store import ParquetStore

# ST / delisting / BJ patterns to exclude
_EXCLUDE_PATTERNS = [
    r"ST",           # ST / *ST
    r"\*ST",
    r"退市",
    r"PT",
    r"N\d",          # IPO first-day naming
    r"C\d",
]


def _is_excluded(name: str, code: str) -> bool:
    """Return True if the stock should be excluded from universe."""
    for pattern in _EXCLUDE_PATTERNS:
        if re.search(pattern, name):
            return True
        if re.search(pattern, code):
            return True
    return False


def load_stock_universe(store: ParquetStore | None = None) -> pd.DataFrame:
    """
    Fetch the full A-share spot list, clean it, and return as a DataFrame
    with standardized columns. Also updates store metadata.

    Columns: code, name, exchange, close, market_cap, volume, amount, change_pct
    """
    raw = fetch_spot_list()
    if raw is None:
        logger.warning("Failed to fetch spot list — attempting to load from store")
        if store is not None:
            meta = store.all_meta()
            if not meta.empty:
                return meta
        raise RuntimeError("Cannot load stock universe: akshare fetch failed, no store data")

    # Standardise column names
    col_map = {
        "代码": "code",
        "名称": "name",
        "最新价": "close",
        "涨跌幅": "change_pct",
        "成交量": "volume",
        "成交额": "amount",
        "总市值": "market_cap",
        "换手率": "turnover_rate",
        "市盈率-动态": "pe",
        "市净率": "pb",
    }
    existing = {k: v for k, v in col_map.items() if k in raw.columns}
    df = raw.rename(columns=existing)

    # Determine exchange from code
    df["exchange"] = df["code"].apply(_guess_exchange)

    # Strip exchange suffix if present
    df["code"] = df["code"].str.replace(r"\.(SH|SZ|BJ)$", "", regex=True)

    # Exclude ST, delisting, IPO, BJ
    df["_exclude"] = df.apply(lambda r: _is_excluded(str(r["name"]), str(r["code"])), axis=1)
    excluded = df[df["_exclude"]]
    df = df[~df["_exclude"]].copy()
    df.drop(columns=["_exclude"], inplace=True)

    logger.info(
        "Stock universe: {} total, {} excluded (ST/BJ/etc.), {} remain",
        len(df) + len(excluded), len(excluded), len(df)
    )

    # Update store metadata
    if store is not None:
        for _, row in df.iterrows():
            store.update_meta(
                symbol=str(row["code"]),
                name=str(row.get("name", "")),
                exchange=str(row.get("exchange", "")),
                market_cap=float(row["market_cap"]) if pd.notna(row.get("market_cap")) else None,
            )

    return df


def pre_screen_candidates(
    universe: pd.DataFrame,
    store: ParquetStore,
    top_n: int | None = None,
) -> list[dict]:
    """
    Filter and rank the stock universe for deep analysis.

    Pre-screen steps:
    1. Remove stocks with price < MIN_PRICE
    2. Remove new listings (< MIN_LISTING_DAYS of data)
    3. Score by composite = volume × price × abs(change_pct)
    4. Return top N candidates

    Returns list of dicts: [{symbol, name, close, exchange, market_cap, ...}]
    """
    if top_n is None:
        top_n = settings.MAX_STOCKS_TO_ANALYZE

    df = universe.copy()

    # Filter 1: Minimum price
    if "close" in df.columns:
        before = len(df)
        df = df[df["close"] >= settings.MIN_PRICE]
        logger.debug("Price filter ≥¥{}: {} → {}", settings.MIN_PRICE, before, len(df))

    # Filter 2: Volume is non-zero (trading)
    if "volume" in df.columns:
        before = len(df)
        df = df[df["volume"] > 0]
        logger.debug("Volume > 0 filter: {} → {}", before, len(df))

    # Filter 3: Minimum listing days (check store)
    before = len(df)
    keep = []
    for _, row in df.iterrows():
        sym = str(row["code"])
        start_d = store.get_start_date(sym)
        if start_d is not None:
            days_since_start = (date.today() - start_d).days
            if days_since_start >= settings.MIN_LISTING_DAYS:
                keep.append(True)
            else:
                keep.append(False)
        else:
            # No data yet — keep it for now, will be filtered later
            keep.append(True)
    df = df[keep].copy()
    logger.debug("Listing days ≥{} filter: {} → {}", settings.MIN_LISTING_DAYS, before, len(df))

    if df.empty:
        logger.warning("No stocks pass pre-screen filters!")
        return []

    # Composite score: volume * price * abs(change) → higher = more "active"
    df["score"] = (
        df["volume"].fillna(0).astype(float)
        * df["close"].fillna(0).astype(float)
        * df["change_pct"].fillna(0).abs()
    )

    df = df.sort_values("score", ascending=False)
    df = df.head(top_n)

    logger.info("Pre-screen: selected top {} candidates from {} eligible", len(df), top_n)

    return df[["code", "name", "close", "exchange", "market_cap", "score"]].to_dict("records")


def _guess_exchange(code: str) -> str:
    """Infer exchange from stock code prefix."""
    code = str(code).replace(".SH", "").replace(".SZ", "").replace(".BJ", "")
    if code.startswith(("60", "68")):
        return "SH"
    elif code.startswith(("00", "30", "002")):
        return "SZ"
    elif code.startswith(("8", "4")):
        return "BJ"
    return "UNKNOWN"
