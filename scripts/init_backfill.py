#!/usr/bin/env python3
"""
One-time backfill: download ALL A-share stocks (2 years daily K-line) into
a single consolidated Parquet file via baostock (no rate limits).

Usage:
    python scripts/init_backfill.py                    # Full backfill
    python scripts/init_backfill.py --limit 100        # Test: only 100 stocks
    python scripts/init_backfill.py --start 2024-06-11  # Custom start
    python scripts/init_backfill.py --force            # Redownload all
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings, ensure_dirs
from data.consolidated_store import get_stock_list, build_all_stocks_parquet
from utils.logger import setup_logging
from loguru import logger


def main():
    parser = argparse.ArgumentParser(description="Backfill all A-share data into consolidated Parquet")
    parser.add_argument("--limit", type=int, default=0, help="Limit stocks (0 = all 5000+)")
    default_start = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")
    parser.add_argument("--start", default=default_start,
                        help=f"Start date YYYY-MM-DD (default: {default_start}, 2 years ago)")
    parser.add_argument("--force", action="store_true", help="Redownload even if parquet exists")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG","INFO","WARNING","ERROR"])
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    ensure_dirs()

    end_date = datetime.now().strftime("%Y-%m-%d")

    logger.info("=" * 60)
    logger.info("Adam's Theory — Consolidated Data Backfill")
    logger.info(f"Period: {args.start} → {end_date}")
    logger.info("=" * 60)

    # 1. Get stock list
    logger.info("Fetching full stock list...")
    stock_list = get_stock_list()
    logger.info(f"Total stocks: {len(stock_list)}")

    if args.limit > 0:
        stock_list = stock_list.head(args.limit)
        logger.info(f"Limited to {args.limit} stocks for testing")

    # 2. Download all
    count = build_all_stocks_parquet(
        stock_list=stock_list,
        start_date=args.start,
        end_date=end_date,
        force=args.force,
    )

    logger.info(f"Done! {count} stocks saved to {settings.STOCKS_DIR}")


if __name__ == "__main__":
    main()
