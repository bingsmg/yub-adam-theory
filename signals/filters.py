"""
Pre-screen filters: exclude ST, penny stocks, new listings, illiquid stocks
before the main detection pipeline runs.
"""

from __future__ import annotations

import re
from datetime import date, datetime

import pandas as pd
from loguru import logger

from config.settings import settings
from data.store import ParquetStore

# Patterns for excluded stocks
_ST_PATTERNS = re.compile(r"ST|\*ST|退市|退|PT")


def filter_excluded_names(df: pd.DataFrame, name_col: str = "name") -> pd.DataFrame:
    """Remove ST, *ST, delisting, PT stocks by name."""
    before = len(df)
    mask = ~df[name_col].astype(str).str.contains(_ST_PATTERNS, na=False)
    df = df[mask].copy()
    removed = before - len(df)
    logger.debug("Name filter: removed {} ST/delisting stocks, {} remain", removed, len(df))
    return df


def filter_penny_stocks(
    df: pd.DataFrame,
    price_col: str = "close",
    min_price: float | None = None,
) -> pd.DataFrame:
    """Remove stocks below the minimum price threshold."""
    if price_col not in df.columns:
        return df
    if min_price is None:
        min_price = settings.MIN_PRICE
    before = len(df)
    df = df[df[price_col].astype(float) >= min_price].copy()
    logger.debug("Price filter ≥¥{}: {} → {}", min_price, before, len(df))
    return df


def filter_illiquid(
    df: pd.DataFrame,
    volume_col: str = "volume",
    min_volume_ratio: float | None = None,
) -> pd.DataFrame:
    """Remove stocks with zero or near-zero volume."""
    if volume_col not in df.columns:
        return df
    before = len(df)
    df = df[df[volume_col].astype(float) > 0].copy()
    logger.debug("Liquidity filter (volume > 0): {} → {}", before, len(df))
    return df


def filter_new_listings(
    candidates: list[dict],
    store: ParquetStore,
    min_listing_days: int | None = None,
) -> list[dict]:
    """
    Remove stocks that have been listed for less than min_listing_days.
    Uses store metadata to check data history length.
    """
    if min_listing_days is None:
        min_listing_days = settings.MIN_LISTING_DAYS

    today = date.today()
    filtered = []

    for c in candidates:
        sym = c.get("code", c.get("symbol", ""))
        start_d = store.get_start_date(sym)
        if start_d is None:
            # No data yet; we'll keep it for now (it'll fail later if insufficient data)
            filtered.append(c)
            continue
        days_since_start = (today - start_d).days
        if days_since_start >= min_listing_days:
            filtered.append(c)
        else:
            logger.debug("Skipping {} — listed only {} days", sym, days_since_start)

    logger.debug("Listing age filter: {} → {}", len(candidates), len(filtered))
    return filtered


def rank_by_activity(
    df: pd.DataFrame,
    top_n: int | None = None,
) -> pd.DataFrame:
    """
    Rank stocks by trading activity composite score.

    Score = volume × price × |change_pct|
    Higher score → more active → more likely to produce meaningful signals.
    """
    if top_n is None:
        top_n = settings.MAX_STOCKS_TO_ANALYZE

    if "volume" not in df.columns or "close" not in df.columns:
        return df.head(top_n) if len(df) > top_n else df

    vol = df["volume"].astype(float).fillna(0)
    price = df["close"].astype(float).fillna(0)
    change = df.get("change_pct", pd.Series(0, index=df.index)).astype(float).fillna(0)

    df = df.copy()
    df["_activity_score"] = vol * price * change.abs()
    df = df.sort_values("_activity_score", ascending=False)
    df = df.drop(columns=["_activity_score"])

    result = df.head(top_n)
    logger.info("Activity ranking: selected top {} from {} candidates", len(result), len(df))
    return result
