"""测试 recommendation/ranking.py — 排名与一问规则"""

from __future__ import annotations

from datetime import datetime
import pytest

from recommendation.ranking import select_top_recommendations, apply_one_question_rule
from config.schema import AdamSignal, AdamProjection, SignalClue


def _make_signal(symbol="600519", clue_count=2, risk_score=5.0,
                 direction="up", convergence=0.8, volume_ratio=1.5):
    """构建测试用 AdamSignal（含所有必填字段）"""
    clue_types = ["breakout", "trend_change", "range_expansion"]
    clues = [
        SignalClue(clue_type=ct, strength=0.8, detail=f"test {ct}")
        for ct in clue_types[:clue_count]
    ]
    proj = AdamProjection(
        projected_prices=[50.0] * 20,
        anchor_price=50.0,
        convergence_score=convergence,
        projected_direction=direction,
    )
    return AdamSignal(
        symbol=symbol,
        name=f"股票{symbol}",
        direction="buy",
        signal_date=datetime(2026, 6, 18),
        clues=clues,
        projection=proj,
        risk_score=risk_score,
        current_close=55.0,
        stop_loss_price=50.0,
        projected_entry_price=55.0,
        atr=1.5,
        volume_ratio=volume_ratio,
    )


class TestApplyOneQuestionRule:
    """一问规则测试"""

    def test_keep_all_when_few(self):
        """<=5 个信号全部保留"""
        signals = [_make_signal(str(600000 + i)) for i in range(5)]
        kept = apply_one_question_rule(signals)
        assert len(kept) == 5

    def test_keep_fraction_mid(self):
        """6-15 个信号保留 80%，不少于 5 个"""
        signals = [_make_signal(str(600000 + i)) for i in range(10)]
        kept = apply_one_question_rule(signals)
        assert len(kept) == 8  # 10 * 0.8 = 8

    def test_keep_fraction_high(self):
        """>15 个信号保留 70%，不少于 10 个"""
        signals = [_make_signal(str(600000 + i)) for i in range(20)]
        kept = apply_one_question_rule(signals)
        assert len(kept) == 14  # 20 * 0.7 = 14

    def test_min_keep_enforced_mid(self):
        """少量信号场景下最低保留数有效"""
        signals = [_make_signal(str(600000 + i)) for i in range(7)]
        kept = apply_one_question_rule(signals)
        assert len(kept) == 5  # 7 * 0.8 = 5.6 → max(5, 5) = 5

    def test_min_keep_enforced_high(self):
        """大量信号场景下最低保留数有效"""
        signals = [_make_signal(str(600000 + i)) for i in range(16)]
        kept = apply_one_question_rule(signals)
        assert len(kept) == 11  # 16 * 0.7 = 11.2 → max(10, 11) = 11

    def test_keeps_first_n(self):
        """一问规则保留前 N 个（已排序信号）"""
        s_good = _make_signal("600001", clue_count=3, risk_score=2.0)
        s_bad = _make_signal("600002", clue_count=2, risk_score=8.0)
        signals = [s_good, s_bad]
        kept = apply_one_question_rule(signals)
        assert kept == [s_good, s_bad]  # <=5，全部保留


class TestSelectTopRecommendations:
    """最终推荐选择测试"""

    def test_empty_returns_empty(self):
        assert select_top_recommendations([]) == []

    def test_ranks_by_composite(self):
        """应按 quality²/risk 排序，质量高+风险低的排前面"""
        s_good = _make_signal("600001", clue_count=3, risk_score=2.0)
        s_mid = _make_signal("600002", clue_count=2, risk_score=5.0)
        s_bad = _make_signal("600003", clue_count=2, risk_score=8.0)
        result = select_top_recommendations([s_bad, s_good, s_mid], top_n=10)
        assert result[0] == s_good
        assert result[1] == s_mid
        assert result[2] == s_bad

    def test_top_n_truncation(self):
        """应截断到 top_n"""
        signals = [_make_signal(str(600000 + i)) for i in range(30)]
        result = select_top_recommendations(signals, top_n=10)
        assert len(result) == 10

    def test_single_signal(self):
        s = _make_signal()
        result = select_top_recommendations([s], top_n=20)
        assert result == [s]

    def test_top_n_larger_than_signals(self):
        """top_n 大于实际信号数时返回所有"""
        signals = [_make_signal(str(600000 + i)) for i in range(3)]
        result = select_top_recommendations(signals, top_n=20)
        assert len(result) == 3
