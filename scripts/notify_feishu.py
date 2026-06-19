#!/usr/bin/env python3
"""
Send daily Adam's Theory recommendations to Feishu (飞书) via webhook bot.

Usage:
    python scripts/notify_feishu.py                          # Send latest results CSV
    python scripts/notify_feishu.py --csv path/to/file.csv   # Send specific CSV
    python scripts/notify_feishu.py --webhook URL            # Override webhook URL
    python scripts/notify_feishu.py --test                   # Send a test message
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings
from config.schema import AdamSignal
from notification.feishu import FeishuNotifier, build_feishu_card, build_feishu_text


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


def rows_to_signals(rows: list[dict]) -> list[AdamSignal]:
    """Convert CSV rows back to AdamSignal objects (best-effort for display)."""
    # For notification, we work with raw CSV rows directly —
    # the card builder accepts either format via legacy helpers.
    # This wrapper preserves the original CSV-based card building.
    return []  # Kept for future migration; current path uses CSV rows directly


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

    if args.text_only:
        text = build_feishu_text([], market_date)  # Fallback
        if rows:
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
        # Use FeishuNotifier's built-in card from CSV rows (legacy path)
        card = build_feishu_card([], market_date)
        if rows:
            # Build card from CSV rows using legacy builders
            from notification.feishu import _risk_emoji, _board_name, _volume_emoji
            clue_short = {"breakout": "B", "trend_change": "T", "range_expansion": "R"}

            elements = []
            n = len(rows)
            avg_risk = sum(float(r["risk_score"]) for r in rows) / n
            conditions_3 = sum(1 for r in rows if r["clue_count"] == "3")
            conditions_2 = sum(1 for r in rows if r["clue_count"] == "2")
            boards: dict[str, int] = {}
            for r in rows:
                b = _board_name(r["symbol"])
                boards[b] = boards.get(b, 0) + 1
            board_str = " | ".join(f"{k} {v}" for k, v in boards.items() if v > 0)

            avg_stop_pct = 0
            count_stop = 0
            for r in rows:
                try:
                    c = float(r["close"]); s = float(r["stop_loss"])
                    if c > 0:
                        avg_stop_pct += (c - s) / c * 100
                        count_stop += 1
                except (ValueError, ZeroDivisionError):
                    pass
            avg_stop_str = f"{avg_stop_pct/count_stop:.1f}%" if count_stop else "N/A"

            stats_md = (
                f"📊 **分析范围**: A股全市场 → {n} 只推荐\n"
                f"🎯 **3条件满分**: {conditions_3} 只 | **2条件**: {conditions_2} 只 | **平均风险**: {avg_risk:.1f}/10\n"
                f"📉 **平均止损距离**: {avg_stop_str} | 🏢 {board_str}"
            )
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": stats_md}})
            elements.append({"tag": "hr"})

            display_count = min(n, 20)
            elements.append({"tag": "div", "text": {"tag": "lark_md", "content": f"**🏆 Top {display_count} 买入推荐**"}})

            for i, r in enumerate(rows[:display_count], 1):
                sym = r["symbol"]
                name = r["name"]
                close = float(r["close"])
                risk = float(r["risk_score"])
                clues = r.get("clues", "")
                proj = r.get("projected_direction", "neutral")
                stop_loss = r.get("stop_loss", "")
                vol_ratio_str = r.get("volume_ratio", "")
                try:
                    vol_ratio = float(vol_ratio_str)
                except (ValueError, TypeError):
                    vol_ratio = 0

                clue_badges = " ".join(
                    f"**{clue_short.get(c, '?')}**" if c in clues else f"~~{clue_short.get(c, '?')}~~"
                    for c in ["breakout", "trend_change", "range_expansion"]
                )
                stop_pct = (close - float(stop_loss)) / close * 100 if stop_loss else 0
                proj_label = {"up": "看涨 ↑", "down": "看跌 ↓", "neutral": "横盘 →"}.get(proj, proj)

                line = (
                    f"**#{i}** `{sym}` {name} | {_board_name(sym)}\n"
                    f"━ 收盘 ¥{close:.2f} | {clue_badges} | {_risk_emoji(risk)} 风险{risk:.1f}\n"
                    f"━ {proj_label} | 止损 ¥{stop_loss}（-{stop_pct:.1f}%）| {_volume_emoji(vol_ratio)} 量比{vol_ratio:.1f}x"
                )
                elements.append({"tag": "div", "text": {"tag": "lark_md", "content": line}})
                elements.append({"tag": "hr"})

            elements.append({
                "tag": "div",
                "text": {"tag": "lark_md", "content": (
                    f"🤖 [Adam's Theory](https://github.com/bingsmg/yub-adam-theory) 自动生成\n"
                    f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"⚠️ *仅供研究参考，不构成投资建议。股市有风险，投资需谨慎。*"
                )},
            })
            elements.append({
                "tag": "note",
                "elements": [{"tag": "plain_text", "content": "B=突破 Breakout | T=趋势改变 Trend Change | R=缺口/宽幅 Gap/Wide Range | 🔥高量 📊中量 ➡️平量"}],
            })

            card = {
                "config": {"wide_screen_mode": True},
                "header": {"title": {"tag": "plain_text", "content": f"🔔 亚当理论 · {market_date} 收盘 · Top {display_count}"}, "template": "blue"},
                "elements": elements,
            }

        payload = {"msg_type": "interactive", "card": card}
        ok = notifier._post(payload)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
