"""Pydantic data models for the stock recommendation pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


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


