"""
Efinance data source (stub — EastMoney scraper, lighter than akshare).

Native batch query support via get_quote_history() accepting a list of codes.
Not yet fully implemented — use akshare for EastMoney access for now.
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from loguru import logger

from .base import DataSource, normalize_columns


class EfinanceDataSource(DataSource):
    """Daily K-line via efinance (EastMoney scraper with native batch support).

    NOTE: Stub implementation.  Install with: pip install efinance
    """

    name = "efinance"

    def is_available(self) -> bool:
        try:
            import efinance as ef  # noqa: F401
            return True
        except ImportError:
            return False

    def get_stock_list(self) -> pd.DataFrame:
        if not self.is_available():
            raise ImportError("efinance not installed")
        import efinance as ef

        df = ef.stock.get_realtime_quotes()
        result = pd.DataFrame()
        result["symbol"] = df["股票代码"].astype(str)
        result["name"] = df["股票名称"].astype(str)
        result["code"] = result["symbol"]
        result = result[result["symbol"].str.match(r"^\d{6}$")]
        logger.info(f"efinance: {len(result)} listed stocks")
        return result.reset_index(drop=True)

    def fetch_daily_kline(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        if not self.is_available():
            logger.warning("efinance not installed — returning None")
            return None
        import efinance as ef

        try:
            result = ef.stock.get_quote_history(
                stock_codes=[symbol],
                beg=start_date.replace("-", ""),
                end=end_date.replace("-", ""),
            )
            if isinstance(result, dict):
                df = result.get(symbol)
            elif isinstance(result, pd.DataFrame):
                df = result
            else:
                return None

            if df is None or df.empty:
                return None

            df = normalize_columns(df, self.name)
            return df
        except Exception:
            return None

    def fetch_batch(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        delay: float = 0.5,
    ) -> dict[str, pd.DataFrame]:
        """Native batch query — fetch multiple symbols in one API call."""
        if not self.is_available():
            logger.warning("efinance not installed — returning {}")
            return {}
        import efinance as ef

        results: dict[str, pd.DataFrame] = {}
        try:
            raw = ef.stock.get_quote_history(
                stock_codes=symbols,
                beg=start_date.replace("-", ""),
                end=end_date.replace("-", ""),
            )
            if isinstance(raw, dict):
                for sym, df in raw.items():
                    if df is not None and not df.empty:
                        df = normalize_columns(df, self.name)
                        if len(df) >= 30:
                            results[sym] = df
            logger.info(f"efinance: batch done — {len(results)}/{len(symbols)} fetched")
        except Exception:
            logger.warning("efinance batch fetch failed")
        return results
