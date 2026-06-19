"""Tests for multi-source data fetching layer."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import numpy as np
import pandas as pd
import pytest

from data.sources.base import (
    DataSource,
    normalize_columns,
    OUTPUT_COLUMNS,
    CN_COLUMN_MAP,
)
from data.sources.strategy import (
    _resolve_source,
    get_available_sources,
    select_source,
    fetch_with_fallback,
)
from data.sources.parallel import fetch_batch_parallel


# ── Synthetic data helpers ─────────────────────────────────────

def _synthetic_kline(n_bars: int = 60, seed: int = 42) -> pd.DataFrame:
    """Build a realistic OHLCV DataFrame as if returned by a data source."""
    rng = np.random.default_rng(seed)
    n = n_bars
    dates = pd.date_range("2025-01-02", periods=n, freq="B")

    close = 50.0 + np.cumsum(rng.normal(0, 1.0, n))
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    open_ = close - rng.normal(0, 0.2, n)
    volume = rng.integers(100_000, 1_000_000, n)

    df = pd.DataFrame({
        "date": dates,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": volume * close,
    })
    return df


def _chinese_kline(n_bars: int = 60, seed: int = 42) -> pd.DataFrame:
    """Synthetic data with Chinese column names (akshare-style)."""
    rng = np.random.default_rng(seed)
    n = n_bars
    dates = pd.date_range("2025-01-02", periods=n, freq="B")

    close = 50.0 + np.cumsum(rng.normal(0, 1.0, n))
    high = close + np.abs(rng.normal(0, 0.3, n))
    low = close - np.abs(rng.normal(0, 0.3, n))
    open_ = close - rng.normal(0, 0.2, n)
    volume = rng.integers(100_000, 1_000_000, n)

    return pd.DataFrame({
        "日期": dates,
        "开盘": open_,
        "最高": high,
        "最低": low,
        "收盘": close,
        "成交量": volume.astype(float),
        "成交额": (volume * close).astype(float),
    })


# ── normalize_columns ──────────────────────────────────────────

class TestNormalizeColumns:
    def test_english_columns_pass_through(self):
        df = _synthetic_kline(60)
        result = normalize_columns(df, "test")
        for col in OUTPUT_COLUMNS:
            if col in df.columns:
                assert col in result.columns
        assert len(result) == 60

    def test_chinese_columns_mapped(self):
        df = _chinese_kline(60)
        assert "日期" in df.columns
        result = normalize_columns(df, "akshare")
        assert "date" in result.columns
        assert "open" in result.columns
        assert "close" in result.columns
        assert "volume" in result.columns
        assert "amount" in result.columns
        # Numeric conversion happened
        assert result["close"].dtype.kind in ("f", "i")

    def test_removes_rows_without_close(self):
        df = _synthetic_kline(60)
        df.loc[10:15, "close"] = np.nan
        result = normalize_columns(df, "test")
        # Rows with NaN close dropped
        assert len(result) < 60

    def test_handles_empty_dataframe(self):
        df = pd.DataFrame()
        result = normalize_columns(df, "test")
        assert result.empty

    def test_cn_column_map_coverage(self):
        """Verify the canonical Chinese column names are in the map."""
        expected = {"日期", "开盘", "最高", "最低", "收盘", "成交量", "成交额"}
        assert expected.issubset(set(CN_COLUMN_MAP.keys()))


# ── DataSource ABC ─────────────────────────────────────────────

class TestDataSourceABC:
    def test_cannot_instantiate_abstract(self):
        with pytest.raises(TypeError):
            DataSource()  # type: ignore[abstract]

    def test_concrete_subclass_must_implement_all(self):
        class Incomplete(DataSource):
            name = "incomplete"

        with pytest.raises(TypeError):
            Incomplete()

    def test_minimal_concrete_works(self):
        class Minimal(DataSource):
            name = "minimal"

            def is_available(self):
                return True

            def get_stock_list(self):
                return pd.DataFrame({"symbol": ["000001"], "name": ["test"], "code": ["sz.000001"]})

            def fetch_daily_kline(self, symbol, start_date, end_date):
                return _synthetic_kline()

        src = Minimal()
        assert src.name == "minimal"
        assert src.is_available()
        df = src.fetch_daily_kline("000001", "2025-01-01", "2025-06-01")
        assert len(df) >= 30


# ── BaostockDataSource (mocked) ────────────────────────────────

class TestBaostockSource:
    @pytest.fixture
    def mock_baostock(self):
        """Mock baostock module to return synthetic data."""
        mock_bs = MagicMock()
        mock_bs.login = MagicMock()
        mock_bs.logout = MagicMock()

        # Mock query_history_k_data_plus — returns fresh RS each call
        def _make_rs():
            calls = [0]
            rs = MagicMock()
            rs.error_code = "0"

            def _next():
                calls[0] += 1
                return calls[0] <= 60

            rs.next = _next
            rs.get_row_data = MagicMock(return_value=[
                "2025-01-15", "50.0", "50.5", "49.5", "50.2", "500000", "25000000"
            ])
            return rs

        mock_bs.query_history_k_data_plus = MagicMock(side_effect=lambda *a, **kw: _make_rs())

        # query_stock_basic
        stock_calls = [0]
        mock_rs2 = MagicMock()
        mock_rs2.error_code = "0"

        def _next2():
            stock_calls[0] += 1
            return stock_calls[0] <= 100

        mock_rs2.next = _next2
        mock_rs2.get_row_data = MagicMock(return_value=[
            "sh.600519", "贵州茅台", "2001-08-27", "", "1", "1"
        ])
        mock_bs.query_stock_basic = MagicMock(return_value=mock_rs2)

        with patch.dict(sys.modules, {"baostock": mock_bs}):
            yield mock_bs

    def test_is_available(self, mock_baostock):
        from data.sources.baostock_source import BaostockDataSource
        src = BaostockDataSource()
        assert src.is_available()

    def test_get_stock_list(self, mock_baostock):
        from data.sources.baostock_source import BaostockDataSource
        src = BaostockDataSource()
        df = src.get_stock_list()
        assert len(df) == 100
        assert list(df.columns) == ["symbol", "name", "code"]
        assert df.iloc[0]["symbol"] == "600519"

    def test_fetch_daily_kline(self, mock_baostock):
        from data.sources.baostock_source import BaostockDataSource
        src = BaostockDataSource()
        df = src.fetch_daily_kline("600519", "2025-01-01", "2025-01-31")
        assert df is not None
        assert "open" in df.columns
        assert "close" in df.columns

    def test_fetch_batch(self, mock_baostock):
        from data.sources.baostock_source import BaostockDataSource
        src = BaostockDataSource()
        results = src.fetch_batch(
            ["600519", "000001", "300750"],
            "2025-01-01", "2025-01-31",
            delay=0.0,
        )
        assert isinstance(results, dict)
        assert len(results) == 3


# ── AkshareDataSource (mocked) ─────────────────────────────────

class TestAkshareSource:
    @pytest.fixture
    def mock_akshare(self):
        mock_ak = MagicMock()
        mock_ak.stock_zh_a_hist = MagicMock(return_value=_chinese_kline(60))
        mock_spot = pd.DataFrame({
            "代码": ["600519", "000001", "300750"],
            "名称": ["贵州茅台", "平安银行", "宁德时代"],
        })
        mock_ak.stock_zh_a_spot_em = MagicMock(return_value=mock_spot)

        with patch.dict(sys.modules, {"akshare": mock_ak}):
            yield mock_ak

    def test_is_available(self, mock_akshare):
        from data.sources.akshare_source import AkshareDataSource
        src = AkshareDataSource()
        assert src.is_available()

    def test_get_stock_list(self, mock_akshare):
        from data.sources.akshare_source import AkshareDataSource
        src = AkshareDataSource()
        df = src.get_stock_list()
        assert len(df) == 3
        assert list(df.columns) == ["symbol", "name", "code"]
        assert "600519" in df["symbol"].values

    def test_fetch_daily_kline(self, mock_akshare):
        from data.sources.akshare_source import AkshareDataSource
        src = AkshareDataSource()
        df = src.fetch_daily_kline("600519", "20250101", "20250601")
        assert df is not None
        assert "open" in df.columns
        assert "close" in df.columns
        # Chinese columns were mapped
        assert "日期" not in df.columns

    def test_retry_on_failure(self, mock_akshare):
        from data.sources.akshare_source import AkshareDataSource

        # Fail twice, succeed on third try
        call_count = [0]
        def _flaky(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] < 3:
                raise ConnectionError("timeout")
            return _chinese_kline(60)

        mock_akshare.stock_zh_a_hist = _flaky

        src = AkshareDataSource(max_retries=3, retry_delays=(0.01, 0.01, 0.01))
        df = src.fetch_daily_kline("600519", "20250101", "20250601")
        assert df is not None
        assert call_count[0] == 3


# ── Strategy selection ─────────────────────────────────────────

class TestStrategy:
    def test_resolve_unknown_source(self):
        src = _resolve_source("nonexistent")
        assert src is None

    def test_get_available_sources(self):
        # With both mocked, should return both
        sources = get_available_sources(order=["akshare", "baostock"])
        # At least one should be available (depends on what's installed)
        assert len(sources) >= 1

    def test_select_source_priority(self):
        src = select_source(strategy="priority")
        assert src is not None
        assert src.name in ("akshare", "baostock", "efinance", "tencent")

    def test_fetch_with_fallback_returns_first_success(self):
        """When first source succeeds, fallback is not tried."""
        class GoodSource(DataSource):
            name = "good"
            def is_available(self): return True
            def get_stock_list(self): return pd.DataFrame()
            def fetch_daily_kline(self, symbol, start_date, end_date):
                return _synthetic_kline(60)

        class BadSource(DataSource):
            name = "bad"
            def is_available(self): return True
            def get_stock_list(self): return pd.DataFrame()
            def fetch_daily_kline(self, symbol, start_date, end_date):
                return None

        # Good first
        df = fetch_with_fallback("600519", "2025-01-01", "2025-06-01",
                                  sources=[GoodSource(), BadSource()])
        assert df is not None

        # Bad first, then good
        df = fetch_with_fallback("600519", "2025-01-01", "2025-06-01",
                                  sources=[BadSource(), GoodSource()])
        assert df is not None

        # All bad
        df = fetch_with_fallback("600519", "2025-01-01", "2025-06-01",
                                  sources=[BadSource()])
        assert df is None


# ── Parallel fetch ─────────────────────────────────────────────

class TestParallel:
    def _fake_fetch(self, symbol: str, start: str, end: str):
        """Deterministic fetch for testing."""
        df = _synthetic_kline(60)
        df["symbol"] = symbol
        return df

    def test_sequential_mode(self):
        """With max_workers=1, should behave like sequential."""
        symbols = [f"{i:06d}" for i in range(10)]
        results = fetch_batch_parallel(
            self._fake_fetch, symbols,
            "2025-01-01", "2025-06-01",
            max_workers=1, delay_per_worker=0.0, progress_every=5,
        )
        assert len(results) == 10
        for sym in symbols:
            assert sym in results

    def test_parallel_mode(self):
        """With max_workers=4, should still get all results."""
        symbols = [f"{i:06d}" for i in range(20)]
        results = fetch_batch_parallel(
            self._fake_fetch, symbols,
            "2025-01-01", "2025-06-01",
            max_workers=4, delay_per_worker=0.01, progress_every=10,
        )
        assert len(results) == 20

    def test_handles_failures(self):
        """Some symbols fail — should still return successes."""
        def _sometimes_fail(sym, start, end):
            if int(sym) % 3 == 0:
                return None
            return self._fake_fetch(sym, start, end)

        symbols = [f"{i:06d}" for i in range(15)]
        results = fetch_batch_parallel(
            _sometimes_fail, symbols,
            "2025-01-01", "2025-06-01",
            max_workers=2, delay_per_worker=0.0, progress_every=10,
        )
        # 15 symbols, every 3rd fails → 10 should succeed
        assert len(results) == 10
        for i in range(15):
            sym = f"{i:06d}"
            if i % 3 == 0:
                assert sym not in results
            else:
                assert sym in results


# ── get_fetcher factory ────────────────────────────────────────

class TestGetFetcher:
    def test_returns_data_source(self):
        from data.sources import get_fetcher
        fetcher = get_fetcher()
        assert isinstance(fetcher, DataSource)
        assert fetcher.is_available()

    def test_respects_order_override(self):
        from data.sources import get_fetcher
        fetcher = get_fetcher(order=["baostock"])
        assert fetcher.name == "baostock"

    def test_unknown_order_raises(self):
        from data.sources import get_fetcher
        with pytest.raises(RuntimeError):
            get_fetcher(order=["nonexistent"])
