"""Enhanced HTML report with Plotly charts and modern design."""

from __future__ import annotations

import webbrowser
from datetime import datetime
from pathlib import Path

import plotly.graph_objects as go
import plotly.express as px
from loguru import logger

from config.schema import DailyRecommendation, AdamSignal
from config.settings import settings


def _make_charts(result: DailyRecommendation) -> dict[str, str]:
    """Generate Plotly chart divs. Returns dict of chart_name -> html_div."""
    charts = {}
    recs = result.recommendations
    if not recs:
        return charts

    symbols = [r.symbol for r in recs]
    names = [r.name for r in recs]
    clues = [len(r.clues) for r in recs]
    risk_scores = [r.risk_score for r in recs]
    close_prices = [r.current_close for r in recs]
    stop_losses = [r.stop_loss_price for r in recs]
    stop_pcts = [(r.current_close - r.stop_loss_price) / r.current_close * 100 for r in recs]
    directions = [r.projection.projected_direction for r in recs]
    convergence = [r.projection.convergence_score for r in recs]
    vol_ratios = [r.volume_ratio for r in recs]

    # Color by risk
    def risk_color(s):
        if s <= 3: return '#27ae60'
        elif s <= 5: return '#f39c12'
        elif s <= 7: return '#e67e22'
        return '#e74c3c'

    bar_colors = [risk_color(s) for s in risk_scores]

    # ── Chart 1: Risk Score + Stop Loss % ──
    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        x=symbols, y=risk_scores,
        marker_color=bar_colors,
        text=[f'{s:.1f}' for s in risk_scores],
        textposition='outside',
        name='Risk Score',
        hovertemplate='%{x}<br>Risk: %{y:.1f}/10<extra></extra>'
    ))
    fig1.add_trace(go.Scatter(
        x=symbols, y=stop_pcts,
        mode='markers+lines',
        marker=dict(size=10, color='#e74c3c', symbol='diamond'),
        line=dict(dash='dot', color='#e74c3c'),
        name='Stop Loss %',
        yaxis='y2',
        hovertemplate='%{x}<br>Stop: %{y:.1f}%<extra></extra>'
    ))
    fig1.update_layout(
        title=dict(text='Risk Score & Stop Loss Distance', font=dict(size=16)),
        xaxis=dict(title='Stock', tickangle=-45),
        yaxis=dict(title='Risk Score (1-10)', range=[0, 11], gridcolor='#eee'),
        yaxis2=dict(title='Stop Loss %', overlaying='y', side='right', showgrid=False),
        height=400,
        margin=dict(l=40, r=60, t=50, b=80),
        template='plotly_white',
        legend=dict(x=0.01, y=0.99),
        bargap=0.3,
    )
    charts['risk_chart'] = fig1.to_html(full_html=False, include_plotlyjs=False)

    # ── Chart 2: Quality vs Risk scatter ──
    # Compute quality scores via scorer
    from signals.scorer import compute_quality_score
    quality_scores = [compute_quality_score(r) for r in recs]

    fig2 = go.Figure()
    for i, r in enumerate(recs):
        fig2.add_trace(go.Scatter(
            x=[quality_scores[i]], y=[risk_scores[i]],
            mode='markers+text',
            marker=dict(size=max(12, quality_scores[i]*0.5), color=bar_colors[i]),
            text=[f'#{i+1} {r.symbol}'],
            textposition='top center',
            name=f'{r.symbol} {r.name}',
            hovertemplate=(
                f'<b>{r.name}</b> ({r.symbol})<br>'
                f'Quality: {quality_scores[i]:.0f}/100<br>'
                f'Risk: {risk_scores[i]:.1f}/10<br>'
                f'Clues: {clues[i]}/3<extra></extra>'
            )
        ))
    fig2.update_layout(
        title=dict(text='Quality Score vs Risk (bubble size = quality)', font=dict(size=16)),
        xaxis=dict(title='Quality Score (0-100)', gridcolor='#eee'),
        yaxis=dict(title='Risk Score (1-10)', gridcolor='#eee', autorange='reversed'),
        height=400,
        margin=dict(l=40, r=40, t=50, b=40),
        template='plotly_white',
        showlegend=False,
    )
    # Add quadrant lines
    fig2.add_hline(y=5, line_dash='dash', line_color='#f39c12', opacity=0.5)
    fig2.add_vline(x=50, line_dash='dash', line_color='#3498db', opacity=0.5)
    charts['quality_chart'] = fig2.to_html(full_html=False, include_plotlyjs=False)

    # ── Chart 3: Volume Ratio ──
    fig3 = go.Figure()
    fig3.add_trace(go.Bar(
        x=symbols, y=vol_ratios,
        marker_color=['#27ae60' if v >= 1.5 else '#f39c12' if v >= 0.7 else '#e74c3c' for v in vol_ratios],
        text=[f'{v:.1f}x' for v in vol_ratios],
        textposition='outside',
        hovertemplate='%{x}<br>Volume: %{y:.1f}x avg<extra></extra>'
    ))
    fig3.add_hline(y=1.0, line_dash='dash', line_color='gray', annotation_text='Normal')
    fig3.update_layout(
        title=dict(text='Volume Ratio (vs 20-day avg)', font=dict(size=16)),
        xaxis=dict(tickangle=-45),
        yaxis=dict(title='Volume Ratio', gridcolor='#eee'),
        height=350,
        margin=dict(l=40, r=40, t=50, b=80),
        template='plotly_white',
        bargap=0.3,
    )
    charts['volume_chart'] = fig3.to_html(full_html=False, include_plotlyjs=False)

    # ── Chart 4: Clue composition ──
    clue_types = {'breakout': 0, 'trend_change': 0, 'range_expansion': 0}
    for r in recs:
        for c in r.clues:
            ct = c.clue_type
            if ct in clue_types:
                clue_types[ct] += 1

    fig4 = go.Figure(data=[go.Pie(
        labels=['Breakout (突破)', 'Trend Change (趋势改变)', 'Gap/Wide Range (缺口/宽幅)'],
        values=[clue_types['breakout'], clue_types['trend_change'], clue_types['range_expansion']],
        marker_colors=['#3498db', '#2ecc71', '#e74c3c'],
        hole=0.4,
        textinfo='label+value',
        hovertemplate='%{label}: %{value} signals<extra></extra>'
    )])
    fig4.update_layout(
        title=dict(text='Signal Clue Composition', font=dict(size=16)),
        height=350,
        margin=dict(l=20, r=20, t=50, b=20),
        template='plotly_white',
    )
    charts['clue_pie'] = fig4.to_html(full_html=False, include_plotlyjs=False)

    # ── Chart 5: Direction + Convergence ──
    dir_colors = {'up': '#27ae60', 'down': '#e74c3c', 'neutral': '#95a5a6'}
    fig5 = go.Figure()
    fig5.add_trace(go.Bar(
        x=symbols, y=convergence,
        marker_color=[dir_colors.get(d, '#95a5a6') for d in directions],
        text=[f'{c:.3f} ({d.upper()})' for c, d in zip(convergence, directions)],
        textposition='outside',
        hovertemplate='%{x}<br>Convergence: %{y:.3f}<br>Direction: %{text}<extra></extra>'
    ))
    fig5.update_layout(
        title=dict(text='Center Symmetry Projection: Convergence by Direction', font=dict(size=16)),
        xaxis=dict(tickangle=-45),
        yaxis=dict(title='Convergence Score (higher = more reliable)', range=[0.8, 1.0], gridcolor='#eee'),
        height=350,
        margin=dict(l=40, r=40, t=50, b=80),
        template='plotly_white',
        bargap=0.3,
    )
    charts['direction_chart'] = fig5.to_html(full_html=False, include_plotlyjs=False)

    return charts


