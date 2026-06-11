"""Shared pytest fixtures — synthetic price data for testing."""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest


def _make_df(closes, highs=None, lows=None, opens=None, volumes=None, start="2025-01-01"):
    """Build a clean OHLCV DataFrame."""
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="B")
    c = np.asarray(closes, dtype=float)

    if highs is None:
        h = c + np.abs(np.random.normal(0, 0.3, n))
    else:
        h = np.asarray(highs, dtype=float)

    if lows is None:
        l = c - np.abs(np.random.normal(0, 0.3, n))
    else:
        l = np.asarray(lows, dtype=float)

    if opens is None:
        o = c - np.random.normal(0, 0.2, n)
    else:
        o = np.asarray(opens, dtype=float)

    if volumes is None:
        v = np.random.randint(100000, 1000000, n)
    else:
        v = np.asarray(volumes, dtype=float)

    return pd.DataFrame({
        "open": o, "high": h, "low": l, "close": c, "volume": v,
    }, index=dates)


@pytest.fixture
def uptrend_df():
    """100-bar clean uptrend."""
    n = 100
    base = 50.0
    trend = np.linspace(0, 20, n)
    noise = np.random.normal(0, 0.3, n)
    closes = base + trend + noise
    return _make_df(closes)


@pytest.fixture
def downtrend_df():
    """100-bar clean downtrend."""
    n = 100
    base = 70.0
    trend = np.linspace(0, -15, n)
    noise = np.random.normal(0, 0.3, n)
    closes = base + trend + noise
    return _make_df(closes)


@pytest.fixture
def ranging_df():
    """100-bar sideways/ranging market."""
    n = 100
    base = 50.0
    noise = np.random.normal(0, 0.5, n)
    closes = base + noise
    return _make_df(closes)


@pytest.fixture
def breakout_df():
    """
    40 bars of tight consolidation followed by 5 bars sharp breakout.
    The last bar should trigger a breakout clue.
    """
    n = 45
    closes = [50.0] * 40
    # Consolidation with slight noise
    for i in range(40):
        closes[i] = 50.0 + np.random.normal(0, 0.3)
    # Sharp breakout
    closes.append(51.0)   # bar 41
    closes.append(52.0)   # bar 42
    closes.append(53.5)   # bar 43
    closes.append(55.0)   # bar 44
    closes.append(57.0)   # bar 45 — far above consolidation highs

    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    opens = [c - 0.1 for c in closes]
    volumes = [100000] * 40 + [300000] * 5  # Volume spike on breakout

    return _make_df(closes, highs=highs, lows=lows, opens=opens, volumes=volumes)


@pytest.fixture
def trend_change_df():
    """
    60 bars downtrend then 20 bars reversal/uptrend.
    Simulates a trend change signal.
    """
    n = 80
    closes = []
    # 60 bars of downtrend
    for i in range(60):
        closes.append(60.0 - i * 0.3 + np.random.normal(0, 0.2))
    # 20 bars of reversal
    base = closes[-1]
    for i in range(20):
        closes.append(base + i * 0.5 + np.random.normal(0, 0.2))

    highs = [c + abs(np.random.normal(0, 0.3)) for c in closes]
    lows = [c - abs(np.random.normal(0, 0.3)) for c in closes]
    opens = [c - np.random.normal(0, 0.1) for c in closes]

    return _make_df(closes, highs=highs, lows=lows, opens=opens)


@pytest.fixture
def range_expansion_df():
    """60 bars low-vol, then 1 bar with massive range expansion."""
    n = 61
    closes = [50.0] * 60
    for i in range(60):
        closes[i] = 50.0 + np.random.normal(0, 0.2)
    closes.append(52.0)  # Gap up + expansion

    highs = [c + 0.3 for c in closes[:-1]] + [54.0]   # Big range
    lows = [c - 0.3 for c in closes[:-1]] + [51.0]
    opens = [c - 0.1 for c in closes[:-1]] + [51.5]    # Gap from prev close ~50

    return _make_df(closes, highs=highs, lows=lows, opens=opens)
