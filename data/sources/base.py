"""
Abstract base class for A-share data sources.

Every data source must:
  - Return DataFrames with standardized English column names
  - Use QFQ (forward-adjusted) prices
  - Convert all OHLCV columns to numeric types
  - Return None on failure (never raise)
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from typing import Optional

import pandas as pd
from loguru import logger

# Canonical output columns — every source must produce these
OUTPUT_COLUMNS = ["date", "open", "high", "low", "close", "volume", "amount", "symbol", "name"]

# Chinese → English column mapping (used by akshare, efinance, etc.)
CN_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
    "股票代码": "symbol",
    "股票名称": "name",
    "涨跌幅": "change_pct",
    "换手率": "turnover",
}


def normalize_columns(df: pd.DataFrame, source_name: str) -> pd.DataFrame:
    """Map source-specific columns to canonical English names.

    Handles both Chinese column names (akshare/efinance) and already-English
    names (baostock).  Returns a DataFrame with at least OUTPUT_COLUMNS.
    """
    if df.empty:
        return df

    renamed = df.rename(columns=CN_COLUMN_MAP)

    # Convert numeric columns
    for col in ["open", "high", "low", "close", "volume", "amount"]:
        if col in renamed.columns:
            renamed[col] = pd.to_numeric(renamed[col], errors="coerce")

    # Ensure date column
    if "date" in renamed.columns:
        renamed["date"] = pd.to_datetime(renamed["date"], errors="coerce")

    # Drop rows with no close price
    if "close" in renamed.columns:
        renamed = renamed.dropna(subset=["close"])

    # Keep only canonical columns that exist
    keep = [c for c in OUTPUT_COLUMNS if c in renamed.columns]
    result = renamed[keep].copy()

    if len(result) != len(df):
        logger.debug(f"{source_name}: filtered {len(df) - len(result)} bad rows")

    return result


class DataSource(ABC):
    """Abstract interface for an A-share daily K-line data provider."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """Check whether this source can be used right now (imports work, etc.)."""
        ...

    @abstractmethod
    def get_stock_list(self) -> pd.DataFrame:
        """Return all listed A-share stocks.

        Returns DataFrame with columns: [symbol, name, code]
        where `code` is the exchange-prefixed form (e.g. 'sh.600519').
        """
        ...

    @abstractmethod
    def fetch_daily_kline(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch daily OHLCV for a single stock.

        Args:
            symbol: 6-digit code (e.g. '600519').
            start_date: 'YYYY-MM-DD'.
            end_date: 'YYYY-MM-DD'.

        Returns:
            DataFrame with canonical columns, or None on failure.
            Prices must be QFQ (forward-adjusted).
        """
        ...

    def fetch_batch(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        delay: float = 0.5,
    ) -> dict[str, pd.DataFrame]:
        """Default sequential batch fetch.  Override for source-specific batching.

        Returns dict mapping symbol → DataFrame (symbols that failed are omitted).
        """
        results: dict[str, pd.DataFrame] = {}
        t0 = time.time()

        for i, sym in enumerate(symbols):
            if i > 0 and delay > 0:
                time.sleep(delay)

            try:
                df = self.fetch_daily_kline(sym, start_date, end_date)
                if df is not None and not df.empty:
                    results[sym] = df
            except Exception:
                logger.debug(f"{self.name}: fetch failed for {sym}")

            if (i + 1) % 200 == 0:
                elapsed = time.time() - t0
                rate = (i + 1) / elapsed if elapsed > 0 else 0
                remaining = (len(symbols) - i - 1) / rate if rate > 0 else 0
                logger.info(
                    f"  {self.name}: {i+1}/{len(symbols)} — "
                    f"{len(results)} ok — {elapsed:.0f}s elapsed, ~{remaining:.0f}s left"
                )

        logger.info(f"{self.name}: batch done — {len(results)}/{len(symbols)} fetched")
        return results

    def __repr__(self) -> str:
        return f"<{self.name}>"
