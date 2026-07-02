"""
企业微信通知通道。

通过企业微信群机器人 webhook 发送每日亚当理论推荐。
支持 markdown 消息格式，兼容企业微信机器人 API。
"""

from __future__ import annotations

from datetime import datetime

import httpx
from loguru import logger

from config.schema import DailyRecommendation
from config.settings import settings
from notification.base import Notifier


# ── 格式化辅助函数 ──────────────────────────────────────────────────────

def _risk_label(score: float) -> str:
    """企业微信不支持彩色 emoji，用文字标签代替。"""
    if score <= 3.0:
        return "低风险"
    elif score <= 5.0:
        return "中风险"
    elif score <= 7.0:
        return "⚠️高风险"
    return "🔴极高风险"


def _board_name(symbol: str) -> str:
    """从股票代码判断所属板块。"""
    sym = str(symbol).zfill(6)
    if sym.startswith(("300", "301")):
        return "创业板"
    elif sym.startswith(("688", "689")):
        return "科创板"
    elif sym.startswith(("8", "4")):
        return "北交所"
    return "主板"


def _volume_label(ratio: float) -> str:
    if ratio >= 3.0:
        return "🔥放量"
    elif ratio >= 2.0:
        return "放量"
    elif ratio >= 1.2:
        return "温和放量"
    return "平量"


# ── Markdown 构建器 ─────────────────────────────────────────────────────

def build_wecom_markdown(rows: list[dict], market_date: str) -> str:
    """根据 CSV 行字典构建企业微信 markdown 消息。

    企业微信 markdown 支持的语法：
    - # ~ ###### 标题
    - **粗体**
    - [链接](url)
    - `行内代码`
    - > 引用
    - <font color="info|comment|warning">文字</font>
    """
    n = len(rows)
    clue_short = {"breakout": "B", "trend_change": "T", "range_expansion": "R"}

    lines = [
        f"# 🔔 亚当理论 · {market_date} 收盘",
        "",
    ]

    if n == 0:
        lines.append("> 今日无买入信号 — 无条件≥2的股票触发。")
        lines.append("")
        lines.append(f"---")
        lines.append(f"🤖 Adam's Theory 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        lines.append(f"<font color=\"comment\">⚠️ 仅供研究参考，不构成投资建议。股市有风险，投资需谨慎。</font>")
        return "\n".join(lines)

    # 统计摘要
    avg_risk = sum(float(r["risk_score"]) for r in rows) / n
    conditions_3 = sum(1 for r in rows if r["clue_count"] == "3")
    conditions_2 = sum(1 for r in rows if r["clue_count"] == "2")
    boards: dict[str, int] = {}
    for r in rows:
        b = _board_name(r["symbol"])
        boards[b] = boards.get(b, 0) + 1
    board_str = " | ".join(f"{k} {v}只" for k, v in boards.items() if v > 0)

    avg_stop_pct = 0
    count_stop = 0
    for r in rows:
        try:
            c = float(r["close"])
            s = float(r["stop_loss"])
            if c > 0:
                avg_stop_pct += (c - s) / c * 100
                count_stop += 1
        except (ValueError, ZeroDivisionError):
            pass
    avg_stop_str = f"{avg_stop_pct / count_stop:.1f}%" if count_stop else "N/A"

    lines.append(f"> 📊 共 **{n}** 只推荐 | 🎯 3条件: **{conditions_3}** | 2条件: **{conditions_2}** | 均风险: **{avg_risk:.1f}/10**")
    lines.append(f"> 📉 均止损距离: **{avg_stop_str}** | 🏢 {board_str}")
    lines.append("")

    # Top 推荐列表
    display_count = min(n, 20)
    lines.append(f"## 🏆 Top {display_count} 买入推荐")
    lines.append("")

    for i, r in enumerate(rows[:display_count], 1):
        sym = r["symbol"]
        name = r["name"]
        close_val = float(r["close"])
        risk = float(r["risk_score"])
        clues = r.get("clues", "")
        proj = r.get("projected_direction", "neutral")
        stop_loss = r.get("stop_loss", "")
        vol_ratio_str = r.get("volume_ratio", "")
        try:
            vol_ratio = float(vol_ratio_str)
        except (ValueError, TypeError):
            vol_ratio = 0

        # 条件标记
        clue_badges = " ".join(
            f"**{clue_short.get(c, '?')}**" if c in clues else f"~~{clue_short.get(c, '?')}~~"
            for c in ["breakout", "trend_change", "range_expansion"]
        )
        stop_pct = (close_val - float(stop_loss)) / close_val * 100 if stop_loss else 0
        proj_label = {"up": "📈看涨", "down": "📉看跌", "neutral": "➡️横盘"}.get(proj, proj)

        lines.append(
            f"**#{i}** `{sym}` {name} | {_board_name(sym)}\n"
            f"> 收盘 ¥{close_val:.2f} | {clue_badges} | {_risk_label(risk)} {risk:.1f}\n"
            f"> {proj_label} | 止损 ¥{stop_loss}（-{stop_pct:.1f}%）| {_volume_label(vol_ratio)} {vol_ratio:.1f}x\n"
        )
        lines.append("")

    lines.append("---")
    lines.append(f"🤖 [Adam's Theory](https://github.com/bingsmg/yub-adam-theory) 自动生成 · {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"<font color=\"comment\">⚠️ 仅供研究参考，不构成投资建议。股市有风险，投资需谨慎。</font>")

    return "\n".join(lines)


