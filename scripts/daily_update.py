#!/usr/bin/env python3
"""
Daily incremental update + Adam's Theory recommendation generation.

1. Load all_stocks.parquet
2. Fetch new trading days since last update
3. Run Adam's Theory detection on active stocks
4. Output recommendations

Usage:
    python scripts/daily_update.py                 # Full daily run
    python scripts/daily_update.py --limit 100     # Analyze top 100 active stocks
    python scripts/daily_update.py --no-update     # Skip fetch, analysis only
    python scripts/daily_update.py --output html   # HTML report
"""

from __future__ import annotations

import argparse
import sys
import csv
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings, ensure_dirs
from config.schema import DailyRecommendation
from data.consolidated_store import (
    get_stock_list_baostock,
    load_all_stocks,
    update_latest_days,
    filter_active_stocks,
)
from signals.detector import detect_signal
from recommendation.explainer import build_explanation
from recommendation.ranking import select_top_recommendations
from reporting.console import print_recommendations
from reporting.html_report import generate_html_report
from utils.logger import setup_logging
from loguru import logger


def main():
    parser = argparse.ArgumentParser(description="Daily update + recommendations")
    parser.add_argument("--limit", type=int, default=None, help="Max active stocks to analyze")
    parser.add_argument("--no-update", action="store_true", help="Skip data fetch, use cached")
    parser.add_argument("--output", choices=["console","html","both"], default="both")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG","INFO","WARNING","ERROR"])
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    ensure_dirs()

    parquet_path = settings.ALL_STOCKS_PATH
    if not parquet_path.exists():
        print(f"[ERROR] {parquet_path} not found.")
        print("  Run 'python scripts/init_backfill.py' first.")
        sys.exit(1)

    # 1. Update data
    if not args.no_update:
        logger.info("Updating data to latest trading day...")
        try:
            stock_list = get_stock_list_baostock()
            stock_list.to_csv(settings.STOCK_LIST_PATH, index=False)
        except Exception:
            stock_list = load_all_stocks(parquet_path)[['symbol','name']].drop_duplicates()

        master = update_latest_days(stock_list)
    else:
        logger.info("Skipping data fetch (--no-update)")
        master = load_all_stocks(parquet_path)

    # 2. Filter active stocks
    candidates = filter_active_stocks(master, top_n=args.limit)
    logger.info(f"Active candidates for analysis: {len(candidates)}")

    # 3. Run Adam's Theory detection
    signals = []

    latest_date = master['date'].max()

    for i, c in enumerate(candidates):
        sym = c['symbol']
        name = c.get('name', '')

        if i > 0 and i % 20 == 0:
            logger.info(f"Detection: {i}/{len(candidates)}")

        # Extract this stock's data
        df_stock = master[master['symbol'] == sym].sort_values('date')
        if len(df_stock) < 60:
            continue

        # Rename amount column if present (detector expects 'amount' not required)
        signal = detect_signal(df_stock, symbol=sym, name=name)
        if signal:
            signals.append(signal)

    logger.info(f"Signals found: {len(signals)}/{len(candidates)}")

    # 4. Rank and select
    recommendations = select_top_recommendations(signals)
    for s in recommendations:
        s.reason = build_explanation(s)

    # 5. Build result
    result = DailyRecommendation(
        generated_at=datetime.now(),
        market_date=latest_date,
        total_stocks_analyzed=len(candidates),
        total_signals_found=len(signals),
        recommendations=recommendations,
        market_regime_desc="",
    )

    # 6. Save CSV
    results_dir = Path(settings.RESULTS_DIR)
    results_dir.mkdir(parents=True, exist_ok=True)
    csv_path = results_dir / f"recommendations_{latest_date.date().isoformat()}.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["rank","symbol","name","close","clues","clue_count",
                          "risk_score","projected_direction","stop_loss","volume_ratio","reason"])
        for i, rec in enumerate(recommendations, 1):
            clue_str = "|".join(c.clue_type for c in rec.clues)
            writer.writerow([i, rec.symbol, rec.name, rec.current_close, clue_str,
                             len(rec.clues), rec.risk_score, rec.projection.projected_direction,
                             rec.stop_loss_price, rec.volume_ratio, rec.reason])

    # 7. Output
    if args.output in ("console","both"):
        print_recommendations(result)

    if args.output in ("html","both"):
        try:
            html_path = generate_html_report(result)
            print(f"\n[HTML] {html_path}")
        except ImportError:
            pass

    n = len(recommendations)
    if n > 0:
        print(f"\n[DONE] {n} buy recommendations for {latest_date.date()}")
    else:
        print(f"\n[DONE] No buy signals for {latest_date.date()}")


if __name__ == "__main__":
    main()
