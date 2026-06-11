"""
Adam's Theory of Markets — Core Algorithm.

Pure Adam's Theory implementation per Wilder's original work.
No technical indicators (ADX, RSI, etc.) in the gating logic —
only the three visual clues from the chart.

Three Entry Conditions (Long):
  1. Breakout — price breaks above visible recent highs
  2. Trend Change — prior downtrend/consolidation reverses into uptrend
  3. Gap / Wide Range — gap up or daily range significantly above average

Signal: >= 2 of the 3 conditions must be satisfied simultaneously.

Also implements the center symmetry projection (second mirror image)
as a visual aid for the "one question" rule.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from config.schema import AdamProjection, SignalClue
from config.settings import settings


# ═══════════════════════════════════════════════════════════════════════
# Center Symmetry Projection (the "second image")
# ═══════════════════════════════════════════════════════════════════════

def compute_center_symmetry_projection(
    df: pd.DataFrame,
    lookback: int | None = None,
) -> AdamProjection:
    """
    Adam's Theory center symmetry (second mirror image).

    The trader traces past price on transparent film, flips it horizontally
    then vertically, and aligns the oldest bar with "now". The resulting
    curve is the market's own projection of where price is likely to go.

    Mathematical equivalent:
        Projected[i] = 2 * anchor - historical_midpoint[lookback - 1 - i]

    Args:
        df: OHLCV DataFrame. Most recent row = the "center point" (now).
        lookback: Bars to mirror (default from settings).

    Returns:
        AdamProjection with projected_midpoints, anchor, convergence, direction.
    """
    if lookback is None:
        lookback = settings.LOOKBACK_BARS

    if len(df) < lookback + 2:
        raise ValueError(f"Need at least {lookback + 2} bars, got {len(df)}")

    current = df.iloc[-1]
    anchor = (float(current["close"]) + float(current["open"])) / 2.0

    closes = df["close"].values.astype(float)
    opens = df["open"].values.astype(float)
    highs = df["high"].values.astype(float)
    lows = df["low"].values.astype(float)

    # Historical segment: lookback bars before "now"
    hist_close = closes[-(lookback + 1):-1]
    hist_open = opens[-(lookback + 1):-1]
    hist_high = highs[-(lookback + 1):-1]
    hist_low = lows[-(lookback + 1):-1]

    n = len(hist_close)
    projected_midpoints = []
    projected_highs = []
    projected_lows = []

    for i in range(n):
        hist_idx = n - 1 - i  # most recent past → earliest future
        # Center symmetry: Proj = 2*Anchor - Hist
        # High/Low invert: past high → projected low, past low → projected high
        proj_mid = 2.0 * anchor - (hist_close[hist_idx] + hist_open[hist_idx]) / 2.0
        proj_high = 2.0 * anchor - hist_low[hist_idx]
        proj_low = 2.0 * anchor - hist_high[hist_idx]

        projected_midpoints.append(float(proj_mid))
        projected_highs.append(float(proj_high))
        projected_lows.append(float(proj_low))

    # Direction: compare first few projected bars to anchor
    if len(projected_midpoints) >= 5:
        early = np.mean(projected_midpoints[:5])
        late = np.mean(projected_midpoints[-5:])
        delta_pct = (late - early) / anchor * 100
        if delta_pct > 0.5:
            direction = "up"
        elif delta_pct < -0.5:
            direction = "down"
        else:
            direction = "neutral"
    else:
        direction = "neutral"

    # Convergence: how tightly the projection clusters
    if projected_midpoints:
        std = float(np.std(projected_midpoints))
        convergence = float(1.0 / (1.0 + std / anchor))
        convergence = max(0.0, min(1.0, convergence))
    else:
        convergence = 0.0

    return AdamProjection(
        projected_prices=projected_midpoints,
        anchor_price=round(anchor, 2),
        convergence_score=round(convergence, 4),
        projected_direction=direction,
        lookback_used=lookback,
    )


# ═══════════════════════════════════════════════════════════════════════
# Condition 1: Breakout (突破)
# ═══════════════════════════════════════════════════════════════════════

def detect_breakout(
    df: pd.DataFrame,
    lookback: int | None = None,
) -> SignalClue | None:
    """
    Condition 1 — Breakout (突破):
    Today's closing price breaks above the visible high of the recent period.
    The longer the consolidation before the breakout, the more significant.

    Rule: close >= highest high of the last N bars (excluding today)
    """
    if lookback is None:
        lookback = settings.BREAKOUT_LOOKBACK

    if len(df) < lookback + 2:
        return None

    recent = df.iloc[-(lookback + 1):-1]  # exclude today
    current_close = float(df["close"].iloc[-1])
    highest_high = float(recent["high"].max())
    avg_high = float(recent["high"].mean())

    if current_close < highest_high:
        return None

    # How many of the lookback highs does this close exceed?
    bars_broken = int((df["close"].iloc[-1] > recent["high"]).sum())
    coverage_pct = bars_broken / lookback * 100

    excess_pct = (current_close - highest_high) / highest_high * 100

    # Strength: how decisively it broke out
    if coverage_pct >= 80:
        strength = min(1.0, 0.6 + excess_pct / 5.0)
    elif coverage_pct >= 50:
        strength = min(0.8, 0.4 + excess_pct / 5.0)
    else:
        strength = min(0.6, excess_pct / 5.0)

    detail = (
        f"Breakout confirmed: closing price {current_close:.2f} "
        f"breaks above {lookback}-day highest high {highest_high:.2f}, "
        f"exceeding {bars_broken}/{lookback} ({coverage_pct:.0f}%) recent highs"
    )

    return SignalClue(clue_type="breakout", strength=round(max(0.1, strength), 4), detail=detail)


# ═══════════════════════════════════════════════════════════════════════
# Condition 2: Trend Change (趋势改变)
# ═══════════════════════════════════════════════════════════════════════

def detect_trend_change(
    df: pd.DataFrame,
    trend_lookback: int | None = None,
    recent_lookback: int | None = None,
) -> SignalClue | None:
    """
    Condition 2 — Trend Change (趋势改变):
    Prior price action was in a downtrend or consolidation, and now
    price has reversed upward, forming higher lows and breaking above
    a recent swing high.

    Detection:
      1. Previous phase: lower highs / lower lows (downtrend)
         OR sideways / narrowing (consolidation)
      2. Recent swing low formed and price bounced
      3. Current close breaks above a swing high formed after the low
    """
    if trend_lookback is None:
        trend_lookback = settings.TREND_CHANGE_LOOKBACK
    if recent_lookback is None:
        recent_lookback = settings.TREND_CHANGE_RECENT

    if len(df) < trend_lookback + 5:
        return None

    full = df.iloc[-trend_lookback:]
    current_close = float(df["close"].iloc[-1])
    half = len(full) // 2

    first_half = full.iloc[:half]
    second_half = full.iloc[half:]

    first_high_mean = float(first_half["high"].mean())
    first_low_mean = float(first_half["low"].mean())
    second_high_mean = float(second_half["high"].mean())
    second_low_mean = float(second_half["low"].mean())

    # Detect prior phase type
    downtrend = (first_high_mean > second_high_mean * 1.02 and
                 first_low_mean > second_low_mean * 1.02)
    consolidation = (abs(first_high_mean - second_high_mean) / max(first_high_mean, 0.01) < 0.03 and
                     abs(first_low_mean - second_low_mean) / max(first_low_mean, 0.01) < 0.03)

    if not (downtrend or consolidation):
        return None

    # Find swing low in recent window
    recent = df.iloc[-recent_lookback:]
    swing_low_val = float(recent["low"].min())
    swing_low_loc = recent["low"].idxmin()

    # Data after swing low
    after_low = df.loc[swing_low_loc:]
    if len(after_low) < 2:
        return None

    # Highest high between swing low and today (exclusive of today)
    after_except_today = after_low.iloc[:-1]
    if after_except_today.empty:
        return None
    swing_high_after_low = float(after_except_today["high"].max())

    # Must break above this swing high
    if current_close <= swing_high_after_low:
        return None

    # Recovery magnitude from swing low
    recovery_pct = (current_close - swing_low_val) / swing_low_val * 100
    if recovery_pct < 2.0:
        return None

    # Strength
    recovery_strength = min(1.0, recovery_pct / 8.0)
    phase_bonus = 1.0 if downtrend else 0.7  # downtrend reversal > consolidation breakout
    strength = min(1.0, recovery_strength * phase_bonus)

    phase_label = "downtrend reversal" if downtrend else "consolidation breakout"
    detail = (
        f"Trend change ({phase_label}): prior phase was "
        f"{'downtrend' if downtrend else 'consolidation'}. "
        f"Price recovered {recovery_pct:.1f}% from swing low {swing_low_val:.2f}, "
        f"now breaking above recent swing high {swing_high_after_low:.2f}"
    )

    return SignalClue(clue_type="trend_change", strength=round(max(0.1, strength), 4), detail=detail)


# ═══════════════════════════════════════════════════════════════════════
# Condition 3: Gap / Wide Range (跳高缺口 或 高低价差大)
# ═══════════════════════════════════════════════════════════════════════

def detect_gap_or_wide_range(
    df: pd.DataFrame,
    lookback: int | None = None,
    gap_min_pct: float | None = None,
    range_multiple: float | None = None,
) -> SignalClue | None:
    """
    Condition 3 — Gap Up or Wide Daily Range (跳高缺口或当日高低价差大):
    The market "wakes up" from a quiet period.

    Two sub-conditions (either or both):
      a) Gap up: today's open > yesterday's close (跳高缺口)
      b) Wide range: today's high-low range significantly exceeds recent average
    """
    if lookback is None:
        lookback = settings.BREAKOUT_LOOKBACK
    if gap_min_pct is None:
        gap_min_pct = settings.GAP_MIN_PCT
    if range_multiple is None:
        range_multiple = settings.RANGE_EXPANSION_MULTIPLE

    if len(df) < lookback + 2:
        return None

    today = df.iloc[-1]
    yesterday = df.iloc[-2]
    recent_excl_today = df.iloc[-(lookback + 1):-1]

    today_open = float(today["open"])
    today_high = float(today["high"])
    today_low = float(today["low"])
    yesterday_close = float(yesterday["close"])

    gap_pct = (today_open - yesterday_close) / yesterday_close * 100
    has_gap_up = gap_pct >= gap_min_pct

    avg_range = float((recent_excl_today["high"] - recent_excl_today["low"]).mean())
    today_range = today_high - today_low
    range_ratio = today_range / avg_range if avg_range > 0 else 1.0
    has_wide_range = range_ratio >= range_multiple

    if not (has_gap_up or has_wide_range):
        return None

    parts = []
    strength = 0.0

    if has_gap_up:
        gap_strength = min(1.0, gap_pct / 3.0)
        strength += gap_strength * 0.6
        parts.append(f"gap up {gap_pct:.2f}% (open {today_open:.2f} > prev close {yesterday_close:.2f})")

    if has_wide_range:
        range_strength = min(1.0, (range_ratio - 1.0) / 2.0)
        strength += range_strength * 0.4
        parts.append(f"wide range {today_range:.2f} ({range_ratio:.1f}x {lookback}-day avg {avg_range:.2f})")

    strength = min(1.0, strength)

    detail = "Market activation: " + " | ".join(parts)

    return SignalClue(clue_type="range_expansion", strength=round(max(0.1, strength), 4), detail=detail)


# ═══════════════════════════════════════════════════════════════════════
# Combined Detection
# ═══════════════════════════════════════════════════════════════════════

def detect_all_three_conditions(df: pd.DataFrame) -> list[SignalClue]:
    """
    Run all three condition detectors.

    Returns list of triggered conditions (0-3 elements).
    """
    clues: list[SignalClue] = []

    c1 = detect_breakout(df)
    if c1:
        clues.append(c1)

    c2 = detect_trend_change(df)
    if c2:
        clues.append(c2)

    c3 = detect_gap_or_wide_range(df)
    if c3:
        clues.append(c3)

    return clues


def check_buy_signal(clues: list[SignalClue]) -> tuple[bool, str]:
    """
    Adam's Theory buy signal rule:
    At least 2 of the 3 conditions must be satisfied simultaneously.

    Returns (is_buy, reason).
    """
    n = len(clues)
    condition_names = {"breakout": "突破", "trend_change": "趋势改变", "range_expansion": "缺口/宽幅"}

    if n >= 3:
        names = ", ".join(condition_names.get(c.clue_type, c.clue_type) for c in clues)
        return True, f"All 3 conditions met: {names} — strong Adam buy signal"

    if n == 2:
        names = ", ".join(condition_names.get(c.clue_type, c.clue_type) for c in clues)
        return True, f"2 of 3 conditions met: {names} — confirmed Adam buy signal"

    if n == 1:
        missing = set(condition_names.values()) - {condition_names.get(clues[0].clue_type, clues[0].clue_type)}
        return False, f"Only 1 condition met ({clues[0].clue_type}), missing: {', '.join(missing)}"

    return False, "No conditions met — no entry signal"


def find_structural_stop(df: pd.DataFrame, lookback: int = 40) -> float:
    """
    Find a structural stop-loss level below the most recent swing low.

    Structural stop = the lowest low in the recent lookback window,
    representing the nearest support level that, if broken, invalidates
    the bullish thesis.

    Returns the stop price (float).
    """
    if len(df) < 10:
        return float(df["low"].min())

    recent = df.iloc[-lookback:]
    swing_low = float(recent["low"].min())
    current_close = float(df["close"].iloc[-1])

    # Ensure stop is at least 1% below current price for breathing room
    if (current_close - swing_low) / current_close < 0.01:
        swing_low = current_close * 0.97

    return round(swing_low, 2)
