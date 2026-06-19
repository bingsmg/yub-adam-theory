"""测试 signals/scorer.py — 质量评分与排序"""

from __future__ import annotations

from datetime import datetime
import pytest

from signals.scorer import compute_quality_score, rank_signals
from config.schema import AdamSignal, AdamProjection, SignalClue


def _make_projection(direction="up", convergence=0.8):
    return AdamProjection(
        projected_prices=[50.0] * 20,
        anchor_price=50.0,
        convergence_score=convergence,
        projected_direction=direction,
    )


def _make_signal(clue_count=2, direction="up", convergence=0.8,
                 risk_score=5.0, volume_ratio=1.5):
    """构建测试用 AdamSignal（含所有必填字段）"""
    clue_types = ["breakout", "trend_change", "range_expansion"]
    clues = [
        SignalClue(clue_type=ct, strength=0.8, detail=f"test {ct}")
        for ct in clue_types[:clue_count]
    ]
    proj = _make_projection(direction, convergence)
    return AdamSignal(
        symbol="600519",
        name="贵州茅台",
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


class TestComputeQualityScore:
    """质量评分测试"""

    def test_three_conditions_high_score(self):
        """3 条件应得 70+ 分"""
        s = _make_signal(clue_count=3)
        score = compute_quality_score(s)
        assert score >= 70, f"三条件信号得分应 >= 70，实际: {score}"

    def test_two_conditions_lower_than_three(self):
        """2 条件信号得分应低于同等 3 条件信号"""
        s2 = _make_signal(clue_count=2)
        s3 = _make_signal(clue_count=3)
        assert compute_quality_score(s2) < compute_quality_score(s3)

    def test_up_projection_boosts_score(self):
        """上涨投影应得更高分"""
        s_up = _make_signal(direction="up")
        s_down = _make_signal(direction="down")
        assert compute_quality_score(s_up) > compute_quality_score(s_down)

    def test_convergence_boosts_score(self):
        """高收敛度应得更高分"""
        s_high = _make_signal(convergence=0.9)
        s_low = _make_signal(convergence=0.3)
        assert compute_quality_score(s_high) > compute_quality_score(s_low)

    def test_volume_ratio_boosts_score(self):
        """高成交量比应得更高分"""
        s_high = _make_signal(volume_ratio=3.0)
        s_low = _make_signal(volume_ratio=0.5)
        assert compute_quality_score(s_high) > compute_quality_score(s_low)

    def test_score_bounded_0_100(self):
        """分数应在 0-100 范围内"""
        # 各种极端组合
        cases = [
            _make_signal(clue_count=3, direction="up", convergence=1.0, volume_ratio=5.0),
            _make_signal(clue_count=2, direction="neutral", convergence=0.5, volume_ratio=0.3),
            _make_signal(clue_count=2, direction="down", convergence=0.0, volume_ratio=0.1),
        ]
        for s in cases:
            score = compute_quality_score(s)
            assert 0.0 <= score <= 100.0, f"分数 {score} 超出范围"

    def test_risk_score_not_affecting_quality(self):
        """风险评分不应影响质量评分（质量评分是独立维度）"""
        s_low_risk = _make_signal(risk_score=2.0)
        s_high_risk = _make_signal(risk_score=8.0)
        assert compute_quality_score(s_low_risk) == compute_quality_score(s_high_risk)


class TestRankSignals:
    """信号排序测试"""

    def test_ranks_by_composite(self):
        """应按 quality²/risk 降序排列"""
        s1 = _make_signal(clue_count=3, risk_score=3.0)  # 高质量低风险
        s2 = _make_signal(clue_count=2, risk_score=6.0)  # 低质量高风险
        ranked = rank_signals([s2, s1])  # 故意乱序输入
        assert ranked[0] == s1
        assert ranked[1] == s2

    def test_empty_list(self):
        assert rank_signals([]) == []

    def test_single_signal(self):
        s = _make_signal()
        assert rank_signals([s]) == [s]

    def test_many_signals_stable(self):
        """大量信号排序不应崩溃"""
        signals = [
            _make_signal(
                clue_count=2 + (i % 2),
                risk_score=2.0 + (i % 7),
                volume_ratio=0.5 + (i % 5) * 0.5,
            )
            for i in range(100)
        ]
        ranked = rank_signals(signals)
        assert len(ranked) == 100
        # 排名不应改变元素
        assert set(id(s) for s in ranked) == set(id(s) for s in signals)
