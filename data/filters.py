"""
A 股业务过滤与分类。

板块分类、股票列表获取、过期检测，
以及活跃股票预筛选 —— 所有操作独立于存储 I/O。
"""

from __future__ import annotations

import os
from datetime import datetime

import pandas as pd
from loguru import logger

from config.settings import settings


def get_board(symbol: str) -> str:
    """根据 6 位 A 股代码判断所属交易板块。

    返回以下之一：'main'（主板）、'chinext'（创业板）、'star'（科创板）、'bse'（北交所）
    """
    code = str(symbol).zfill(6)
    if code.startswith(('300', '301')):
        return 'chinext'
    elif code.startswith(('688', '689')):
        return 'star'
    elif code.startswith(('8', '4')):
        return 'bse'
    return 'main'


def get_stock_list(fetcher=None) -> pd.DataFrame:
    """通过已配置的数据源获取完整的 A 股股票列表。

    参数:
        fetcher: 可选的 DataSource 实例。若为 None，则使用 get_fetcher()
                 （从配置中读取 DATA_SOURCE_ORDER）。

    返回包含 symbol、name、code 列的 DataFrame
    """
    if fetcher is None:
        from data.sources import get_fetcher
        fetcher = get_fetcher()
    return fetcher.get_stock_list()


def get_stale_stocks(
    stock_list: pd.DataFrame,
    stocks_dir: str | None = None,
    reference_date: str | None = None,
) -> dict[str, pd.Timestamp | None]:
    """查找最后数据日期早于参考日期的股票。

    仅从每个股票文件中读取 'date' 列以查找其最大日期。
    比加载全部数据快得多。

    返回 symbol -> last_date 的映射字典（文件不存在时为 None）。
    """
    if stocks_dir is None:
        stocks_dir = str(settings.STOCKS_DIR)
    if reference_date is None:
        reference_date = datetime.now().strftime('%Y-%m-%d')

    from data.store import _stock_file_path

    ref_dt = pd.Timestamp(reference_date)
    stale: dict[str, pd.Timestamp | None] = {}

    for _, row in stock_list.iterrows():
        sym = row['symbol']
        path = _stock_file_path(sym, stocks_dir)
        if not os.path.exists(path):
            stale[sym] = None
            continue
        try:
            dates = pd.read_parquet(path, columns=['date'])
            last_date = dates['date'].max()
            if pd.isna(last_date) or last_date < ref_dt:
                stale[sym] = last_date
        except Exception:
            stale[sym] = None

    return stale


def filter_active_stocks(
    master: pd.DataFrame | None = None,
    top_n: int | None = None,
) -> list[dict]:
    """
    筛选出最活跃的股票进行分析。

    活跃度 = 最近日期上（成交量 × 收盘价）最高。

    若 master 为 None，则使用 load_latest_snapshot()，
    该方法仅读取每只股票文件的最后一行 —— 比加载全部数据快得多。

    返回字典列表：[{symbol, name, close, ...}]
    """
    if top_n is None:
        top_n = settings.MAX_STOCKS_TO_ANALYZE

    from data.store import load_latest_snapshot

    if master is not None:
        latest_date = master['date'].max()
        latest = master[master['date'] == latest_date].copy()
    else:
        latest = load_latest_snapshot()

    if latest.empty:
        return []

    # 排除 ST 股
    if 'name' in latest.columns:
        latest = latest[~latest['name'].str.contains('ST|退', na=False)]

    # 排除低价股（仙股）
    latest = latest[latest['close'] >= settings.MIN_PRICE]
    latest = latest[latest['volume'] > 0]

    # 排除无交易权限的板块
    if not settings.ALLOW_CHINEXT:
        latest = latest[~latest['symbol'].astype(str).str.match(r'^30[01]')]
    if not settings.ALLOW_STAR_MARKET:
        latest = latest[~latest['symbol'].astype(str).str.match(r'^68[89]')]
    if not settings.ALLOW_BSE:
        latest = latest[~latest['symbol'].astype(str).str.match(r'^[84]')]

    # 活跃度评分
    latest['_score'] = latest['volume'].fillna(0) * latest['close'].fillna(0)
    latest = latest.sort_values('_score', ascending=False)
    latest = latest.head(top_n)

    return latest[['symbol', 'name', 'close']].to_dict('records')
