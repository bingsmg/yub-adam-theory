#!/usr/bin/env python3
"""
Run walk-forward backtest on historical data.

Usage:
    python scripts/run_backtest.py
    python scripts/run_backtest.py --start 2023-01-01 --end 2024-06-30
    python scripts/run_backtest.py --symbols 000001,600519,300750
"""

from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings, ensure_dirs
from data.store import ParquetStore
from data.trading_calendar import load_trading_calendar
from backtesting.engine import BacktestEngine
from backtesting.metrics import summary_metrics
from backtesting.report import generate_backtest_report, print_trade_details
from utils.logger import setup_logging
from loguru import logger


def main():
    parser = argparse.ArgumentParser(description="Walk-forward backtest")
    parser.add_argument("--start", default="2023-01-01", help="Backtest start date")
    parser.add_argument("--end", default="2024-12-31", help="Backtest end date")
    parser.add_argument("--symbols", default="", help="Comma-separated stock codes (empty=all)")
    parser.add_argument("--max-concurrent", type=int, default=10, help="Max concurrent positions")
    parser.add_argument("--holding-days", type=int, default=20, help="Max holding days")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG","INFO","WARNING","ERROR"])
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    ensure_dirs()

    store = ParquetStore()

    # Check we have data
    symbols = store.list_symbols()
    if not symbols:
        logger.error("No stock data found. Run scripts/init_backfill.py first.")
        sys.exit(1)

    logger.info("Found {} stocks with cached data", len(symbols))

    # Filter symbols if specified
    if args.symbols:
        requested = [s.strip() for s in args.symbols.split(",")]
        symbols = [s for s in requested if s in symbols]
        if not symbols:
            logger.error("None of the requested symbols have data: {}", args.symbols)
            sys.exit(1)

    # Create engine and run
    engine = BacktestEngine(
        store=store,
        start_date=date.fromisoformat(args.start),
        end_date=date.fromisoformat(args.end),
        max_concurrent=args.max_concurrent,
        holding_days_max=args.holding_days,
    )

    logger.info("Starting backtest: {} → {} ({} stocks)", args.start, args.end, len(symbols))
    trades = engine.run(symbols=symbols)

    # Report
    print(generate_backtest_report(trades, start_date=args.start, end_date=args.end))
    print(print_trade_details(trades, top_n=10))


if __name__ == "__main__":
    main()
