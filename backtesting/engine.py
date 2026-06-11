"""
Walk-forward backtest engine for Adam's Theory signals.

Simulates trading on historical data:
  - Each day, run detection on all available stocks
  - Record trades at market open the next day
  - Exit on stop-loss, trailing stop, or time-based exit
  - Track all trades and compute performance metrics
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from collections import defaultdict

import pandas as pd
import numpy as np
from loguru import logger

from config.settings import settings
from config.schema import TradeRecord
from data.store import ParquetStore
from data.trading_calendar import trading_days_between, next_trading_day
from indicators.market_regime import compute_adx, compute_atr
from indicators.adams_theory import detect_all_clues, has_buy_signal, compute_center_symmetry_projection
from indicators.risk_metrics import compute_risk_score, compute_stop_loss


class BacktestEngine:
    """
    Walk-forward backtest engine.

    Simulates the full signal detection → entry → exit cycle over a
    historical period, producing trade records and performance metrics.
    """

    def __init__(
        self,
        store: ParquetStore,
        start_date: date | str = "2023-01-01",
        end_date: date | str = "2024-12-31",
        max_concurrent: int = 10,
        holding_days_max: int = 20,
    ):
        self.store = store
        self.start_date = date.fromisoformat(start_date) if isinstance(start_date, str) else start_date
        self.end_date = date.fromisoformat(end_date) if isinstance(end_date, str) else end_date
        self.max_concurrent = max_concurrent
        self.holding_days_max = holding_days_max

    def run(self, symbols: list[str] | None = None) -> list[TradeRecord]:
        """
        Execute the walk-forward backtest.

        Args:
            symbols: Stock codes to test on. If None, uses all in store.

        Returns:
            List of TradeRecord for all completed trades.
        """
        if symbols is None:
            symbols = self.store.list_symbols()

        trading_days = trading_days_between(self.start_date, self.end_date)
        if len(trading_days) < 60:
            raise ValueError("Need at least 60 trading days for backtest")

        logger.info(
            "Backtest: {} stocks, {} trading days ({} → {})",
            len(symbols), len(trading_days), self.start_date, self.end_date,
        )

        trades: list[TradeRecord] = []
        open_positions: dict[str, dict] = {}  # symbol → position info

        # Walk forward day by day
        for day_idx, td in enumerate(trading_days[:-1]):  # Need next day for entry
            if day_idx < 60:  # Warmup period for indicator calculation
                continue

            if day_idx % 20 == 0:
                logger.info("Backtest progress: {} / {} days, {} trades so far",
                            day_idx, len(trading_days), len(trades))

            next_td = trading_days[day_idx + 1]

            # ── 1. Check open positions for exits ──────────────────
            self._check_exits(open_positions, td, trades)

            # ── 2. If under max_concurrent, scan for new signals ───
            active_count = len(open_positions)
            if active_count >= self.max_concurrent:
                continue

            # Scan up to 50 symbols per day (performance)
            scan_symbols = symbols[:50]  # Use top 50 for backtest speed
            for sym in scan_symbols:
                if sym in open_positions:
                    continue
                if len(open_positions) >= self.max_concurrent:
                    break

                signal = self._detect_signal_on_date(sym, td)
                if signal:
                    # Enter trade at next day's open
                    df = self.store.load_range(sym, start=next_td - timedelta(days=5), end=next_td + timedelta(days=1))
                    if df is not None and not df.empty:
                        next_bar = df[df["date"] >= pd.Timestamp(next_td)]
                        if not next_bar.empty:
                            entry_price = float(next_bar.iloc[0]["open"])
                            open_positions[sym] = {
                                "entry_date": next_td,
                                "entry_price": entry_price,
                                "stop_loss": signal["stop_loss"],
                                "atr": signal["atr"],
                                "entry_day_idx": day_idx,
                            }

        # Close any remaining positions at end
        last_day = trading_days[-1]
        for sym, pos in list(open_positions.items()):
            df = self.store.load_range(sym, start=last_day, end=last_day + timedelta(days=1))
            if df is not None and not df.empty:
                exit_price = float(df.iloc[-1]["close"])
                pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"] * 100
                trades.append(TradeRecord(
                    symbol=sym, name="", entry_date=pos["entry_date"],
                    entry_price=pos["entry_price"], exit_date=last_day,
                    exit_price=exit_price, exit_reason="time_exit",
                    pnl_pct=round(pnl_pct, 2),
                    holding_days=(last_day - pos["entry_date"]).days,
                ))

        logger.info("Backtest complete: {} trades", len(trades))
        return trades

    def _detect_signal_on_date(self, symbol: str, td: date) -> dict | None:
        """Run Adam's Theory detection as of a historical date."""
        df = self.store.load_range(symbol, start=td - timedelta(days=365), end=td)
        if df is None or len(df) < 60:
            return None

        min_bars = settings.TREND_CHANGE_LOOKBACK + settings.LOOKBACK_BARS + 5
        if len(df) < min_bars:
            return None

        try:
            adx_df = compute_adx(df["high"], df["low"], df["close"], period=settings.ADX_PERIOD)
            current_adx = float(adx_df.iloc[-1][f"ADX_{settings.ADX_PERIOD}"])

            from indicators.market_regime import compute_efficiency_ratio
            er = compute_efficiency_ratio(df["close"], period=settings.ER_PERIOD)

            clues = detect_all_clues(df)
            is_buy, _ = has_buy_signal(clues, current_adx, er)

            if not is_buy:
                return None

            projection = compute_center_symmetry_projection(df)
            risk_score = compute_risk_score(df, current_adx, er, projection, clues)

            if risk_score > settings.MAX_RISK_SCORE:
                return None

            atr_series = compute_atr(df["high"], df["low"], df["close"], period=settings.ATR_PERIOD)
            current_atr = float(atr_series.iloc[-1])
            current_close = float(df["close"].iloc[-1])
            stop_loss = compute_stop_loss(current_close, current_atr)

            return {
                "adx": current_adx, "er": er, "clues": len(clues),
                "risk_score": risk_score, "stop_loss": stop_loss,
                "atr": current_atr, "close": current_close,
            }
        except Exception:
            return None

    def _check_exits(
        self,
        positions: dict[str, dict],
        td: date,
        trades: list[TradeRecord],
    ) -> None:
        """Check open positions for stop-loss or time-based exit."""
        symbols_to_close = []

        for sym, pos in positions.items():
            # Time exit
            days_held = (td - pos["entry_date"]).days
            if days_held >= self.holding_days_max:
                symbols_to_close.append((sym, "time_exit"))
                continue

            # Stop loss check
            df = self.store.load_range(sym, start=td - timedelta(days=2), end=td)
            if df is not None and not df.empty:
                low = float(df["low"].iloc[-1])
                close = float(df["close"].iloc[-1])

                if low <= pos["stop_loss"]:
                    symbols_to_close.append((sym, "stop_loss"))
                    continue

                # Trailing stop: move stop up if price advanced >2 ATR
                if close > pos["entry_price"] + 2 * pos["atr"]:
                    new_stop = close - 2 * pos["atr"]
                    if new_stop > pos["stop_loss"]:
                        pos["stop_loss"] = new_stop

        for sym, reason in symbols_to_close:
            pos = positions.pop(sym)
            df = self.store.load_range(sym, start=td, end=td + timedelta(days=1))
            exit_price = pos["entry_price"]
            if df is not None and not df.empty:
                if reason == "stop_loss":
                    exit_price = pos["stop_loss"]
                else:
                    exit_price = float(df.iloc[-1]["close"])

            pnl_pct = (exit_price - pos["entry_price"]) / pos["entry_price"] * 100
            trades.append(TradeRecord(
                symbol=sym, name="",
                entry_date=pos["entry_date"],
                entry_price=round(pos["entry_price"], 2),
                exit_date=td,
                exit_price=round(exit_price, 2),
                exit_reason=reason,
                pnl_pct=round(pnl_pct, 2),
                holding_days=(td - pos["entry_date"]).days,
            ))