# ── 通知器实现 ───────────────────────────────────────────────────────────

class WecomNotifier(Notifier):
    """企业微信群机器人 webhook 通知通道。

    用法:
        notifier = WecomNotifier(webhook_url="https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=xxx")
        notifier.send(daily_recommendation)
    """

    name = "wecom"

    def __init__(self, webhook_url: str | None = None):
        self.webhook_url = webhook_url or settings.WECOM_WEBHOOK_URL

    def send(self, recommendation: DailyRecommendation) -> bool:
        """以 markdown 格式发送推荐到企业微信。"""
        if not self.webhook_url:
            logger.warning("Wecom webhook URL not configured, skipping notification")
            return False

        market_date = recommendation.market_date.strftime('%Y-%m-%d')

        # 构建 rows（与现有 CSV 格式兼容，复用 build_wecom_markdown）
        rows = []
        for s in recommendation.recommendations:
            rows.append({
                "symbol": s.symbol,
                "name": s.name,
                "close": str(s.current_close),
                "risk_score": str(s.risk_score),
                "clues": "|".join(c.clue_type for c in s.clues),
                "clue_count": str(len(s.clues)),
                "projected_direction": s.projection.projected_direction,
                "stop_loss": str(s.stop_loss_price),
                "volume_ratio": str(s.volume_ratio),
            })

        markdown = build_wecom_markdown(rows, market_date)
        payload = {
            "msgtype": "markdown",
            "markdown": {"content": markdown},
        }
        return self._post(payload)

    def send_test(self) -> bool:
        """发送测试消息以验证连接。"""
        if not self.webhook_url:
            return False

        markdown = (
            f"# 🧪 Adam's Theory 企业微信通知测试\n"
            f"> ✅ 企业微信机器人连接正常！\n"
            f"> 系统: Adam's Theory A-Share Stock Picker\n"
            f"> 测试时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"> \n"
            f"> 每日推荐将在A股收盘后自动推送。\n"
        )
        payload = {"msgtype": "markdown", "markdown": {"content": markdown}}
        return self._post(payload)

    def _post(self, payload: dict) -> bool:
        """向企业微信 webhook 发送 POST 请求。"""
        try:
            resp = httpx.post(self.webhook_url, json=payload, timeout=15.0)
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("Wecom notification sent successfully")
                return True
            logger.error(f"Wecom API error: {result}")
            return False
        except Exception as e:
            logger.error(f"Failed to send Wecom notification: {e}")
            return False
