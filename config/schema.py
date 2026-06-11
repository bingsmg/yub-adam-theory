"""Pydantic data models for the stock recommendation pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# ── Raw data ──────────────────────────────────────────────────────────

class OHLCVBar(BaseModel):
    """A single bar of daily OHLCV data."""
    date: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float       # shares (手)
    amount: float        # turnover in RMB
    symbol: str = ""
    name: str = ""


class StockMeta(BaseModel):
    """Metadata for one stock in the universe."""
    symbol: str          # 6-digit code without exchange suffix
    name: str            # Chinese name
    exchange: str        # "SH" | "SZ" | "BJ"
    market_cap: float | None = None  # Total market cap in RMB
    listing_date: datetime | None = None
    last_updated: datetime | None = None
    data_start_date: datetime | None = None
    total_bars: int = 0


# ── Indicator outputs ─────────────────────────────────────────────────

class AdamProjection(BaseModel):
    """Result of the center symmetry (second mirror image) projection."""
    projected_prices: list[float]      # lookback_bars projected midpoints ahead
    anchor_price: float                 # (close + open) / 2 of the current bar
    convergence_score: float            # 0 (noisy) → 1 (tight convergence)
    projected_direction: Literal["up", "down", "neutral"]
    lookback_used: int = 20


class SignalClue(BaseModel):
    """One of the three Adam's Theory entry clues."""
    clue_type: Literal["breakout", "trend_change", "range_expansion"]
    strength: float                     # 0.0 → 1.0
    detail: str                         # Human-readable explanation


class MarketRegime(BaseModel):
    """Overall market condition assessment."""
    adx: float
    plus_di: float
    minus_di: float
    atr: float
    efficiency_ratio: float
    trend_strength: Literal["strong", "weak", "none"]


# ── Signal outputs ────────────────────────────────────────────────────

class AdamSignal(BaseModel):
    """Complete buy signal for one stock."""
    symbol: str
    name: str
    signal_date: datetime
    direction: Literal["buy", "no_entry"]

    # Core calculations
    projection: AdamProjection
    clues: list[SignalClue]
    adx: float
    efficiency_ratio: float
    trend_strength: Literal["strong", "weak", "none"]

    # Risk
    atr: float
    volatility_20d: float
    risk_score: float                   # 1 (safest) → 10 (riskiest)
    stop_loss_price: float
    projected_entry_price: float

    # Context
    current_close: float
    volume_ratio: float                 # current volume / 20d avg volume
    market_cap: float | None = None

    # Reason
    reason: str = ""


class DailyRecommendation(BaseModel):
    """Full daily recommendation output."""
    generated_at: datetime
    market_date: datetime
    total_stocks_analyzed: int
    total_signals_found: int
    recommendations: list[AdamSignal]
    index_adx: float | None = None      # CSI 300 ADX
    market_regime_desc: str = ""        # e.g. "trending", "ranging"


# ── Backtest types ────────────────────────────────────────────────────

class TradeRecord(BaseModel):
    """A single completed trade for backtesting."""
    symbol: str
    name: str
    entry_date: datetime
    entry_price: float
    exit_date: datetime
    exit_price: float
    exit_reason: Literal["stop_loss", "trailing_stop", "time_exit", "signal_reverse"]
    pnl_pct: float                      # Percentage P&L
    holding_days: int


class BacktestResult(BaseModel):
    """Full backtest performance summary."""
    total_trades: int
    win_rate: float                     # 0.0 → 1.0
    avg_win_pct: float
    avg_loss_pct: float
    profit_factor: float                # gross_profit / gross_loss
    sharpe_ratio: float                 # annualized
    max_drawdown_pct: float
    total_return_pct: float
    trades: list[TradeRecord]
