"""测试 notification/ — 飞书通知通道"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch
import pytest

from notification.base import Notifier
from notification.feishu import (
    FeishuNotifier,
    _risk_color,
    _risk_emoji,
    _board_name,
    _volume_emoji,
    _proj_emoji,
    build_feishu_card,
    build_feishu_text,
    build_feishu_card_from_rows,
)
from config.schema import (
    AdamSignal,
    AdamProjection,
    SignalClue,
    DailyRecommendation,
)


# ── 测试用辅助函数 ────────────────────────────────────────────────────────

def _make_projection(direction="up", convergence=0.8):
    return AdamProjection(
        projected_prices=[50.0] * 20,
        anchor_price=50.0,
        convergence_score=convergence,
        projected_direction=direction,
    )


def _make_signal(symbol="600519", name="贵州茅台", clue_count=2,
                 risk_score=5.0, close=55.0, stop=50.0, vol_ratio=1.5):
    clue_types = ["breakout", "trend_change", "range_expansion"]
    clues = [
        SignalClue(clue_type=ct, strength=0.8, detail=f"{ct}")
        for ct in clue_types[:clue_count]
    ]
    return AdamSignal(
        symbol=symbol,
        name=name,
        direction="buy",
        signal_date=datetime(2026, 6, 18),
        clues=clues,
        projection=_make_projection(),
        risk_score=risk_score,
        current_close=close,
        stop_loss_price=stop,
        projected_entry_price=close,
        atr=1.5,
        volume_ratio=vol_ratio,
    )


# ── 格式化辅助函数测试 ────────────────────────────────────────────────────

class TestFormattingHelpers:
    """格式化辅助函数测试"""

    def test_risk_color_low(self):
        assert _risk_color(2.0) == "green"

    def test_risk_color_mid(self):
        assert _risk_color(4.0) == "yellow"
        assert _risk_color(6.0) == "orange"

    def test_risk_color_high(self):
        assert _risk_color(8.0) == "red"

    def test_risk_emoji(self):
        assert _risk_emoji(2.0) == "🟢"
        assert _risk_emoji(4.0) == "🟡"
        assert _risk_emoji(6.0) == "🟠"
        assert _risk_emoji(8.0) == "🔴"

    def test_board_name(self):
        assert _board_name("600519") == "主板"
        assert _board_name("300750") == "创业板"
        assert _board_name("688981") == "科创板"
        assert _board_name("830000") == "北交所"

    def test_volume_emoji_high(self):
        assert _volume_emoji(3.0) == "🔥"
        assert _volume_emoji(2.0) == "📊"

    def test_volume_emoji_flat(self):
        assert _volume_emoji(0.5) == "➡️"

    def test_proj_emoji(self):
        assert _proj_emoji("up") == "📈"
        assert _proj_emoji("down") == "📉"
        assert _proj_emoji("neutral") == "➡️"


# ── 卡片构建测试 ──────────────────────────────────────────────────────────

class TestBuildFeishuCard:
    """飞书卡片构建测试"""

    def test_empty_card(self):
        card = build_feishu_card([], "2026-06-18")
        assert card["header"]["template"] == "blue"
        assert "elements" in card

    def test_card_with_signals(self):
        signals = [_make_signal("600519", "贵州茅台"), _make_signal("000001", "平安银行")]
        card = build_feishu_card(signals, "2026-06-18")
        assert card["config"]["wide_screen_mode"] is True
        assert len(card["elements"]) > 3  # 统计+分隔+标题+条目

    def test_card_limits_to_20(self):
        signals = [_make_signal(str(600000 + i)) for i in range(30)]
        card = build_feishu_card(signals, "2026-06-18")
        # 应只显示前 20 个
        element_texts = [str(e) for e in card["elements"]]
        combined = " ".join(element_texts)
        assert "**#20**" in combined
        assert "**#21**" not in combined

    def test_card_shows_conditions_count(self):
        signals = [
            _make_signal("600001", clue_count=3),
            _make_signal("600002", clue_count=2),
            _make_signal("600003", clue_count=2),
        ]
        card = build_feishu_card(signals, "2026-06-18")
        combined = " ".join(str(e) for e in card["elements"])
        assert "3条件满分" in combined


class TestBuildFeishuText:
    """飞书文本回退测试"""

    def test_empty_text(self):
        text = build_feishu_text([], "2026-06-18")
        assert "无买入信号" in text

    def test_text_with_signals(self):
        signals = [_make_signal("600519", "贵州茅台")]
        text = build_feishu_text(signals, "2026-06-18")
        assert "600519" in text
        assert "贵州茅台" in text

    def test_text_limits_to_15(self):
        signals = [_make_signal(str(600000 + i)) for i in range(20)]
        text = build_feishu_text(signals, "2026-06-18")
        # #15 应有，#16 不应有
        assert "#15" in text
        assert "#16" not in text


class TestBuildFeishuCardFromRows:
    """CSV 行卡片构建测试"""

    def _make_row(self, symbol="600519", name="茅台", close=55.0, risk=5.0,
                  clues="breakout|trend_change", clue_count="2",
                  proj="up", stop=50.0, vol_ratio="1.5"):
        return {
            "symbol": symbol, "name": name, "close": str(close),
            "risk_score": str(risk), "clues": clues, "clue_count": clue_count,
            "projected_direction": proj, "stop_loss": str(stop),
            "volume_ratio": vol_ratio,
        }

    def test_empty_rows(self):
        card = build_feishu_card_from_rows([], "2026-06-18")
        assert "无买入信号" in str(card["elements"])

    def test_card_with_rows(self):
        rows = [self._make_row("600519", "茅台"), self._make_row("000001", "平安")]
        card = build_feishu_card_from_rows(rows, "2026-06-18")
        assert card["config"]["wide_screen_mode"] is True

    def test_handles_missing_fields(self):
        """缺失可选字段不应崩溃"""
        row = {"symbol": "600519", "name": "茅台", "close": "55.0",
               "risk_score": "5.0", "clue_count": "2",
               "projected_direction": "up", "stop_loss": "50.0"}
        card = build_feishu_card_from_rows([row], "2026-06-18")
        assert card is not None


# ── FeishuNotifier 测试 ────────────────────────────────────────────────────

class TestFeishuNotifier:
    """飞书通知器测试"""

    def test_no_webhook_skips(self):
        notifier = FeishuNotifier(webhook_url="")
        rec = DailyRecommendation(
            generated_at=datetime.now(),
            market_date=datetime(2026, 6, 18),
            total_stocks_analyzed=100,
            total_signals_found=5,
            recommendations=[],
        )
        assert notifier.send(rec) is False

    def test_send_test_no_webhook(self):
        notifier = FeishuNotifier(webhook_url="")
        assert notifier.send_test() is False

    def test_post_success(self):
        """模拟 HTTP 200 返回成功"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0}
        mock_resp.raise_for_status = MagicMock()

        notifier = FeishuNotifier(webhook_url="https://example.com/hook")
        with patch("httpx.post", return_value=mock_resp):
            rec = DailyRecommendation(
                generated_at=datetime.now(),
                market_date=datetime(2026, 6, 18),
                total_stocks_analyzed=100,
                total_signals_found=3,
                recommendations=[_make_signal()],
            )
            assert notifier.send(rec) is True

    def test_post_api_error(self):
        """API 返回错误码应返回 False"""
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 100, "msg": "error"}
        mock_resp.raise_for_status = MagicMock()

        notifier = FeishuNotifier(webhook_url="https://example.com/hook")
        with patch("httpx.post", return_value=mock_resp):
            assert notifier.send_test() is False

    def test_post_network_error(self):
        """网络错误应返回 False，不抛异常"""
        notifier = FeishuNotifier(webhook_url="https://example.com/hook")
        with patch("httpx.post", side_effect=Exception("网络错误")):
            assert notifier.send_test() is False

    def test_post_timeout(self):
        """超时应返回 False"""
        import httpx
        notifier = FeishuNotifier(webhook_url="https://example.com/hook")
        with patch("httpx.post", side_effect=httpx.TimeoutException("超时")):
            assert notifier.send_test() is False

    def test_send_text_fallback(self):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"code": 0}
        mock_resp.raise_for_status = MagicMock()

        notifier = FeishuNotifier(webhook_url="https://example.com/hook")
        with patch("httpx.post", return_value=mock_resp):
            rec = DailyRecommendation(
                generated_at=datetime.now(),
                market_date=datetime(2026, 6, 18),
                total_stocks_analyzed=50,
                total_signals_found=0,
                recommendations=[],
            )
            assert notifier.send_text(rec) is True


class TestNotifierABC:
    """通知器抽象基类测试"""

    def test_cannot_instantiate_abc(self):
        with pytest.raises(TypeError):
            Notifier()

    def test_concrete_subclass_works(self):
        class TestNotifier(Notifier):
            name = "test"

            def send(self, recommendation: DailyRecommendation) -> bool:
                return True

        notifier = TestNotifier()
        assert notifier.name == "test"
        rec = DailyRecommendation(
            generated_at=datetime.now(),
            market_date=datetime(2026, 6, 18),
            total_stocks_analyzed=0,
            total_signals_found=0,
            recommendations=[],
        )
        assert notifier.send(rec) is True
