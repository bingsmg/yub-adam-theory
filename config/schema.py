"""股票推荐管线的 Pydantic 数据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


# ── 指标输出 ───────────────────────────────────────────────────────────

class AdamProjection(BaseModel):
    """中心对称（第二镜像）投影结果。"""
    projected_prices: list[float]      # lookback_bars projected midpoints ahead
    anchor_price: float                 # (close + open) / 2 of the current bar
    convergence_score: float            # 0 (noisy) → 1 (tight convergence)
    projected_direction: Literal["up", "down", "neutral"]
    lookback_used: int = 20


class SignalClue(BaseModel):
    """亚当理论三大入场线索之一。"""
    clue_type: Literal["breakout", "trend_change", "range_expansion"]
    strength: float                     # 0.0 → 1.0
    detail: str                         # Human-readable explanation


# ── 信号输出 ────────────────────────────────────────────────────────────

class AdamSignal(BaseModel):
    """单只股票的完整买入信号。"""
    symbol: str
    name: str
    signal_date: datetime
    direction: Literal["buy", "no_entry"]

    # Core calculations
    projection: AdamProjection
    clues: list[SignalClue]

    # Risk
    atr: float
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
    """完整每日推荐输出。"""
    generated_at: datetime
    market_date: datetime
    total_stocks_analyzed: int
    total_signals_found: int
    recommendations: list[AdamSignal]
    market_regime_desc: str = ""        # e.g. "trending", "ranging"


