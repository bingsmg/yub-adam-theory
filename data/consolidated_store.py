"""
Backward-compatibility re-exports from the refactored data layer.

The data layer has been split into three modules:
  - data.store    — pure storage I/O (load, save, path helpers)
  - data.filters  — business filtering & classification
  - data.pipeline — orchestration (backfill, incremental update)

This file re-exports the public API so existing imports continue to work.
New code should import directly from the sub-modules.
"""

from __future__ import annotations

# ── Store (I/O) ───────────────────────────────────────────────────────────
from data.store import (
    _stock_file_path,
    _save_stock,
    _save_results_to_stocks,
    load_stock,
    load_latest_snapshot,
    load_all_stocks,
    get_latest_date,
)

# ── Filters (business logic) ──────────────────────────────────────────────
from data.filters import (
    get_board,
    get_stock_list,
    get_stale_stocks,
    filter_active_stocks,
)

# ── Pipeline (orchestration) ──────────────────────────────────────────────
from data.pipeline import (
    build_all_stocks_parquet,
    update_latest_days,
)

# ── Legacy functions (removed — re-export stubs for compatibility) ────────
# _baostock_code() — use data.sources.baostock_source._baostock_code instead
# get_stock_list_baostock() — use get_stock_list(order=["baostock"]) instead
# _save_results_to_daily() — date-partitioned storage is deprecated
# migrate_to_daily() — one-time migration has been completed

import warnings

def _baostock_code(symbol: str) -> str:
    """Deprecated: use data.sources.baostock_source._baostock_code instead."""
    from data.sources.baostock_source import _baostock_code as _f
    return _f(symbol)


def get_stock_list_baostock():
    """Deprecated: use get_stock_list() with order=["baostock"] instead."""
    from data.sources import get_fetcher
    fetcher = get_fetcher(order=["baostock"])
    return fetcher.get_stock_list()


def _save_results_to_daily(results, stock_list, daily_dir):
    """Deprecated: date-partitioned storage is no longer primary."""
    warnings.warn("_save_results_to_daily is deprecated. Use _save_results_to_stocks.", DeprecationWarning)
    # Forward to stock-partitioned save
    name_map = dict(zip(stock_list['symbol'], stock_list['name']))
    return _save_results_to_stocks(results, name_map)


def migrate_to_daily(source_path=None, daily_dir=None):
    """Deprecated: migration to date-partitioned format is no longer needed."""
    warnings.warn("migrate_to_daily is deprecated. Stock-partitioned is now primary.", DeprecationWarning)
    return 0
