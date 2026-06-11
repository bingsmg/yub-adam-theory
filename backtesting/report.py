"""Backtest report generation."""

from __future__ import annotations

from datetime import datetime

from config.schema import TradeRecord
from backtesting.metrics import summary_metrics


def generate_backtest_report(
    trades: list[TradeRecord],
    start_date: str = "",
    end_date: str = "",
    initial_capital: float = 100000.0,
) -> str:
    """
    Generate a formatted text report of backtest results.

    Returns a multi-line string suitable for console or file output.
    """
    if not trades:
        return "No trades executed during the backtest period."

    pnl_pcts = [t.pnl_pct for t in trades]

    # Build equity curve
    equity = [initial_capital]
    for p in pnl_pcts:
        equity.append(equity[-1] * (1 + p / 100))
    total_return = (equity[-1] - initial_capital) / initial_capital * 100

    metrics = summary_metrics(pnl_pcts, equity, total_return)

    lines = [
        "=" * 60,
        "  Adam's Theory Backtest Report",
        "=" * 60,
        f"  Period: {start_date} → {end_date}",
        f"  Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "",
        "─" * 40,
        "  Trade Summary",
        "─" * 40,
        f"  Total Trades:       {metrics['total_trades']}",
        f"  Winning Trades:     {metrics['win_count']}",
        f"  Losing Trades:      {metrics['loss_count']}",
        f"  Win Rate:           {metrics['win_rate']:.1%}",
        f"  Avg Win:            {metrics['avg_win_pct']:+.2f}%",
        f"  Avg Loss:           {metrics['avg_loss_pct']:+.2f}%",
        f"  Avg Win/Loss Ratio: {abs(metrics['avg_win_pct']/max(abs(metrics['avg_loss_pct']),0.01)):.2f}",
        "",
        "─" * 40,
        "  Risk & Return",
        "─" * 40,
        f"  Total Return:       {metrics['total_return_pct']:+.2f}%",
        f"  Max Drawdown:       {metrics['max_drawdown_pct']:.2f}%",
        f"  Profit Factor:      {metrics['profit_factor']:.2f}",
        f"  Sharpe Ratio:       {metrics['sharpe_ratio']:.2f}",
        f"  Calmar Ratio:       {metrics['calmar_ratio']:.2f}",
        "",
        "─" * 40,
        "  Minimum Performance Bars",
        "─" * 40,
    ]

    # Check against target metrics
    checks = {
        "Win Rate > 40%": metrics["win_rate"] >= 0.40,
        "Profit Factor > 1.5": metrics["profit_factor"] >= 1.5,
        "Sharpe > 1.0": metrics["sharpe_ratio"] >= 1.0,
        "Max DD < 25%": metrics["max_drawdown_pct"] < 25.0,
    }

    for check, passed in checks.items():
        symbol = "✅" if passed else "❌"
        lines.append(f"  {symbol}  {check}")

    all_pass = all(checks.values())
    lines.append("")
    if all_pass:
        lines.append("  🎉 All targets met! Strategy shows robust edge.")
    else:
        lines.append("  ⚠️  Some targets not met. Consider parameter tuning.")

    lines.append("")
    lines.append("=" * 60)

    return "\n".join(lines)


def print_trade_details(trades: list[TradeRecord], top_n: int = 10) -> str:
    """Print the best and worst trades."""
    if not trades:
        return "No trades to display."

    sorted_trades = sorted(trades, key=lambda t: t.pnl_pct, reverse=True)

    lines = [
        f"\n{'─' * 50}",
        f"  Top {min(top_n, len(trades))} Best Trades:",
        f"{'─' * 50}",
    ]
    for t in sorted_trades[:top_n]:
        lines.append(
            f"  {t.symbol:8s} | Entry: {t.entry_date} ¥{t.entry_price:.2f} | "
            f"Exit: {t.exit_date} ¥{t.exit_price:.2f} ({t.exit_reason}) | "
            f"P&L: {t.pnl_pct:+.2f}% | Held: {t.holding_days}d"
        )

    lines.append(f"\n{'─' * 50}")
    lines.append(f"  Top {min(top_n, len(trades))} Worst Trades:")
    lines.append(f"{'─' * 50}")
    for t in sorted_trades[-top_n:]:
        lines.append(
            f"  {t.symbol:8s} | Entry: {t.entry_date} ¥{t.entry_price:.2f} | "
            f"Exit: {t.exit_date} ¥{t.exit_price:.2f} ({t.exit_reason}) | "
            f"P&L: {t.pnl_pct:+.2f}% | Held: {t.holding_days}d"
        )

    return "\n".join(lines)