_TEMPLATE_PATH = Path(__file__).parent / "templates" / "report.html"

if not _TEMPLATE_PATH.exists():
    raise FileNotFoundError(f"HTML template not found: {_TEMPLATE_PATH}")


def _load_template() -> str:
    """Load the Jinja2 HTML template from file."""
    return _TEMPLATE_PATH.read_text(encoding="utf-8")


def generate_html_report(
    result: DailyRecommendation,
    output_path: Path | None = None,
    open_browser: bool = True,
) -> Path:
    """Generate an enhanced HTML report with Plotly charts.

    Args:
        result: Daily recommendation result.
        output_path: Save path. Default: output/reports/YYYY-MM-DD_report.html
        open_browser: Auto-open in browser after generation.

    Returns:
        Path to the generated HTML file.
    """
    try:
        from jinja2 import Template
    except ImportError:
        logger.error("jinja2 not installed.")
        raise

    if output_path is None:
        reports_dir = Path(settings.REPORTS_DIR)
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_path = reports_dir / f"{result.market_date.strftime('%Y-%m-%d')}_report.html"

    # Generate charts
    charts = _make_charts(result)

    # Render template
    template = Template(_load_template())
    html = template.render(
        market_date=result.market_date.strftime('%Y-%m-%d'),
        generated_at=result.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        market_regime_desc=result.market_regime_desc,
        total_stocks_analyzed=result.total_stocks_analyzed,
        total_signals_found=result.total_signals_found,
        recommendations=result.recommendations,
        charts=charts,
    )

    output_path.write_text(html, encoding="utf-8")
    logger.info("HTML report saved: {}", output_path)

    # Auto-open in browser
    if open_browser:
        try:
            webbrowser.open(str(output_path.resolve()))
            logger.info("Opened report in browser")
        except Exception as e:
            logger.warning("Could not open browser: {}", e)

    return output_path
