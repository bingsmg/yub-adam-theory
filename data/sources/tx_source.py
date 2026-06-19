"""
Tencent (腾讯证券) data source via akshare stock_zh_a_hist_tx.

Uses Tencent's free stock history API — not blocked like EastMoney,
and doesn't require a server connection like baostock.  Good middle ground
for reliable data fetching.

Note: Tencent API uses 'amount' for volume (成交量, in 手/lots).
We rename it to 'volume' for downstream consumption.
"""

from __future__ import annotations

import time
from typing import Optional

import pandas as pd
from loguru import logger

from .base import DataSource, normalize_columns, OUTPUT_COLUMNS


class TencentDataSource(DataSource):
    """Daily K-line via akshare → Tencent (腾讯证券)."""

    name = "tencent"

    def __init__(
        self,
        max_retries: int = 3,
        retry_delays: tuple[float, ...] = (3.0, 6.0, 10.0),
    ):
        self._max_retries = max_retries
        self._retry_delays = retry_delays

    def is_available(self) -> bool:
        try:
            import akshare as ak  # noqa: F401
            return True
        except ImportError:
            return False

    # ── Symbol helpers ────────────────────────────────────────────

    @staticmethod
    def _to_tx_symbol(symbol: str) -> str:
        """Convert 6-digit code to Tencent format: 'sh600001' or 'sz000001'.

        Exchange rules (A-share):
          - 60xxxx, 68xxxx → sh (Shanghai main + STAR)
          - 00xxxx, 30xxxx → sz (Shenzhen main + ChiNext)
          - 8xxxxx, 4xxxxx → bj (Beijing — BSE, not supported by tx)
        """
        sym = str(symbol).zfill(6)
        if sym.startswith(("60", "68")):
            return f"sh{sym}"
        elif sym.startswith(("00", "30")):
            return f"sz{sym}"
        elif sym.startswith(("8", "4")):
            return f"bj{sym}"
        else:
            return f"sz{sym}"  # fallback

    # ── DataSource interface ──────────────────────────────────────

    def get_stock_list(self) -> pd.DataFrame:
        """Get full A-share stock list.

        Uses EastMoney spot snapshot (not Tencent — Tencent doesn't
        have a good stock list API).  Falls back gracefully.
        """
        import akshare as ak

        try:
            df = ak.stock_zh_a_spot_em()
            if df is None or df.empty:
                raise RuntimeError("Empty spot list")

            result = pd.DataFrame()
            result["symbol"] = df["代码"].astype(str).str.zfill(6)
            result["name"] = df["名称"].astype(str)
            result["code"] = result["symbol"]

            result = result[result["symbol"].str.match(r"^\d{6}$")]

            # Exclude ST/delisted
            exclude = df["名称"].str.contains(r"ST|\*ST|退|PT", na=False)
            result = result[~exclude.reindex(result.index, fill_value=False)]

            logger.info(f"tencent: {len(result)} stocks in spot list")
            return result.reset_index(drop=True)

        except Exception:
            # Fallback — can't list via Tencent, try baostock
            logger.warning("tencent: cannot get stock list via EastMoney, trying baostock")
            from .baostock_source import BaostockDataSource
            bs = BaostockDataSource()
            return bs.get_stock_list()

    def fetch_daily_kline(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
    ) -> Optional[pd.DataFrame]:
        """Fetch daily K-line via Tencent with retry."""
        import akshare as ak

        tx_sym = self._to_tx_symbol(symbol)
        start_clean = start_date.replace("-", "")
        end_clean = end_date.replace("-", "")

        last_error = None
        for attempt in range(self._max_retries + 1):
            try:
                df = ak.stock_zh_a_hist_tx(
                    symbol=tx_sym,
                    start_date=start_clean,
                    end_date=end_clean,
                    adjust="qfq",
                    timeout=15.0,
                )

                if df is None or df.empty:
                    return None

                # Tencent columns: date, open, close, high, low, amount
                # 'amount' here is actually volume (成交量 in 手/lots)
                # Rename to match standard OUTPUT_COLUMNS
                df = df.rename(columns={"amount": "volume"})

                # Normalize
                df = normalize_columns(df, self.name)
                if df.empty:
                    return None

                return df

            except Exception as exc:
                last_error = exc
                if attempt < self._max_retries:
                    wait = self._retry_delays[min(attempt, len(self._retry_delays) - 1)]
                    logger.debug(f"tencent: {symbol} retry {attempt+1}/{self._max_retries} after {wait}s")
                    time.sleep(wait)

        logger.debug(f"tencent: {symbol} failed: {last_error}")
        return None

    def fetch_batch(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        delay: float = 0.5,
    ) -> dict[str, pd.DataFrame]:
        """Batch fetch with light delay.

        Tencent doesn't seem to rate-limit aggressively, but a small
        delay keeps things polite.
        """
        return super().fetch_batch(symbols, start_date, end_date, delay=delay)
