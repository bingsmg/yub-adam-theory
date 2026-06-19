"""
Feishu (飞书) notification channel.

Sends daily Adam's Theory recommendations via Feishu bot webhook.
Supports both rich interactive cards and plain text fallback.
"""

from __future__ import annotations

from datetime import datetime

import httpx
from loguru import logger

from config.schema import DailyRecommendation, AdamSignal
from config.settings import settings
from notification.base import Notifier


# ── Formatting helpers ────────────────────────────────────────────────────

def _risk_color(score: float) -> str:
    if score <= 3.0:
        return "green"
    elif score <= 5.0:
        return "yellow"
    elif score <= 7.0:
        return "orange"
    return "red"


def _risk_emoji(score: float) -> str:
    if score <= 3.0:
        return "🟢"
    elif score <= 5.0:
        return "🟡"
    elif score <= 7.0:
        return "🟠"
    return "🔴"


def _board_name(symbol: str) -> str:
    """Determine trading board from symbol prefix."""
    sym = str(symbol).zfill(6)
    if sym.startswith(("300", "301")):
        return "创业板"
    elif sym.startswith(("688", "689")):
        return "科创板"
    elif sym.startswith(("8", "4")):
        return "北交所"
    return "主板"


def _volume_emoji(ratio: float) -> str:
    if ratio >= 3.0:
        return "🔥"
    elif ratio >= 2.0:
        return "📊"
    elif ratio >= 1.2:
        return "📈"
    return "➡️"


def _proj_emoji(direction: str) -> str:
    return {"up": "📈", "down": "📉", "neutral": "➡️"}.get(direction, "❓")


# ── Card builder ──────────────────────────────────────────────────────────

def build_feishu_card(recommendations: list[AdamSignal], market_date: str) -> dict:
    """Build a rich Feishu interactive card from AdamSignal list."""
    n = len(recommendations)
    clue_short = {"breakout": "B", "trend_change": "T", "range_expansion": "R"}

    elements = []

    if not recommendations:
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

    # Summary stats
    avg_risk = sum(s.risk_score for s in recommendations) / n
    conditions_3 = sum(1 for s in recommendations if len(s.clues) >= 3)
    conditions_2 = sum(1 for s in recommendations if len(s.clues) == 2)
    boards: dict[str, int] = {}
    for s in recommendations:
        b = _board_name(s.symbol)
        boards[b] = boards.get(b, 0) + 1
    board_str = " | ".join(f"{k} {v}" for k, v in boards.items() if v > 0)

    avg_stop_pct = sum(
        (s.current_close - s.stop_loss_price) / s.current_close * 100
        for s in recommendations if s.current_close > 0
    ) / n

    stats_md = (
        f"📊 **分析范围**: A股全市场 → {n} 只推荐\n"
        f"🎯 **3条件满分**: {conditions_3} 只 | **2条件**: {conditions_2} 只 | **平均风险**: {avg_risk:.1f}/10\n"
        f"📉 **平均止损距离**: {avg_stop_pct:.1f}% | 🏢 {board_str}"
    )

    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": stats_md},
    })
    elements.append({"tag": "hr"})

    display_count = min(n, 20)
    elements.append({
        "tag": "div",
        "text": {"tag": "lark_md", "content": f"**🏆 Top {display_count} 买入推荐**"},
    })

    for i, s in enumerate(recommendations[:display_count], 1):
        clues = "|".join(c.clue_type for c in s.clues)
        clue_badges = " ".join(
            f"**{clue_short.get(c, '?')}**" if c in clues else f"~~{clue_short.get(c, '?')}~~"
            for c in ["breakout", "trend_change", "range_expansion"]
        )
        stop_pct = (s.current_close - s.stop_loss_price) / s.current_close * 100
        proj_label = {"up": "看涨 ↑", "down": "看跌 ↓", "neutral": "横盘 →"}.get(
            s.projection.projected_direction, s.projection.projected_direction
        )

        line = (
            f"**#{i}** `{s.symbol}` {s.name} | {_board_name(s.symbol)}\n"
            f"━ 收盘 ¥{s.current_close:.2f} | {clue_badges} | {_risk_emoji(s.risk_score)} 风险{s.risk_score:.1f}\n"
            f"━ {proj_label} | 止损 ¥{s.stop_loss_price}（-{stop_pct:.1f}%）| {_volume_emoji(s.volume_ratio)} 量比{s.volume_ratio:.1f}x"
        )
        elements.append({
            "tag": "div",
            "text": {"tag": "lark_md", "content": line},
        })
        elements.append({"tag": "hr"})

    elements.append({
        "tag": "div",
        "text": {
            "tag": "lark_md",
            "content": (
                f"🤖 [Adam's Theory](https://github.com/bingsmg/yub-adam-theory) 自动生成\n"
                f"⏰ {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                f"⚠️ *仅供研究参考，不构成投资建议。股市有风险，投资需谨慎。*"
            ),
        },
    })

    elements.append({
        "tag": "note",
        "elements": [{
            "tag": "plain_text",
            "content": "B=突破 Breakout | T=趋势改变 Trend Change | R=缺口/宽幅 Gap/Wide Range | 🔥高量 📊中量 ➡️平量",
        }],
    })

    return {
        "config": {"wide_screen_mode": True},
        "header": {
            "title": {"tag": "plain_text", "content": f"🔔 亚当理论 · {market_date} 收盘 · Top {display_count}"},
            "template": "blue",
        },
        "elements": elements,
    }


