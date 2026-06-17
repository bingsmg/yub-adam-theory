"""
Baostock data source implementation.

Uses baostock's own data server (not a scraper).  No rate limits,
but sequential-only and ~1.5s per stock.  Session refreshed every
200 stocks to prevent timeout.
"""

from __future__ import annotations

import socket
import time
from typing import Optional

import pandas as pd
from loguru import logger

from .base import DataSource, normalize_columns, OUTPUT_COLUMNS


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


class BaostockDataSource(DataSource):
    """Daily K-line via baostock query_history_k_data_plus()."""

    name = "baostock"

    def __init__(self, session_refresh_every: int = 200, socket_timeout: int = 30):
        self._session_stocks = 0
        self._session_refresh = session_refresh_every
        self._socket_timeout = socket_timeout
        self._logged_in = False

    def is_available(self) -> bool:
        try:
            import baostock as bs  # noqa: F401
            return True
        except ImportError:
            return False

    # ── session management ──────────────────────────────────────

    def _login(self) -> None:
        import baostock as bs

        bs.login()
        socket.setdefaulttimeout(self._socket_timeout)
        self._logged_in = True
        self._session_stocks = 0

    def _logout(self) -> None:
        import baostock as bs

        try:
            bs.logout()
        except Exception:
            pass
        self._logged_in = False

    def _maybe_refresh(self) -> None:
        if self._session_stocks > 0 and self._session_stocks % self._session_refresh == 0:
            logger.debug(f"baostock: refreshing session after {self._session_stocks} stocks")
            self._logout()
            time.sleep(1)
            self._login()

    # ── DataSource interface ────────────────────────────────────

    def get_stock_list(self) -> pd.DataFrame:
        """Get full A-share stock list via baostock query_stock_basic()."""
        import baostock as bs

        self._login()
        try:
            rs = bs.query_stock_basic()
            all_data = []
            while (rs.error_code == "0") & rs.next():
                all_data.append(rs.get_row_data())

            if not all_data:
                raise RuntimeError("baostock returned empty stock list")

            df = pd.DataFrame(all_data, columns=["code", "name", "ipo_date", "out_date", "type", "status"])

            # type='1' = stock, status='1' = listed
            df = df[(df["type"] == "1") & (df["status"] == "1")]

            # Extract 6-digit symbol from 'sh.600519'
            df["symbol"] = df["code"].str.replace(r"^(sh|sz|bj)\.", "", regex=True)

            logger.info(f"baostock: {len(df)} listed stocks")
            return df[["symbol", "name", "code"]].reset_index(drop=True)

        finally:
            # Keep session alive for subsequent data fetches
            pass

    def fetch_daily_kline(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        max_retries: int = 3,
    ) -> Optional[pd.DataFrame]:
        import baostock as bs

        if not self._logged_in:
            self._login()

        baocode = _baostock_code(symbol)

        for attempt in range(max_retries + 1):
            self._maybe_refresh()

            try:
                rs = bs.query_history_k_data_plus(
                    baocode,
                    "date,open,high,low,close,volume,amount",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d",
                    adjustflag="2",  # QFQ
                )

                data = []
                while (rs.error_code == "0") and rs.next():
                    data.append(rs.get_row_data())

                self._session_stocks += 1

                if not data:
                    return None

                df = pd.DataFrame(data, columns=["date", "open", "high", "low", "close", "volume", "amount"])
                df = normalize_columns(df, self.name)
                if df.empty:
                    return None

                return df

            except OSError as exc:
                # WinError 10054: remote host forcibly closed connection
                self._session_stocks += 1
                if attempt < max_retries:
                    wait = 2 ** attempt  # 1s, 2s, 4s
                    logger.debug(f"baostock: {symbol} connection reset, retry {attempt+1}/{max_retries} after {wait}s")
                    self._logout()
                    time.sleep(wait)
                    self._login()
                else:
                    logger.debug(f"baostock: {symbol} failed after {max_retries} retries: {exc}")
                    return None

            except Exception:
                self._session_stocks += 1
                return None

        return None

    def fetch_batch(
        self,
        symbols: list[str],
        start_date: str,
        end_date: str,
        delay: float = 0.0,
    ) -> dict[str, pd.DataFrame]:
        """Sequential batch with session refresh every 200 stocks.

        Baostock has no rate limit so delay defaults to 0.
        """
        self._login()
        try:
            return super().fetch_batch(symbols, start_date, end_date, delay=delay)
        finally:
            self._logout()

    def __del__(self) -> None:
        if self._logged_in:
            self._logout()
