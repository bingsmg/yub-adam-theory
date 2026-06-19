#!/usr/bin/env python3
"""
Daily incremental update + Adam's Theory recommendation generation.

Usage:
    python scripts/daily_update.py                 # Full daily run
    python scripts/daily_update.py --limit 100     # Analyze top 100 active stocks
    python scripts/daily_update.py --no-update     # Skip fetch, analysis only
    python scripts/daily_update.py --output html   # HTML report
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings, ensure_dirs
from pipeline.daily_pipeline import DailyPipeline
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

    # Verify data exists
    stocks_dir = settings.STOCKS_DIR
    data_exists = (
        stocks_dir.exists() and list(stocks_dir.glob('*.parquet'))
    )
    if not data_exists:
        print(f"[ERROR] No data found at {stocks_dir}/.")
        print("  Run 'python scripts/init_backfill.py' first.")
        sys.exit(1)

    # Run pipeline
    pipeline = DailyPipeline()
    result = pipeline.run(limit=args.limit, skip_update=args.no_update)

    # Output
    if args.output in ("console", "both"):
        print_recommendations(result)

    if args.output in ("html", "both"):
        try:
            html_path = generate_html_report(result)
            print(f"\n[HTML] {html_path}")
        except ImportError:
            pass

    n = len(result.recommendations)
    if n > 0:
        print(f"\n[DONE] {n} buy recommendations for {result.market_date.date()}")
    else:
        print(f"\n[DONE] No buy signals for {result.market_date.date()}")


if __name__ == "__main__":
    main()
