"""Shared pytest fixtures — synthetic price data for testing.

All fixtures use fixed random seeds for deterministic, reproducible tests.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

# Fixed random seed for deterministic test data across all runs
_RNG = np.random.RandomState(42)


def _make_df(closes, highs=None, lows=None, opens=None, volumes=None, start="2025-01-01"):
    """Build a clean OHLCV DataFrame with deterministic noise."""
    n = len(closes)
    dates = pd.date_range(start, periods=n, freq="B")
    c = np.asarray(closes, dtype=float)

    if highs is None:
        h = c + np.abs(_RNG.normal(0, 0.3, n))
    else:
        h = np.asarray(highs, dtype=float)

    if lows is None:
        l = c - np.abs(_RNG.normal(0, 0.3, n))
    else:
        l = np.asarray(lows, dtype=float)

    if opens is None:
        o = c - _RNG.normal(0, 0.2, n)
    else:
        o = np.asarray(opens, dtype=float)

    if volumes is None:
        v = _RNG.randint(100000, 1000000, n)
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
    noise = _RNG.normal(0, 0.3, n)
    closes = base + trend + noise
    return _make_df(closes)


@pytest.fixture
def downtrend_df():
    """100-bar clean downtrend."""
    n = 100
    base = 70.0
    trend = np.linspace(0, -15, n)
    noise = _RNG.normal(0, 0.3, n)
    closes = base + trend + noise
    return _make_df(closes)


@pytest.fixture
def ranging_df():
    """100-bar sideways/ranging market."""
    n = 100
    base = 50.0
    noise = _RNG.normal(0, 0.5, n)
    closes = base + noise
    return _make_df(closes)


@pytest.fixture
def breakout_df():
    """
    60 bars of tight consolidation followed by 5 bars sharp breakout.
    The last bar always triggers a breakout clue (deterministic, 65 bars total).
    """
    n = 65
    closes = [50.0] * 60
    # Consolidation with slight deterministic noise
    for i in range(60):
        closes[i] = 50.0 + _RNG.normal(0, 0.3)
    # Sharp breakout
    closes.append(51.0)   # bar 61
    closes.append(52.0)   # bar 62
    closes.append(53.5)   # bar 63
    closes.append(55.0)   # bar 64
    closes.append(57.0)   # bar 65 — far above consolidation highs

    highs = [c + 0.5 for c in closes]
    lows = [c - 0.5 for c in closes]
    opens = [c - 0.1 for c in closes]
    volumes = [100000] * 60 + [300000] * 5  # Volume spike on breakout

    return _make_df(closes, highs=highs, lows=lows, opens=opens, volumes=volumes)


@pytest.fixture
def trend_change_df():
    """
    70 bars clear downtrend then 10 bars sharp reversal.
    Always triggers a trend change signal (deterministic).
    """
    n = 80
    closes = []
    # 70 bars of steep downtrend
    for i in range(70):
        closes.append(60.0 - i * 0.45 + _RNG.normal(0, 0.1))
    # 10 bars of sharp reversal
    base = closes[-1]
    for i in range(10):
        closes.append(base + i * 0.9 + _RNG.normal(0, 0.1))

    highs = [c + abs(_RNG.normal(0, 0.2)) for c in closes]
    lows = [c - abs(_RNG.normal(0, 0.2)) for c in closes]
    opens = [c - _RNG.normal(0, 0.05) for c in closes]

    return _make_df(closes, highs=highs, lows=lows, opens=opens)


@pytest.fixture
def range_expansion_df():
    """60 bars low-vol, then 1 bar with massive range expansion (deterministic)."""
    n = 61
    closes = [50.0] * 60
    for i in range(60):
        closes[i] = 50.0 + _RNG.normal(0, 0.2)
    closes.append(52.0)  # Gap up + expansion

    highs = [c + 0.3 for c in closes[:-1]] + [54.0]   # Big range
    lows = [c - 0.3 for c in closes[:-1]] + [51.0]
    opens = [c - 0.1 for c in closes[:-1]] + [51.5]    # Gap from prev close ~50

    return _make_df(closes, highs=highs, lows=lows, opens=opens)
