"""Backtest performance metrics calculation."""

from __future__ import annotations

import numpy as np


def sharpe_ratio(returns: list[float], risk_free_rate: float = 0.03) -> float:
    """
    Annualized Sharpe ratio.

    Args:
        returns: List of periodic returns (e.g., trade P&L %).
        risk_free_rate: Annual risk-free rate (default 3%).
    """
    if not returns or len(returns) < 2:
        return 0.0
    arr = np.array(returns, dtype=float)
    excess = arr - risk_free_rate / 252  # Daily risk-free
    mean_excess = float(np.mean(excess))
    std_excess = float(np.std(excess, ddof=1))
    if std_excess == 0:
        return 0.0 if mean_excess == 0 else float("inf")
    # Annualize
    return round(mean_excess / std_excess * np.sqrt(252), 2)


def max_drawdown(equity_curve: list[float]) -> float:
    """
    Maximum drawdown from peak.

    Args:
        equity_curve: Running equity values.

    Returns:
        Max drawdown as a fraction (0.0–1.0).
    """
    if not equity_curve:
        return 0.0
    arr = np.array(equity_curve, dtype=float)
    peak = np.maximum.accumulate(arr)
    drawdowns = (peak - arr) / peak
    return round(float(np.max(drawdowns)), 4)


def win_rate(pnl_pcts: list[float]) -> float:
    """Fraction of trades with positive P&L."""
    if not pnl_pcts:
        return 0.0
    wins = sum(1 for p in pnl_pcts if p > 0)
    return round(wins / len(pnl_pcts), 4)


def profit_factor(gains: list[float], losses: list[float]) -> float:
    """Gross profit / Gross loss."""
    total_gain = sum(g for g in gains if g > 0)
    total_loss = sum(abs(l) for l in losses if l < 0)
    if total_loss == 0:
        return float("inf") if total_gain > 0 else 0.0
    return round(total_gain / total_loss, 2)


def avg_win(pnl_pcts: list[float]) -> float:
    wins = [p for p in pnl_pcts if p > 0]
    if not wins:
        return 0.0
    return round(float(np.mean(wins)), 4)


def avg_loss(pnl_pcts: list[float]) -> float:
    losses = [p for p in pnl_pcts if p < 0]
    if not losses:
        return 0.0
    return round(float(np.mean(losses)), 4)


def calmar_ratio(total_return_pct: float, max_dd_pct: float) -> float:
    """Annualized return / Max drawdown."""
    if max_dd_pct == 0:
        return 0.0
    return round(total_return_pct / max_dd_pct, 2)


def summary_metrics(
    pnl_pcts: list[float],
    equity_curve: list[float] | None = None,
    total_return_pct: float = 0.0,
) -> dict:
    """Compute all backtest summary metrics."""
    if equity_curve is None:
        equity_curve = _build_equity_curve(pnl_pcts)

    wins = [p for p in pnl_pcts if p > 0]
    losses = [p for p in pnl_pcts if p < 0]

    dd = max_drawdown(equity_curve)

    return {
        "total_trades": len(pnl_pcts),
        "win_rate": win_rate(pnl_pcts),
        "win_count": len(wins),
        "loss_count": len(losses),
        "avg_win_pct": avg_win(pnl_pcts),
        "avg_loss_pct": avg_loss(pnl_pcts),
        "profit_factor": profit_factor(wins, losses),
        "sharpe_ratio": sharpe_ratio(pnl_pcts),
        "max_drawdown_pct": round(dd * 100, 2),
        "total_return_pct": round(total_return_pct, 2),
        "calmar_ratio": calmar_ratio(total_return_pct, round(dd * 100, 2)),
    }


def _build_equity_curve(pnl_pcts: list[float], initial_capital: float = 100000.0) -> list[float]:
    """Build an equity curve from a list of trade P&L percentages."""
    curve = [initial_capital]
    for pnl in pnl_pcts:
        curve.append(curve[-1] * (1 + pnl / 100))
    return curve
