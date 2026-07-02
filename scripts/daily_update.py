#!/usr/bin/env python3
"""
Daily incremental update + Adam's Theory recommendation generation.

Usage:
    python scripts/daily_update.py                      # Full daily run
    python scripts/daily_update.py --limit 100          # Analyze top 100 active stocks
    python scripts/daily_update.py --no-update          # Skip fetch, analysis only
    python scripts/daily_update.py --output html        # HTML report
    python scripts/daily_update.py --notify feishu      # Send Feishu notification after analysis
    python scripts/daily_update.py --notify wecom       # Send WeChat Work notification
    python scripts/daily_update.py --notify both        # Send to both channels
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


def _send_notifications(result, channels: set[str]) -> None:
    """Send recommendations via configured notification channels.

    Args:
        result: DailyRecommendation from the pipeline.
        channels: Set of channel names, e.g. {'feishu'}, {'wecom'}, {'feishu', 'wecom'}.
    """
    for channel in sorted(channels):
        try:
            if channel == "feishu":
                from notification import FeishuNotifier
                notifier = FeishuNotifier()
                ok = notifier.send(result)
                status = "✅" if ok else "❌"
                print(f"[NOTIFY] Feishu: {status}")
            elif channel == "wecom":
                from notification import WecomNotifier
                notifier = WecomNotifier()
                ok = notifier.send(result)
                status = "✅" if ok else "❌"
                print(f"[NOTIFY] WeChat Work: {status}")
            else:
                logger.warning(f"Unknown notification channel: {channel}")
        except Exception as e:
            logger.error(f"Notification channel '{channel}' failed: {e}")
            print(f"[NOTIFY] {channel}: ❌ ({e})")


def main():
    parser = argparse.ArgumentParser(description="Daily update + recommendations")
    parser.add_argument("--limit", type=int, default=None, help="Max active stocks to analyze")
    parser.add_argument("--no-update", action="store_true", help="Skip data fetch, use cached")
    parser.add_argument("--output", choices=["console","html","both"], default="both")
    parser.add_argument("--notify", choices=["feishu", "wecom", "both"], default=None,
                        help="Send notification after analysis (feishu/wecom/both)")
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

    # Notification (after report generation)
    if args.notify:
        channels = {"feishu", "wecom"} if args.notify == "both" else {args.notify}
        _send_notifications(result, channels)

    n = len(result.recommendations)
    if n > 0:
        print(f"\n[DONE] {n} buy recommendations for {result.market_date.date()}")
    else:
        print(f"\n[DONE] No buy signals for {result.market_date.date()}")


if __name__ == "__main__":
    main()
