"""
Akshare data source implementation.

Scrapes EastMoney (东方财富) for daily K-line data.  Faster than baostock
but subject to anti-scraping measures.  Uses retry + exponential backoff.
"""

from __future__ import annotations

import time
from typing import Optional

import pandas as pd
from loguru import logger

from .base import DataSource, normalize_columns

# Chinese column names returned by akshare stock_zh_a_hist()
AK_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}

# Columns returned by akshare stock_zh_a_spot_em()
AK_SPOT_COLUMNS = {
    "代码": "symbol",
    "名称": "name",
}


class AkshareDataSource(DataSource):
    """Daily K-line via akshare (EastMoney scraper)."""

    name = "akshare"

    def __init__(
        self,
        max_retries: int = 3,
        retry_delays: tuple[float, ...] = (5.0, 10.0, 15.0),
    ):
        self._max_retries = max_retries
        self._retry_delays = retry_delays

    def is_available(self) -> bool:
        try:
            import akshare as ak  # noqa: F401
            return True
        except ImportError:
            return False

    # ── DataSource interface ────────────────────────────────────

    def get_stock_list(self) -> pd.DataFrame:
        """Get full A-share stock list via akshare spot snapshot.

        Returns DataFrame with columns: [symbol, name, code]
        where `code` is set to the raw 6-digit symbol (no exchange prefix).
        """
        import akshare as ak

        logger.info("akshare: fetching spot list...")
        df = ak.stock_zh_a_spot_em()

        if df is None or df.empty:
            raise RuntimeError("akshare returned empty spot list")

        # Map columns
        result = pd.DataFrame()
        result["symbol"] = df["代码"].astype(str).str.zfill(6)
        result["name"] = df["名称"].astype(str)
        result["code"] = result["symbol"]  # Akshare uses plain 6-digit codes

        # Filter out indices, ETFs, etc. — keep only 6-digit numeric codes
        result = result[result["symbol"].str.match(r"^\d{6}$")]

        # Exclude ST/*ST/delisted stocks
        if "名称" in df.columns:
            exclude_pattern = df["名称"].str.contains(r"ST|\*ST|退|PT|N\D|C\D", na=False)
            result = result[~exclude_pattern.reindex(result.index, fill_value=False)]

        logger.info(f"akshare: {len(result)} listed stocks")
        return result.reset_index(drop=True)

    def fetch_daily_kline(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch daily K-line via akshare with retry + backoff."""
        import akshare as ak

        start_clean = start_date.replace("-", "")
        end_clean = end_date.replace("-", "")

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                df = ak.stock_zh_a_hist(
                    symbol=symbol,
                    period="daily",
                    start_date=start_clean,
                    end_date=end_clean,
                    adjust="qfq",
                )

                if df is None or df.empty:
                    return None

                # Rename and normalize
                df = df.rename(columns=AK_COLUMN_MAP)
                df = normalize_columns(df, self.name)
                if df.empty:
                    return None

                return df

            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries:
                    wait = self._retry_delays[min(attempt, len(self._retry_delays) - 1)]
                    logger.debug(f"akshare: {symbol} retry {attempt+1}/{self._max_retries} after {wait}s")
                    time.sleep(wait)

        logger.debug(f"akshare: {symbol} failed after {self._max_retries} retries: {last_error}")
        return None

    def fetch_batch(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        delay: float = 1.0,
    ) -> dict[str, pd.DataFrame]:
        """Batch with conservative 1s delay to avoid EastMoney rate limiting."""
        return super().fetch_batch(symbols, start_date, end_date, delay=delay)
