"""HTML report generation using Jinja2 + Plotly."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from loguru import logger

from config.schema import DailyRecommendation, AdamSignal
from config.settings import settings


_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Adam's Theory Recommendations — {{ market_date }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
         max-width: 1200px; margin: 0 auto; padding: 20px; background: #f5f5f5; }
  h1 { color: #1a1a2e; border-bottom: 3px solid #16213e; padding-bottom: 10px; }
  h2 { color: #0f3460; margin-top: 30px; }
  .summary { background: white; padding: 15px; border-radius: 8px; margin: 15px 0;
             box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
  .summary span { margin-right: 20px; }
  table { width: 100%; border-collapse: collapse; background: white;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }
  th { background: #16213e; color: white; padding: 12px 8px; text-align: left; }
  td { padding: 10px 8px; border-bottom: 1px solid #eee; }
  tr:hover { background: #f8f9fa; }
  .risk-low { color: #27ae60; font-weight: bold; }
  .risk-moderate { color: #f39c12; font-weight: bold; }
  .risk-elevated { color: #e67e22; font-weight: bold; }
  .risk-high { color: #e74c3c; font-weight: bold; }
  .card { background: white; padding: 20px; border-radius: 8px; margin: 20px 0;
          box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
  .card h3 { margin-top: 0; color: #16213e; }
  .clue { padding: 8px 12px; margin: 5px 0; background: #e8f4f8;
          border-left: 4px solid #2980b9; border-radius: 4px; }
  .chart { margin: 20px 0; }
  .footer { text-align: center; color: #999; margin-top: 50px; font-size: 0.9em; }
</style>
</head>
<body>
<h1>🔍 Adam's Theory A-Share Recommendations</h1>

<div class="summary">
  <strong>Market Date:</strong> <span>{{ market_date }}</span>
  <strong>Generated:</strong> <span>{{ generated_at }}</span>
  <strong>Market Regime:</strong> <span>{{ market_regime_desc }}</span>
  <strong>CSI 300 ADX:</strong> <span>{{ "%.1f"|format(index_adx or 0) }}</span>
</div>

<div class="summary">
  <span>📊 Stocks Analyzed: <strong>{{ total_stocks_analyzed }}</strong></span>
  <span>🎯 Signals Found: <strong>{{ total_signals_found }}</strong></span>
  <span>✅ Recommended: <strong>{{ recommendations|length }}</strong></span>
</div>

{% if not recommendations %}
<p style="color:#e67e22;">⚠️ No buy signals found for today. Market conditions may not be favorable for Adam's Theory entries.</p>
{% else %}

<h2>📈 Recommendation Summary</h2>
<table>
<thead>
<tr>
  <th>#</th><th>Code</th><th>Name</th><th>Close</th><th>Clues</th>
  <th>ADX</th><th>ER</th><th>Risk</th><th>Stop Loss</th><th>Direction</th>
</tr>
</thead>
<tbody>
{% for rec in recommendations %}
<tr>
  <td>{{ loop.index }}</td>
  <td>{{ rec.symbol }}</td>
  <td>{{ rec.name }}</td>
  <td>¥{{ "%.2f"|format(rec.current_close) }}</td>
  <td>{{ rec.clues|map(attribute='clue_type')|join(', ') }}</td>
  <td>{{ "%.1f"|format(rec.adx) }}</td>
  <td>{{ "%.3f"|format(rec.efficiency_ratio) }}</td>
  <td class="{% if rec.risk_score <= 3 %}risk-low{% elif rec.risk_score <= 5 %}risk-moderate{% elif rec.risk_score <= 7 %}risk-elevated{% else %}risk-high{% endif %}">
    {{ "%.1f"|format(rec.risk_score) }}
  </td>
  <td>¥{{ "%.2f"|format(rec.stop_loss_price) }}</td>
  <td>{{ rec.projection.projected_direction }}</td>
</tr>
{% endfor %}
</tbody>
</table>

<h2>📋 Detailed Analysis</h2>
{% for rec in recommendations %}
<div class="card">
  <h3>#{{ loop.index }} {{ rec.name }} ({{ rec.symbol }}) — ¥{{ "%.2f"|format(rec.current_close) }}</h3>
  <p><strong>Risk:</strong>
    <span class="{% if rec.risk_score <= 3 %}risk-low{% elif rec.risk_score <= 5 %}risk-moderate{% elif rec.risk_score <= 7 %}risk-elevated{% else %}risk-high{% endif %}">
      {{ "%.1f"|format(rec.risk_score) }}/10
    </span>
    | <strong>Stop Loss:</strong> ¥{{ "%.2f"|format(rec.stop_loss_price) }}
    | <strong>ADX:</strong> {{ "%.1f"|format(rec.adx) }}
    | <strong>ER:</strong> {{ "%.3f"|format(rec.efficiency_ratio) }}
    | <strong>Trend:</strong> {{ rec.trend_strength }}
  </p>

  <h4>Entry Signals ({{ rec.clues|length }}):</h4>
  {% for clue in rec.clues %}
  <div class="clue">
    <strong>[{{ "%.2f"|format(clue.strength) }}] {{ clue.clue_type }}</strong><br>
    {{ clue.detail }}
  </div>
  {% endfor %}

  <h4>Center Symmetry Projection:</h4>
  <p>
    <strong>Direction:</strong> {{ rec.projection.projected_direction.upper() }}
    | <strong>Convergence:</strong> {{ "%.3f"|format(rec.projection.convergence_score) }}
    | <strong>Anchor:</strong> ¥{{ "%.2f"|format(rec.projection.anchor_price) }}
    {% if rec.projection.projected_prices %}
    | <strong>1st Target:</strong> ¥{{ "%.2f"|format(rec.projection.projected_prices[0]) }}
    {% endif %}
  </p>

  <pre style="white-space: pre-wrap; background: #f8f9fa; padding: 10px; border-radius: 4px;">{{ rec.reason }}</pre>
</div>
{% endfor %}

{% endif %}

<div class="footer">
  🤖 Generated by Adam's Theory Stock Picker &mdash; {{ generated_at }}<br>
  <em>Disclaimer: This is for reference only. Trading involves substantial risk. Do your own research.</em>
</div>
</body>
</html>
"""


def generate_html_report(result: DailyRecommendation, output_path: Path | None = None) -> Path:
    """
    Generate an HTML report from recommendation results.

    Args:
        result: The daily recommendation with all signals.
        output_path: Where to save. Default: output/reports/YYYY-MM-DD_report.html

    Returns:
        Path to the generated HTML file.
    """
    try:
        from jinja2 import Template
    except ImportError:
        logger.error("jinja2 not installed. Cannot generate HTML report.")
        raise

    if output_path is None:
        reports_dir = Path(settings.REPORTS_DIR)
        reports_dir.mkdir(parents=True, exist_ok=True)
        output_path = reports_dir / f"{result.market_date.isoformat()}_report.html"

    template = Template(_HTML_TEMPLATE)
    html = template.render(
        market_date=result.market_date.isoformat(),
        generated_at=result.generated_at.strftime("%Y-%m-%d %H:%M:%S"),
        index_adx=result.index_adx or 0,
        market_regime_desc=result.market_regime_desc,
        total_stocks_analyzed=result.total_stocks_analyzed,
        total_signals_found=result.total_signals_found,
        recommendations=result.recommendations,
    )

    output_path.write_text(html, encoding="utf-8")
    logger.info("HTML report saved: {}", output_path)
    return output_path
