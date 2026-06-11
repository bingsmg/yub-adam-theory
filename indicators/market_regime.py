"""Market regime indicators: ADX, ATR, Efficiency Ratio."""

from __future__ import annotations

import numpy as np
import pandas as pd


def compute_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.DataFrame:
    """
    Compute ADX, +DI, -DI using Wilder's method via pandas-ta.

    Returns DataFrame with columns: ADX_14, DMP_14, DMN_14
    """
    import pandas_ta as ta

    adx_df = ta.adx(high=high, low=low, close=close, length=period)
    # pandas-ta returns ADX_{period}, DMP_{period}, DMN_{period}
    return adx_df


def compute_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Compute Average True Range."""
    import pandas_ta as ta

    return ta.atr(high=high, low=low, close=close, length=period)


def compute_efficiency_ratio(close: pd.Series, period: int = 20) -> float:
    """
    Efficiency Ratio (Kaufman).

    ER = |Net_Change| / Sum(|Price_Change_i|)

    Range: 0 (pure random walk / noise) to 1 (perfect trend).

    Returns the latest ER value as a float.
    """
    if len(close) < period + 1:
        return 0.0

    segment = close.iloc[-(period + 1):]
    net_change = abs(segment.iloc[-1] - segment.iloc[0])
    sum_abs_changes = segment.diff().abs().sum()

    if sum_abs_changes == 0:
        return 0.0

    return net_change / sum_abs_changes


def compute_efficiency_ratio_series(close: pd.Series, period: int = 20) -> pd.Series:
    """
    Efficiency Ratio as a rolling series.

    Returns a Series with the same index as close, with NaN for window < period.
    """
    net_change = close.diff(period).abs()
    sum_abs = close.diff().abs().rolling(period).sum()
    er = net_change / sum_abs
    return er.clip(0, 1)


def classify_trend_strength(adx: float, er: float, adx_threshold: float = 25.0) -> str:
    """
    Classify trend strength based on ADX and Efficiency Ratio.

    Returns: "strong" | "weak" | "none"
    """
    if adx >= adx_threshold and er >= 0.3:
        return "strong"
    elif adx >= 20.0 or er >= 0.2:
        return "weak"
    return "none"


def compute_sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(window=period).mean()


def compute_ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()
