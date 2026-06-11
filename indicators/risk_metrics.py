"""
Risk scoring for Adam's Theory signals.

6-factor composite risk model (1 = safest, 10 = riskiest):
  1. Trend reliability (30%) — stronger ADX + higher ER = lower risk
  2. Volatility (20%) — higher vol = riskier
  3. ATR/Price ratio (15%) — wider stops = riskier
  4. Projection convergence (15%) — lower convergence = riskier
  5. Volume confirmation (10%) — lower relative volume = higher fakeout risk
  6. Clue count bonus (10%) — more clues = lower risk
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.schema import AdamProjection, SignalClue
from config.settings import settings


def compute_risk_score(
    df: pd.DataFrame,
    adx: float,
    er: float,
    projection: AdamProjection,
    clues: list[SignalClue],
) -> float:
    """
    Compute composite risk score for a signal.

    Returns float 1.0 (safest) to 10.0 (riskiest).
    """
    current = df.iloc[-1]
    close = float(current["close"])

    # Ensure we have enough data for calculations
    if len(df) < 30:
        return 7.0  # Default moderate-high risk for insufficient data

    # ── Factor 1: Trend Reliability (30%) ──
    # Higher ADX + ER → lower risk
    # ADX: 50 → score 0, 25 → score 5, 10 → score 8
    adx_risk = max(0.0, min(10.0, 10.0 - adx / 5.0))
    # ER: 1.0 → score 0, 0.5 → score 5, 0.1 → score 9
    er_risk = max(0.0, min(10.0, 10.0 - er * 10.0))
    trend_risk = 0.5 * adx_risk + 0.5 * er_risk

    # ── Factor 2: Volatility Risk (20%) ──
    # 20-day annualized volatility
    returns = df["close"].pct_change().dropna()
    if len(returns) >= 20:
        recent_returns = returns.iloc[-20:]
        daily_vol = float(recent_returns.std())
        annual_vol = daily_vol * np.sqrt(252)
    else:
        daily_vol = float(returns.std())
        annual_vol = daily_vol * np.sqrt(252)

    # Scale: 10% annual vol → score 1, 50% → score 5, 100% → score 10
    vol_risk = min(10.0, max(1.0, annual_vol * 100 / 10.0))

    # ── Factor 3: ATR/Price Ratio (15%) ──
    # ATR as % of price
    if len(df) >= 15:
        tr_list = []
        for i in range(-14, 1):
            row = df.iloc[i]
            prev_row = df.iloc[i - 1] if i > -len(df) else row
            tr = max(
                row["high"] - row["low"],
                abs(row["high"] - prev_row["close"]),
                abs(row["low"] - prev_row["close"]),
            )
            tr_list.append(tr)
        atr = float(np.mean(tr_list))
    else:
        atr = float(df["high"].iloc[-1] - df["low"].iloc[-1])

    atr_pct = (atr / close) * 100 if close > 0 else 1.0
    # 0.5% ATR → 1, 2.5% → 5, 5% → 10
    atr_risk = min(10.0, max(1.0, atr_pct * 2.0))

    # ── Factor 4: Projection Convergence (15%) ──
    # Higher convergence → lower risk
    conv_risk = max(0.0, min(10.0, (1.0 - projection.convergence_score) * 10.0))

    # ── Factor 5: Volume Confirmation (10%) ──
    if len(df) >= 6:
        current_vol = float(df["volume"].iloc[-1])
        avg_vol_5d = float(df["volume"].iloc[-6:-1].mean())
        if avg_vol_5d > 0:
            vol_ratio = current_vol / avg_vol_5d
        else:
            vol_ratio = 1.0
    else:
        vol_ratio = 1.0

    if vol_ratio > 2.0:
        volume_risk = 1.0   # Very strong volume confirmation → low risk
    elif vol_ratio > 1.5:
        volume_risk = 2.5
    elif vol_ratio > 1.0:
        volume_risk = 4.0
    elif vol_ratio > 0.7:
        volume_risk = 6.0
    elif vol_ratio > 0.5:
        volume_risk = 8.0
    else:
        volume_risk = 10.0  # Extremely low volume → very high risk

    # ── Factor 6: Clue Count Bonus (10%) ──
    clue_count = len(clues)
    if clue_count >= 3:
        clue_risk = 1.0           # All three clues → very low risk from this factor
    elif clue_count == 2:
        # Average strength of clues matters
        avg_strength = np.mean([c.strength for c in clues])
        if avg_strength > 0.6:
            clue_risk = 2.0
        else:
            clue_risk = 3.5
    elif clue_count == 1:
        c = clues[0]
        if c.strength > 0.7:
            clue_risk = 4.0
        elif c.strength > 0.5:
            clue_risk = 5.5
        else:
            clue_risk = 7.0
    else:
        clue_risk = 10.0          # Should not happen if we have a signal

    # ── Weighted composite ──
    weights = [0.30, 0.20, 0.15, 0.15, 0.10, 0.10]
    component_scores = [trend_risk, vol_risk, atr_risk, conv_risk, volume_risk, clue_risk]

    risk_score = sum(w * s for w, s in zip(weights, component_scores))

    # Clamp to 1-10
    risk_score = max(1.0, min(10.0, risk_score))

    return round(risk_score, 1)


def risk_label(score: float) -> str:
    """Human-readable risk label."""
    if score <= 3.0:
        return "Low Risk"
    elif score <= 5.0:
        return "Moderate Risk"
    elif score <= 7.0:
        return "Elevated Risk"
    elif score <= 8.5:
        return "High Risk"
    else:
        return "Speculative"


def compute_stop_loss(entry_price: float, atr: float, multiple: float | None = None) -> float:
    """Compute stop-loss price: entry - N * ATR."""
    if multiple is None:
        multiple = settings.STOP_LOSS_ATR_MULTIPLE
    return round(entry_price - multiple * atr, 2)
