"""Tests for pure Adam's Theory algorithms — no ADX gating."""

from __future__ import annotations

import pytest

from indicators.adams_theory import (
    compute_center_symmetry_projection,
    detect_breakout,
    detect_trend_change,
    detect_gap_or_wide_range,
    detect_all_three_conditions,
    check_buy_signal,
    find_structural_stop,
)


class TestCenterSymmetryProjection:
    def test_uptrend_projection_up(self, uptrend_df):
        proj = compute_center_symmetry_projection(uptrend_df, lookback=20)
        assert proj.projected_direction in ("up", "neutral")
        assert 0 <= proj.convergence_score <= 1.0
        assert len(proj.projected_prices) == 20

    def test_downtrend_projection_down(self, downtrend_df):
        proj = compute_center_symmetry_projection(downtrend_df, lookback=20)
        assert proj.projected_direction in ("down", "neutral")

    def test_prices_bounded(self, uptrend_df):
        proj = compute_center_symmetry_projection(uptrend_df, lookback=20)
        anchor = proj.anchor_price
        for p in proj.projected_prices:
            assert abs(p - anchor) / anchor < 0.5


class TestBreakout:
    def test_breakout_detected(self, breakout_df):
        """Deterministic fixture: always triggers breakout."""
        clue = detect_breakout(breakout_df)
        assert clue is not None, "Breakout should be detected on this fixture"
        assert clue.clue_type == "breakout"
        assert clue.strength > 0

    def test_no_breakout_ranging(self, ranging_df):
        """Ranging data rarely triggers a breakout. Verify structure if it does."""
        clue = detect_breakout(ranging_df)
        if clue is not None:
            assert clue.clue_type == "breakout"
            assert 0 < clue.strength <= 1.0


class TestTrendChange:
    def test_detected(self, trend_change_df):
        """Deterministic fixture: always triggers trend change."""
        clue = detect_trend_change(trend_change_df)
        assert clue is not None, "Trend change should be detected on this fixture"
        assert clue.clue_type == "trend_change"
        assert 0 < clue.strength <= 1.0


class TestGapWideRange:
    def test_detected(self, range_expansion_df):
        """Deterministic fixture: always triggers range expansion."""
        clue = detect_gap_or_wide_range(range_expansion_df)
        assert clue is not None, "Range expansion should be detected on this fixture"
        assert clue.clue_type == "range_expansion"
        assert 0 < clue.strength <= 1.0

    def test_not_triggered_normal(self, ranging_df):
        """Random data occasionally triggers — should never crash, type correct if it does."""
        clue = detect_gap_or_wide_range(ranging_df)
        if clue is not None:
            assert clue.clue_type == "range_expansion"
            assert 0 < clue.strength <= 1.0


class TestCombined:
    def test_detect_all_returns_list(self, uptrend_df):
        clues = detect_all_three_conditions(uptrend_df)
        assert isinstance(clues, list)

    def test_need_two_of_three(self):
        from config.schema import SignalClue
        c1 = SignalClue(clue_type="breakout", strength=0.8, detail="test1")
        c2 = SignalClue(clue_type="trend_change", strength=0.6, detail="test2")
        is_buy, reason = check_buy_signal([c1, c2])
        assert is_buy

    def test_one_not_enough(self):
        from config.schema import SignalClue
        c1 = SignalClue(clue_type="breakout", strength=0.9, detail="test")
        is_buy, reason = check_buy_signal([c1])
        assert not is_buy

    def test_three_is_strong(self):
        from config.schema import SignalClue
        c1 = SignalClue(clue_type="breakout", strength=0.8, detail="t1")
        c2 = SignalClue(clue_type="trend_change", strength=0.7, detail="t2")
        c3 = SignalClue(clue_type="range_expansion", strength=0.6, detail="t3")
        is_buy, reason = check_buy_signal([c1, c2, c3])
        assert is_buy
        assert "All 3" in reason or "strong" in reason

    def test_zero_is_no(self):
        is_buy, reason = check_buy_signal([])
        assert not is_buy


class TestStructuralStop:
    def test_stop_below_current(self, uptrend_df):
        stop = find_structural_stop(uptrend_df)
        current = float(uptrend_df["close"].iloc[-1])
        assert stop < current

    def test_stop_positive(self, uptrend_df):
        stop = find_structural_stop(uptrend_df)
        assert stop > 0