def build_feishu_text(recommendations: list[AdamSignal], market_date: str) -> str:
    """Build a plain text fallback message."""
    n = len(recommendations)
    if n == 0:
        return f"📊 亚当理论 {market_date}\n今日无买入信号。"

    lines = [f"📊 亚当理论 A股买入推荐 · {market_date}", f"共 {n} 只推荐", ""]
    for i, s in enumerate(recommendations[:15], 1):
        clues = "|".join(c.clue_type for c in s.clues)
        proj_arrow = {"up": "↑", "down": "↓", "neutral": "→"}.get(s.projection.projected_direction, "?")
        lines.append(
            f"#{i} {s.symbol} {s.name}\n"
            f"   条件:{clues} | 风险:{_risk_emoji(s.risk_score)}{s.risk_score:.1f} | 投影:{proj_arrow} | 止损:{s.stop_loss_price}"
        )
        lines.append("")

    lines.append(f"🤖 Adam's Theory 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append("⚠️ 仅供研究参考，不构成投资建议。")
    return "\n".join(lines)


# ── Notifier implementation ───────────────────────────────────────────────

class FeishuNotifier(Notifier):
    """Feishu (飞书) bot webhook notification channel.

    Usage:
        notifier = FeishuNotifier(webhook_url="https://...")
        notifier.send(daily_recommendation)
    """

    name = "feishu"

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or settings.FEISHU_WEBHOOK_URL

    def send(self, recommendation: DailyRecommendation) -> bool:
        """Send recommendation as a rich Feishu card."""
        if not self.webhook_url:
            logger.warning("Feishu webhook URL not configured, skipping notification")
            return False

        market_date = recommendation.market_date.strftime('%Y-%m-%d')
        card = build_feishu_card(recommendation.recommendations, market_date)
        payload = {"msg_type": "interactive", "card": card}
        return self._post(payload)

    def send_text(self, recommendation: DailyRecommendation) -> bool:
        """Send recommendation as plain text (fallback)."""
        if not self.webhook_url:
            return False

        market_date = recommendation.market_date.strftime('%Y-%m-%d')
        text = build_feishu_text(recommendation.recommendations, market_date)
        payload = {"msg_type": "text", "content": {"text": text}}
        return self._post(payload)

    def send_test(self) -> bool:
        """Send a test message to verify connectivity."""
        if not self.webhook_url:
            return False

        test_card = {
            "msg_type": "interactive",
            "card": {
                "config": {"wide_screen_mode": True},
                "header": {
                    "title": {"tag": "plain_text", "content": "🧪 Adam's Theory 飞书通知测试"},
                    "template": "green",
                },
                "elements": [{
                    "tag": "div",
                    "text": {
                        "tag": "lark_md",
                        "content": (
                            f"✅ 飞书机器人连接正常！\n\n"
                            f"- 系统: Adam's Theory A-Share Stock Picker\n"
                            f"- 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                            f"- Webhook: {self.webhook_url[:40]}...\n\n"
                            f"每日推荐将在A股收盘后自动推送。"
                        ),
                    },
                }],
            },
        }
        return self._post(test_card)

    def _post(self, payload: dict) -> bool:
        """POST payload to Feishu webhook."""
        try:
            resp = httpx.post(self.webhook_url, json=payload, timeout=15.0)
            resp.raise_for_status()
            result = resp.json()
            if result.get("code") == 0 or result.get("StatusCode") == 0:
                logger.info("Feishu notification sent successfully")
                return True
            logger.error(f"Feishu API error: {result}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Feishu notification: {e}")
            return False
