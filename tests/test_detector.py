"""Tests for signal detection pipeline."""

from __future__ import annotations

import pandas as pd
import pytest

from signals.detector import detect_signal


class TestDetection:
    def test_insufficient_data(self):
        df = pd.DataFrame({
            "open": [10, 11, 12], "high": [11, 12, 13],
            "low": [9, 10, 11], "close": [10.5, 11.5, 12.5],
            "volume": [100, 200, 300],
        })
        assert detect_signal(df, symbol="000001") is None

    def test_no_crash_on_normal_data(self, ranging_df):
        """Should not crash on any data; random noise may rarely trigger signal."""
        result = detect_signal(ranging_df, symbol="000001", name="test")
        if result is not None:
            assert result.direction == "buy"
            assert len(result.clues) >= 2
            assert 1.0 <= result.risk_score <= 10.0

    def test_signal_structure_when_triggered(self, breakout_df):
        """Breakout fixture always triggers a signal with >=2 conditions."""
        result = detect_signal(breakout_df, symbol="000001", name="test")
        assert result is not None, "Breakout fixture should trigger a buy signal"
        assert result.direction == "buy"
        assert len(result.clues) >= 2  # Must have >=2
        assert result.stop_loss_price < result.current_close
        assert 1.0 <= result.risk_score <= 10.0
