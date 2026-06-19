"""测试 data/filters.py — 业务过滤与板块分类"""

from __future__ import annotations

import os
import tempfile
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from data.filters import get_board, get_stale_stocks, filter_active_stocks
from data.store import _save_stock


class TestGetBoard:
    """板块分类测试"""

    def test_main_board(self):
        assert get_board("600519") == "main"
        assert get_board("000001") == "main"
        assert get_board("002001") == "main"
        assert get_board("603000") == "main"

    def test_chinext_board(self):
        assert get_board("300750") == "chinext"
        assert get_board("301000") == "chinext"

    def test_star_market(self):
        assert get_board("688981") == "star"
        assert get_board("689009") == "star"

    def test_bse_board(self):
        assert get_board("830000") == "bse"
        assert get_board("430000") == "bse"

    def test_short_code_padded(self):
        """短代码应自动补零到 6 位"""
        assert get_board("1") == "main"
        assert get_board("300") == "chinext"


class TestGetStaleStocks:
    """过期股票检测测试"""

    def _make_stock_list(self, symbols):
        return pd.DataFrame({"symbol": symbols, "name": [f"股票{s}" for s in symbols]})

    def _make_ohlcv(self, n_days=50, start="2025-01-01"):
        """构建合成数据"""
        dates = pd.date_range(start, periods=n_days, freq="B")
        rng = np.random.RandomState(42)
        close = 50.0 + np.cumsum(rng.normal(0, 0.5, n_days))
        return pd.DataFrame({
            "date": dates,
            "open": close - 0.2,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": rng.randint(100_000, 1_000_000, n_days),
        })

    def test_stale_detected(self):
        """数据日期早于参考日期应被检测为过期"""
        df = self._make_ohlcv(50, "2025-01-01")
        stock_list = self._make_stock_list(["600519"])
        with tempfile.TemporaryDirectory() as tmpdir:
            _save_stock("600519", df, tmpdir)
            stale = get_stale_stocks(stock_list, tmpdir, "2026-06-18")
            assert "600519" in stale
            assert stale["600519"] is not None

    def test_up_to_date_not_stale(self):
        """数据日期等于参考日期不应过期"""
        df = self._make_ohlcv(50, "2026-06-01")
        stock_list = self._make_stock_list(["600519"])
        with tempfile.TemporaryDirectory() as tmpdir:
            _save_stock("600519", df, tmpdir)
            stale = get_stale_stocks(stock_list, tmpdir, "2026-01-01")
            assert len(stale) == 0

    def test_missing_file_is_none(self):
        """文件不存在时 last_date 应为 None"""
        stock_list = self._make_stock_list(["nonexistent"])
        with tempfile.TemporaryDirectory() as tmpdir:
            stale = get_stale_stocks(stock_list, tmpdir)
            assert stale["nonexistent"] is None


class TestFilterActiveStocks:
    """活跃股筛选测试"""

    def _make_snapshot(self, symbols_prices_volumes):
        """构建模拟的最新快照 DataFrame"""
        rows = []
        rng = np.random.RandomState(42)
        for sym, price, vol in symbols_prices_volumes:
            rows.append({
                "symbol": sym,
                "name": f"股票{sym}",
                "date": pd.Timestamp("2026-06-18"),
                "open": price - 0.5,
                "high": price + 0.5,
                "low": price - 0.5,
                "close": price,
                "volume": vol,
            })
        return pd.DataFrame(rows)

    def test_filters_by_activity(self):
        """应按活跃度（成交量×价格）排序"""
        master = self._make_snapshot([
            ("600001", 50.0, 100_000),   # 低活跃度
            ("600002", 100.0, 1_000_000),  # 高活跃度
            ("600003", 20.0, 500_000),   # 中活跃度
        ])
        with patch("data.filters.load_latest_snapshot", return_value=master):
            result = filter_active_stocks(None, top_n=3)
        assert len(result) == 3
        # 最高活跃度的应排第一: 100 * 1M = 100M
        assert result[0]["symbol"] == "600002"
        assert result[1]["symbol"] == "600003"
        assert result[2]["symbol"] == "600001"

    def test_excludes_st_stocks(self):
        """应排除 ST 股票"""
        master = pd.DataFrame([
            {"symbol": "600001", "name": "正常股票", "date": pd.Timestamp("2026-06-18"),
             "open": 50, "high": 51, "low": 49, "close": 50, "volume": 1_000_000},
            {"symbol": "600002", "name": "*ST退市", "date": pd.Timestamp("2026-06-18"),
             "open": 10, "high": 11, "low": 9, "close": 10, "volume": 2_000_000},
        ])
        with patch("data.filters.load_latest_snapshot", return_value=master):
            result = filter_active_stocks(None, top_n=10)
        symbols = [r["symbol"] for r in result]
        assert "600002" not in symbols

    def test_excludes_penny_stocks(self):
        """应排除低于 MIN_PRICE 的仙股"""
        master = self._make_snapshot([
            ("600001", 50.0, 1_000_000),
            ("600002", 0.5, 10_000_000),  # 仙股
        ])
        with patch("data.filters.load_latest_snapshot", return_value=master):
            result = filter_active_stocks(None, top_n=10)
        symbols = [r["symbol"] for r in result]
        assert "600002" not in symbols

    def test_empty_input(self):
        """空数据应返回空列表"""
        assert filter_active_stocks(pd.DataFrame()) == []

    def test_returns_dict_list(self):
        """返回格式应为 dict 列表，含 symbol/name/close"""
        master = self._make_snapshot([("600519", 1800.0, 5_000_000)])
        with patch("data.filters.load_latest_snapshot", return_value=master):
            result = filter_active_stocks(None, top_n=10)
        assert isinstance(result, list)
        assert all(isinstance(r, dict) for r in result)
        assert all("symbol" in r for r in result)
        assert all("name" in r for r in result)
        assert all("close" in r for r in result)
