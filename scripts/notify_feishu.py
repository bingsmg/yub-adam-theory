#!/usr/bin/env python3
"""
Send daily Adam's Theory recommendations to Feishu (飞书) via webhook bot.

Usage:
    python scripts/notify_feishu.py                          # Send latest results CSV
    python scripts/notify_feishu.py --csv path/to/file.csv   # Send specific CSV
    python scripts/notify_feishu.py --webhook URL            # Override webhook URL
    python scripts/notify_feishu.py --test                   # Send a test message
    python scripts/notify_feishu.py --text-only              # Send as plain text instead of card
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from notification.feishu import (
    FeishuNotifier,
    build_feishu_card_from_rows,
    build_feishu_text,
)


def read_latest_csv(results_dir: Path | None = None) -> tuple[list[dict], str]:
    """Read the most recent recommendations CSV. Returns (rows, filename)."""
    if results_dir is None:
        results_dir = settings.RESULTS_DIR

    csv_files = sorted(results_dir.glob("recommendations_*.csv"))
    if not csv_files:
        raise FileNotFoundError(f"No recommendation CSVs found in {results_dir}")

    latest = csv_files[-1]
    rows = []
    with open(latest, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    return rows, latest.name


def main():
    parser = argparse.ArgumentParser(description="Send Adam's Theory recommendations to Feishu")
    parser.add_argument("--csv", type=str, help="Path to specific CSV file")
    parser.add_argument("--webhook", type=str, help="Feishu webhook URL (overrides env var)")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    parser.add_argument("--text-only", action="store_true", help="Send as plain text instead of card")
    args = parser.parse_args()

    webhook_url = args.webhook or getattr(settings, "FEISHU_WEBHOOK_URL", "")
    if not webhook_url:
        print("[ERROR] FEISHU_WEBHOOK_URL not configured.")
        print("  Set FEISHU_WEBHOOK_URL in .env or pass --webhook")
        print("  Get a webhook URL: Feishu → Group → Settings → Bots → Add Bot → Custom Bot")
        sys.exit(1)

    notifier = FeishuNotifier(webhook_url=webhook_url)

    if args.test:
        ok = notifier.send_test()
        sys.exit(0 if ok else 1)

    # Read CSV
    if args.csv:
        csv_path = Path(args.csv)
        rows = []
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)
        market_date = csv_path.stem.replace("recommendations_", "")
    else:
        rows, fname = read_latest_csv()
        market_date = fname.replace("recommendations_", "").replace(".csv", "")

    if not rows:
        # Send empty-result notification
        if args.text_only:
            text = build_feishu_text([], market_date)
            payload = {"msg_type": "text", "content": {"text": text}}
        else:
            card = build_feishu_card_from_rows([], market_date)
            payload = {"msg_type": "interactive", "card": card}
        ok = notifier._post(payload)
        sys.exit(0 if ok else 1)

    if args.text_only:
        # Text-only path: build plain text from rows
        from notification.feishu import _risk_emoji
        n = len(rows)
        lines = [f"📊 亚当理论 A股买入推荐 · {market_date}", f"共 {n} 只推荐", ""]
        for i, r in enumerate(rows[:15], 1):
            sym = r["symbol"]
            name = r["name"]
            risk = float(r["risk_score"])
            clues = r.get("clues", "")
            proj = r.get("projected_direction", "?")
            stop_loss = r.get("stop_loss", "")
            proj_arrow = {"up": "↑", "down": "↓", "neutral": "→"}.get(proj, "?")
            risk_icon = _risk_emoji(risk)
            lines.append(
                f"#{i} {sym} {name}\n"
                f"   条件:{clues} | 风险:{risk_icon}{risk:.1f} | 投影:{proj_arrow} | 止损:{stop_loss}"
            )
            lines.append("")
        lines.append(f"🤖 Adam's Theory 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append("⚠️ 仅供研究参考，不构成投资建议。")
        text = "\n".join(lines)
        payload = {"msg_type": "text", "content": {"text": text}}
        ok = notifier._post(payload)
    else:
        # Rich card path: delegates to shared card builder
        card = build_feishu_card_from_rows(rows, market_date)
        payload = {"msg_type": "interactive", "card": card}
        ok = notifier._post(payload)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
