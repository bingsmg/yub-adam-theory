#!/usr/bin/env python3
"""
Adam's Theory A-Share Stock Recommendation System

Usage:
    python main.py                  # Run full daily pipeline
    python main.py --limit 50       # Analyze top 50 stocks only
    python main.py --cache-only     # Use only cached data (no API calls)
    python main.py --output html    # Generate HTML report
    python main.py --output console # Console output only (default)
    python main.py --output both    # Both console and HTML
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime

from config.settings import settings, ensure_dirs
from recommendation.pipeline import RecommendationPipeline
from reporting.console import print_recommendations
from reporting.html_report import generate_html_report
from utils.logger import setup_logging


def main():
    parser = argparse.ArgumentParser(
        description="Adam's Theory A-Share Stock Recommendation System"
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help=f"Max stocks to analyze (default: {settings.MAX_STOCKS_TO_ANALYZE})",
    )
    parser.add_argument(
        "--cache-only", action="store_true",
        help="Use only locally cached data, skip API calls",
    )
    parser.add_argument(
        "--output", choices=["console", "html", "both"], default="both",
        help="Output mode (default: both)",
    )
    parser.add_argument(
        "--log-level", default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level",
    )
    parser.add_argument(
        "--start-date", default=None,
        help="Start date for historical data fetch YYYYMMDD (default: 2 years ago)",
    )
    args = parser.parse_args()

    # Setup
    setup_logging(level=args.log_level)
    ensure_dirs()

    # Default start_date = 2 years ago
    if args.start_date is None:
        from datetime import timedelta as _td
        args.start_date = (datetime.now() - _td(days=730)).strftime("%Y%m%d")

    print("=" * 65)
    print("  Adam's Theory A-Share Stock Recommendation System")
    print("  Based on J. Welles Wilder Jr.'s Adam's Theory of Markets")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Data range: {args.start_date} → today")
    print("=" * 65)
    print()

    # Run pipeline
    pipeline = RecommendationPipeline()

    try:
        result = pipeline.run(
            limit_stocks=args.limit,
            start_date=args.start_date,
            use_cache_only=args.cache_only,
        )
    except RuntimeError as e:
        print(f"\n[ERROR] {e}")
        print("   Please run 'python scripts/init_backfill.py' first to download historical data.")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

    # Output
    if args.output in ("console", "both"):
        print_recommendations(result)

    if args.output in ("html", "both"):
        try:
            html_path = generate_html_report(result)
            print(f"\n[HTML] Report: {html_path}")
        except ImportError:
            print("\n[WARN] jinja2 not installed. Skipping HTML report.")

    # Summary
    n_rec = len(result.recommendations)
    if n_rec > 0:
        print(f"\n[DONE] Pipeline complete. {n_rec} buy recommendations for {result.market_date}.")
    else:
        print(f"\n[DONE] Pipeline complete. No buy signals for {result.market_date}.")


if __name__ == "__main__":
    main()
