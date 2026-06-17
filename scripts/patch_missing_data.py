#!/usr/bin/env python3
"""
Targeted patch: fill 2026-06-11 data for stocks missing it.
Uses cached stock list (output/stock_list.csv) to avoid the slow
baostock query_stock_basic() call. Fetches sequentially to avoid
rate limiting issues.
"""
from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from loguru import logger

from config.settings import settings
from data.sources.akshare_source import AkshareDataSource

# Config
TARGET_DATE = "2026-06-11"

logger.info(f"=== Patch missing data for {TARGET_DATE} ===")

# 1. Load cached stock list (fast — CSV, no API call)
stock_list_path = Path(settings.STOCK_LIST_PATH)
if not stock_list_path.exists():
    # Fallback: extract symbols from parquet
    logger.warning("No stock_list.csv, extracting from parquet...")
    df_all = pd.read_parquet(str(settings.DAILY_DIR))
    name_map = df_all[["symbol", "name"]].drop_duplicates(subset=["symbol"])
    name_map = name_map.set_index("symbol")["name"].to_dict()
else:
    stock_list = pd.read_csv(stock_list_path, dtype={"symbol": str})
    name_map = dict(zip(stock_list["symbol"], stock_list["name"]))
logger.info(f"  Stock universe: {len(name_map):,} stocks")

# 2. Load all data, find missing
daily_dir = Path(settings.DAILY_DIR)
df_all = pd.read_parquet(str(daily_dir))
df_all["date"] = pd.to_datetime(df_all["date"])

latest_per_sym = df_all.groupby("symbol")["date"].max()
target_dt = pd.Timestamp(TARGET_DATE)

needs_update = latest_per_sym[latest_per_sym < target_dt]
logger.info(f"  Need update: {len(needs_update):,} stocks missing {TARGET_DATE}")

if needs_update.empty:
    logger.info("All stocks already have data for {TARGET_DATE}!")
    sys.exit(0)

# 3. Fetch — sequential baostock (stable, no rate limit)
fetcher = AkshareDataSource(max_retries=2, retry_delays=(3.0, 6.0))

t0 = time.time()
success = 0
fail = 0
batch_dfs = []

for i, (sym, last_d) in enumerate(needs_update.items()):
    name = name_map.get(sym, "")
    start_str = last_d.strftime("%Y-%m-%d")

    # Conservative delay for akshare (EastMoney rate limit ~3 req/s)
    if i > 0:
        time.sleep(2.0)

    df = fetcher.fetch_daily_kline(sym, start_date=start_str, end_date=TARGET_DATE)

    if df is not None and not df.empty and len(df) >= 30:
        if "symbol" not in df.columns:
            df["symbol"] = sym
        if "name" not in df.columns:
            df["name"] = name
        batch_dfs.append(df)
        success += 1
    else:
        fail += 1

    # Progress + checkpoint every 100 (faster feedback)
    done = i + 1
    if done % 100 == 0 or done == len(needs_update):
        elapsed = time.time() - t0
        rate = done / elapsed if elapsed > 0 else 0
        remain = (len(needs_update) - done) / rate if rate > 0 else 0
        logger.info(
            f"  {done}/{len(needs_update)} ({done*100//len(needs_update)}%) — "
            f"{success} ok, {fail} fail — "
            f"{elapsed/60:.1f}min elapsed, ~{remain/60:.1f}min left"
        )

        # Progressive save
        if batch_dfs:
            new_data = pd.concat(batch_dfs, ignore_index=True)
            new_data["date"] = pd.to_datetime(new_data["date"])
            for date_val, group in new_data.groupby("date"):
                date_str = pd.Timestamp(date_val).strftime("%Y-%m-%d")
                daily_path = daily_dir / f"{date_str}.parquet"
                if daily_path.exists():
                    existing = pd.read_parquet(daily_path)
                    group = pd.concat([existing, group], ignore_index=True)
                    group = group.drop_duplicates(subset=["symbol"], keep="last")
                group.to_parquet(daily_path, index=False)
            batch_dfs = []

elapsed = time.time() - t0
logger.info(f"Done: {success} ok, {fail} fail in {elapsed/60:.1f}min")
