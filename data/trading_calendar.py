"""Trading calendar utilities — detect trading days, next trading day, etc."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from functools import lru_cache

import pandas as pd
from loguru import logger

try:
    import akshare as ak
except ImportError:
    ak = None


@lru_cache(maxsize=1)
def get_trading_calendar(start_date: str = "20100101", end_date: str | None = None) -> pd.DataFrame:
    """
    Fetch and cache A-share trading calendar.

    Returns DataFrame with column 'trade_date' of datetime64.
    """
    if end_date is None:
        end_date = (datetime.now() + timedelta(days=30)).strftime("%Y%m%d")

    try:
        df = ak.tool_trade_date_hist_sina()
        df["trade_date"] = pd.to_datetime(df["trade_date"])
        df = df[(df["trade_date"] >= start_date) & (df["trade_date"] <= end_date)]
        logger.info("Fetched trading calendar: {} days", len(df))
        return df
    except Exception:
        # Fallback: generate all weekdays, will miss some holidays
        logger.warning("Could not fetch trading calendar, using weekday approximation")
        dates = pd.bdate_range(start=start_date, end=end_date)
        return pd.DataFrame({"trade_date": dates})


def is_trading_day(d: date | datetime) -> bool:
    """Check if a given date is an A-share trading day."""
    if isinstance(d, datetime):
        d = d.date()
    cal = get_trading_calendar()
    return pd.Timestamp(d) in cal["trade_date"].values


def next_trading_day(from_date: date | datetime | None = None, offset: int = 1) -> date:
    """
    Return the next (or previous) trading day.

    offset=1  → next trading day
    offset=-1 → previous trading day
    """
    if from_date is None:
        from_date = date.today()
    if isinstance(from_date, datetime):
        from_date = from_date.date()

    cal = get_trading_calendar()
    dates = cal["trade_date"].dt.date.values

    if offset > 0:
        for d in dates:
            if d > from_date:
                return d
    else:
        rev = list(dates)[::-1]
        for d in rev:
            if d < from_date:
                return d
    return from_date


def most_recent_trading_day(before: date | datetime | None = None) -> date:
    """Return the most recent trading day on or before `before`."""
    return next_trading_day(from_date=before, offset=-1)


def trading_days_between(start: date, end: date) -> list[date]:
    """Return list of trading days in [start, end] inclusive."""
    cal = get_trading_calendar()
    dates = cal["trade_date"].dt.date.values
    return [d for d in dates if start <= d <= end]
