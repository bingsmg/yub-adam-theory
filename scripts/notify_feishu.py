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
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import settings


def _risk_color(score: float) -> str:
    """Feishu card color mapping for risk levels."""
    if score <= 3.0:
        return "green"
    elif score <= 5.0:
        return "yellow"
    elif score <= 7.0:
        return "orange"
    else:
        return "red"


def _risk_emoji(score: float) -> str:
    if score <= 3.0:
        return "🟢"
    elif score <= 5.0:
        return "🟡"
    elif score <= 7.0:
        return "🟠"
    else:
        return "🔴"


def _clue_label(clue_type: str) -> str:
    return {"breakout": "突破", "trend_change": "趋势改变", "range_expansion": "缺口/宽幅"}.get(clue_type, clue_type)


def _proj_emoji(direction: str) -> str:
    return {"up": "📈", "down": "📉", "neutral": "➡️"}.get(direction, "❓")


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


def build_card(rows: list[dict], market_date: str) -> dict:
    """
    Build a Feishu interactive card from recommendation rows.

    Feishu message card v2 format:
    https://open.feishu.cn/document/uAjLw4CM/ukzMukzMukzM/feishu-cards/card-components
    """
    n = len(rows)
    clue_short = {"breakout": "B", "trend_change": "T", "range_expansion": "R"}

    # ── Header ──
    header_block = {
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": f"**🔔 亚当理论 A股买入推荐**\n{market_date} · {n} 只推荐 · 仅参考不构成投资建议",
        },
    }

    elements = [header_block, {"tag": "hr"}]

    if not rows:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": "今日无买入信号 — 无条件≥2的股票触发。"},
        })
        return {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": f"亚当理论 · {market_date}"},
                "template": "blue",
            },
            "elements": elements,
        }

    # ── Summary stats ──
    top3 = rows[:3]
    avg_risk = sum(float(r["risk_score"]) for r in rows) / n
    conditions_3 = sum(1 for r in rows if r["clue_count"] == "3")
    conditions_2 = sum(1 for r in rows if r["clue_count"] == "2")

    stats_md = (
        f"**统计概览**\n"
        f"推荐总数: **{n}** | 平均风险: **{avg_risk:.1f}**/10\n"
        f"3条件触发: **{conditions_3}** 只 | 2条件触发: **{conditions_2}** 只\n"
    )

    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": stats_md},
    })

    elements.append({"tag": "hr"})

    # ── Top picks ──
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": "**🏆 精选推荐 TOP 10**"},
    })

    # Build a compact table
    table_lines = []
    for i, r in enumerate(rows[:10], 1):
        sym = r["symbol"]
        name = r["name"]
        close = r["close"]
        risk = float(r["risk_score"])
        clues = r.get("clues", "")
        proj = r.get("projected_direction", "neutral")
        stop_loss = r.get("stop_loss", "")
        vol_ratio = r.get("volume_ratio", "")

        # Clue badges
        clue_badges = " ".join(
            f"**{clue_short.get(c, '?')}**" if c in clues else f"~~{clue_short.get(c, '?')}~~"
            for c in ["breakout", "trend_change", "range_expansion"]
        )

        line = (
            f"**#{i}** {sym} {name}\n"
            f"收盘 {close} | {clue_badges}\n"
            f"{_risk_emoji(risk)} 风险{risk:.1f} | {_proj_emoji(proj)} {proj} | "
            f"止损{stop_loss} | 量比{vol_ratio}"
        )
        table_lines.append(line)

    for line in table_lines:
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": line},
        })
        elements.append({"tag": "hr"})

    # ── Footer ──
    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": (
                f"🤖 由 [Adam's Theory 系统](https://github.com/bingsmg/yub-adam-theory) 自动生成\n"
                f"⏰ 生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"⚠️ *本内容仅供研究参考，不构成投资建议。股市有风险，投资需谨慎。*"
            ),
        },
    })

    elements.append({
        "tag": "note",
        "elements": [
            {
                "tag": "plain_text",
                "content": "B=突破 Breakout | T=趋势改变 Trend Change | R=缺口/宽幅 Gap/Wide Range",
            }
        ],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🔔 亚当理论 · {market_date} · Top {n}"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_text_message(rows: list[dict], market_date: str) -> str:
    """Build a plain text fallback message for Feishu."""
    n = len(rows)
    if n == 0:
        return f"📊 亚当理论 {market_date}\n今日无买入信号。"

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
    return "\n".join(lines)


def send_feishu(webhook_url: str, payload: dict) -> bool:
    """Send message to Feishu webhook. Returns True on success."""
    try:
        resp = httpx.post(webhook_url, json=payload, timeout=15.0)
        resp.raise_for_status()
        result = resp.json()
        if result.get("code") == 0 or result.get("StatusCode") == 0:
            print(f"[OK] Message sent to Feishu")
            return True
        else:
            print(f"[ERROR] Feishu API returned: {result}")
            return False
    except Exception as e:
        print(f"[ERROR] Failed to send to Feishu: {e}")
        return False


def send_test_message(webhook_url: str) -> bool:
    """Send a test message to verify Feishu webhook connectivity."""
    test_card = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text", "content": "🧪 Adam's Theory 飞书通知测试"},
                "template": "green",
            },
            "elements": [
                {
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"✅ 飞书机器人连接正常！\n\n"
                            f"- 系统: Adam's Theory A-Share Stock Picker\n"
                            f"- 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"- Webhook: {webhook_url[:40]}...\n\n"
                            f"每日推荐将在A股收盘后自动推送。"
                        ),
                    },
                }
            ],
        },
    }
    return send_feishu(webhook_url, test_card)


def main():
    parser = argparse.ArgumentParser(description="Send Adam's Theory recommendations to Feishu")
    parser.add_argument("--csv", type=str, help="Path to specific CSV file")
    parser.add_argument("--webhook", type=str, help="Feishu webhook URL (overrides env var)")
    parser.add_argument("--test", action="store_true", help="Send a test message")
    parser.add_argument("--text-only", action="store_true", help="Send as plain text instead of card")
    args = parser.parse_args()

    # Get webhook URL
    webhook_url = args.webhook or getattr(settings, "FEISHU_WEBHOOK_URL", "")
    if not webhook_url:
        print("[ERROR] FEISHU_WEBHOOK_URL not configured.")
        print("  Set FEISHU_WEBHOOK_URL in .env or pass --webhook")
        print("  Get a webhook URL: Feishu → Group → Settings → Bots → Add Bot → Custom Bot")
        sys.exit(1)

    if args.test:
        ok = send_test_message(webhook_url)
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
        if args.text_only:
            msg = build_text_message(rows, market_date)
            payload = {"msg_type": "text", "content": {"text": msg}}
        else:
            card = build_card(rows, market_date)
            payload = {"msg_type": "interactive", "card": card}
    else:
        # Use card message for rich formatting
        card = build_card(rows, market_date)
        payload = {"msg_type": "interactive", "card": card}

    ok = send_feishu(webhook_url, payload)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
