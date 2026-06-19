"""
Market regime detection — classify the current market environment.

Pure price-action based classification into three regimes:
- trending_up / trending_down: directional movement (ADX-like assessment)
- ranging: sideways / consolidation
- volatile: high volatility regardless of direction

Used to provide context for Adam's Theory signals — breakouts are more
significant after consolidation; trend changes matter more in trending markets.
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from loguru import logger


def detect_market_regime(
    df: pd.DataFrame,
    lookback: int = 40,
    vol_lookback: int = 20,
    trend_threshold_pct: float = 5.0,
    consolidation_range_pct: float = 3.0,
) -> str:
    """
    Classify the current market regime based on recent price action.

    Algorithm:
      1. Compare price change over lookback: >5% up = trending_up,
         <-5% down = trending_down
      2. Check volatility (ATR / close ratio): >3% = volatile
      3. Check range tightness: <3% = consolidation/ranging
      4. Otherwise = neutral/ranging

    Args:
        df: OHLCV DataFrame with DatetimeIndex.
        lookback: Bars for trend assessment.
        vol_lookback: Bars for volatility calculation.
        trend_threshold_pct: Min % price change to classify as trending.
        consolidation_range_pct: Max % range for consolidation classification.

    Returns:
        One of: "trending_up", "trending_down", "ranging", "volatile"
    """
    if len(df) < lookback:
        return "ranging"  # Not enough data, assume ranging

    recent = df.iloc[-lookback:]
    current_close = float(recent["close"].iloc[-1])
    start_close = float(recent["close"].iloc[0])

    # 1. Directional bias from net price change
    net_change_pct = (current_close - start_close) / start_close * 100

    # 2. Volatility: ATR / average close over vol_lookback
    vol_df = df.iloc[-vol_lookback:]
    atr = _compute_atr(vol_df)
    avg_close = float(vol_df["close"].mean())
    vol_pct = (atr / avg_close * 100) if avg_close > 0 else 0

    # 3. Range tightness: (max_high - min_low) / avg_close over lookback
    range_high = float(recent["high"].max())
    range_low = float(recent["low"].min())
    range_pct = (range_high - range_low) / float(recent["close"].mean()) * 100

    # Classification logic
    if vol_pct > 4.0:
        regime = "volatile"  # High volatility dominates
    elif range_pct < consolidation_range_pct:
        regime = "ranging"   # Tight range = consolidation
    elif net_change_pct > trend_threshold_pct:
        # Check monotonicity: is the trend consistent or just a gap?
        if _is_monotonic(recent["close"], direction="up"):
            regime = "trending_up"
        else:
            regime = "ranging"
    elif net_change_pct < -trend_threshold_pct:
        if _is_monotonic(recent["close"], direction="down"):
            regime = "trending_down"
        else:
            regime = "ranging"
    else:
        regime = "ranging"  # Mild net change = ranging

    return regime


def describe_market_regime(regime: str) -> str:
    """Return a Chinese-language description of the market regime."""
    descriptions = {
        "trending_up": "上升趋势 — 价格持续走高，适合顺势买入，注意追高风险",
        "trending_down": "下降趋势 — 价格持续走低，逆势买入需谨慎，控制仓位",
        "ranging": "震荡盘整 — 价格在区间内波动，突破信号更值得关注",
        "volatile": "高波动 — 价格波动剧烈，建议缩小仓位，严格止损",
    }
    return descriptions.get(regime, f"未知 ({regime})")


def regime_risk_adjustment(regime: str) -> float:
    """
    Return a risk adjustment multiplier for the current regime.
    - trending_up: signals are more reliable (0.9)
    - ranging: signals need confirmation (1.0 — neutral)
    - trending_down: counter-trend risk (1.2)
    - volatile: unpredictable (1.15)
    """
    adjustments = {
        "trending_up": 0.9,
        "trending_down": 1.2,
        "ranging": 1.0,
        "volatile": 1.15,
    }
    return adjustments.get(regime, 1.0)


# ── Internal helpers ────────────────────────────────────────────────────────

def _compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Compute ATR (Average True Range) for the given DataFrame."""
    if len(df) < 2:
        return 0.0
    high = df["high"].astype(float)
    low = df["low"].astype(float)
    close = df["close"].astype(float)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    true_range = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return float(true_range.iloc[-min(period, len(true_range)):].mean())


def _is_monotonic(series: pd.Series, direction: str = "up") -> bool:
    """
    Check if a series is roughly monotonic (consistent trend).
    Uses linear regression slope: positive = trending up, negative = down.
    """
    if len(series) < 5:
        return False
    y = series.astype(float).values
    x = np.arange(len(y))
    slope = np.polyfit(x, y, 1)[0]
    if direction == "up":
        return slope > 0
    return slope < 0
