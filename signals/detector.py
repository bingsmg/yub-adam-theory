"""
Signal Detection Pipeline — Pure Adam's Theory.

For each stock:
  1. Load OHLCV data
  2. Run the three condition detectors (breakout, trend change, gap/wide range)
  3. Require >=2 conditions to confirm a buy signal
  4. Find structural stop-loss below the nearest swing low
  5. Compute center symmetry projection as visual confirmation
  6. Build AdamSignal with full reasoning data

No technical indicators (ADX, RSI, etc.) in the gating logic.
"""

from __future__ import annotations

from datetime import date, datetime

import numpy as np
import pandas as pd
from loguru import logger

from config.schema import AdamSignal
from config.settings import settings
from indicators.adams_theory import (
    compute_center_symmetry_projection,
    detect_all_three_conditions,
    check_buy_signal,
    find_structural_stop,
)


def detect_signal(
    df: pd.DataFrame,
    symbol: str,
    name: str = "",
    signal_date: date | datetime | None = None,
    market_cap: float | None = None,
) -> AdamSignal | None:
    """
    Run pure Adam's Theory signal detection on one stock.

    Args:
        df: OHLCV DataFrame with [open, high, low, close, volume].
        symbol: 6-digit stock code.
        name: Chinese stock name.
        signal_date: Analysis date (default: last date in df).
        market_cap: Market cap for context.

    Returns:
        AdamSignal if >=2 conditions met, None otherwise.
    """
    min_bars = settings.TREND_CHANGE_LOOKBACK + settings.LOOKBACK_BARS + 5
    if len(df) < min_bars:
        logger.debug("{}: insufficient data ({} < {} bars)", symbol, len(df), min_bars)
        return None

    required = {"open", "high", "low", "close", "volume"}
    if not required.issubset(df.columns):
        missing = required - set(df.columns)
        logger.error("{}: missing columns {}", symbol, missing)
        return None

    df = df.dropna(subset=["open", "high", "low", "close"])
    if len(df) < min_bars:
        return None

    if signal_date is None:
        signal_date = pd.to_datetime(df["date"].iloc[-1]).date() if "date" in df.columns else date.today()

    # ── 1. Detect the three conditions ────────────────────────────
    clues = detect_all_three_conditions(df)

    # ── 2. Require >=2 of 3 ──────────────────────────────────────
    is_buy, gate_reason = check_buy_signal(clues)

    if not is_buy:
        logger.debug("{}: {} — no signal", symbol, gate_reason)
        return None

    logger.info("{} [{}]: {} — {} conditions met", symbol, name, gate_reason, len(clues))

    # ── 3. Center symmetry projection ────────────────────────────
    try:
        projection = compute_center_symmetry_projection(df, lookback=settings.LOOKBACK_BARS)
    except Exception as e:
        logger.warning("{}: projection failed — {}", symbol, e)
        projection = None

    # ── 4. Structural stop loss ──────────────────────────────────
    current_close = float(df["close"].iloc[-1])
    stop_loss = find_structural_stop(df, lookback=40)
    stop_pct = (current_close - stop_loss) / current_close * 100

    # ── 5. ATR for reference (not for gating, just context) ──────
    current_atr = round(float(df["high"].iloc[-1] - df["low"].iloc[-1]), 2)

    # ── 6. Volume context ────────────────────────────────────────
    if len(df) >= 21:
        vol_ratio = float(df["volume"].iloc[-1] / df["volume"].iloc[-21:-1].mean())
    else:
        vol_ratio = 1.0

    # ── 7. Compute simple risk score (1-10) ──────────────────────
    # Based purely on: stop distance, projection convergence, clue count
    risk_score = _simple_risk_score(stop_pct, projection, len(clues))

    if risk_score > settings.MAX_RISK_SCORE:
        logger.info("{}: signal suppressed — risk {:.1f} > max {:.1f}", symbol, risk_score, settings.MAX_RISK_SCORE)
        return None

    # ── 8. Build signal ──────────────────────────────────────────
    signal = AdamSignal(
        symbol=str(symbol),
        name=name,
        signal_date=signal_date,
        direction="buy",
        projection=projection or _empty_projection(),
        clues=clues,
        adx=0.0,            # Not used in gating
        efficiency_ratio=0.0,  # Not used in gating
        trend_strength="none",
        atr=round(current_atr, 2),
        volatility_20d=0.0,
        risk_score=round(risk_score, 1),
        stop_loss_price=stop_loss,
        projected_entry_price=round(current_close, 2),
        current_close=round(current_close, 2),
        volume_ratio=round(vol_ratio, 2),
        market_cap=market_cap,
        reason="",  # Filled by explainer
    )

    return signal


def _simple_risk_score(stop_pct: float, projection, clue_count: int) -> float:
    """
    Simple risk score based on structural factors.

    - Stop distance: tighter stop (2-5%) = lower risk
    - Projection convergence: tighter = lower risk
    - Clue count: 3 clues = lower risk than 2
    """
    score = 5.0  # neutral base

    # Stop distance factor
    if stop_pct <= 2.0:
        score -= 1.5  # tight stop, less risk if stopped
    elif stop_pct <= 4.0:
        score -= 0.5
    elif stop_pct >= 8.0:
        score += 1.5  # wide stop, more capital at risk
    elif stop_pct >= 5.0:
        score += 0.5

    # Projection factor
    if projection is not None and projection.convergence_score > 0:
        if projection.convergence_score > 0.7:
            score -= 1.0
        elif projection.convergence_score < 0.3:
            score += 1.0

    # Clue count factor
    if clue_count >= 3:
        score -= 1.0
    # 2 clues = neutral

    return max(1.0, min(10.0, score))


def _empty_projection():
    from config.schema import AdamProjection
    return AdamProjection(
        projected_prices=[], anchor_price=1.0,
        convergence_score=0.0, projected_direction="neutral"
    )
