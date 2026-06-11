"""Rich console output for daily recommendations."""

from __future__ import annotations

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from rich import box

from config.schema import DailyRecommendation


def _risk_style(score: float) -> str:
    if score <= 3.0: return "green"
    elif score <= 5.0: return "yellow"
    elif score <= 7.0: return "orange1"
    else: return "red"


def _clue_short(clue_type: str) -> str:
    return {"breakout": "B", "trend_change": "T", "range_expansion": "R"}.get(clue_type, "?")


def print_recommendations(result: DailyRecommendation) -> None:
    """Print Adam's Theory recommendation report."""
    console = Console()

    # ── Header ──
    header_text = Text()
    header_text.append("Adam's Theory A-Share Buy Recommendations\n", style="bold cyan underline")
    header_text.append(f"Date: {result.market_date}  |  ", style="dim")
    header_text.append(f"Analyzed: {result.total_stocks_analyzed}  |  ", style="dim")
    header_text.append(f"Signals: {result.total_signals_found}  |  ", style="dim")
    header_text.append(f"Recommended: {len(result.recommendations)}", style="dim")

    console.print(Panel(header_text, box=box.ROUNDED))

    if not result.recommendations:
        console.print("[yellow]No buy signals — fewer than 2 conditions met for any stock.[/yellow]")
        return

    # ── Summary Table ──
    table = Table(title="Top Recommendations", box=box.SIMPLE_HEAD, header_style="bold white")
    table.add_column("#", style="dim", width=3)
    table.add_column("Code", width=8)
    table.add_column("Name", width=10)
    table.add_column("Close", justify="right", width=8)
    table.add_column("2/3 Met", width=10)
    table.add_column("Missing", width=8)
    table.add_column("Proj", width=6)
    table.add_column("Risk", justify="right", width=6)
    table.add_column("Stop", justify="right", width=8)
    table.add_column("Stop%", justify="right", width=6)

    for i, rec in enumerate(result.recommendations, 1):
        met_types = {c.clue_type for c in rec.clues}
        all_types = {"breakout", "trend_change", "range_expansion"}
        missing = all_types - met_types

        met_str = "+".join(_clue_short(t) for t in ["breakout", "trend_change", "range_expansion"] if t in met_types)
        missing_str = ",".join(_clue_short(t) for t in ["breakout", "trend_change", "range_expansion"] if t in missing)

        proj_str = rec.projection.projected_direction[:2].upper()
        stop_pct = (rec.current_close - rec.stop_loss_price) / rec.current_close * 100
        risk_color = _risk_style(rec.risk_score)

        table.add_row(
            str(i), rec.symbol, rec.name, f"{rec.current_close:.2f}",
            met_str, missing_str, proj_str,
            f"[{risk_color}]{rec.risk_score:.1f}[/{risk_color}]",
            f"{rec.stop_loss_price:.2f}", f"-{stop_pct:.1f}%",
        )

    console.print(table)
    console.print("[dim]B=Breakout(突破) T=Trend Change(趋势改变) R=Gap/Wide Range(缺口/宽幅)[/dim]")
    console.print()

    # ── Detailed Reasoning ──
    for i, rec in enumerate(result.recommendations, 1):
        console.print(rec.reason)
        console.print()
