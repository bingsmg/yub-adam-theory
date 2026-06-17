#!/usr/bin/env python3
"""
Multi-date conservative patch: fill missing data for one or more dates.
Usage:
    python scripts/patch_dates.py 2026-06-11 2026-06-12
"""
from __future__ import annotations

import socket
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from loguru import logger

from config.settings import settings

BATCH_SIZE = 50
INTER_STOCK_DELAY = 1.5
INTER_BATCH_DELAY = 5.0

if len(sys.argv) < 2:
    print("Usage: python scripts/patch_dates.py YYYY-MM-DD [YYYY-MM-DD ...]")
    sys.exit(1)

TARGET_DATES = sys.argv[1:]
logger.info(f"=== Conservative patch for: {', '.join(TARGET_DATES)} ===")

# 1. Load stock list
stock_list = pd.read_csv(settings.STOCK_LIST_PATH, dtype={"symbol": str})
name_map = dict(zip(stock_list["symbol"], stock_list["name"]))
logger.info(f"  Stock universe: {len(name_map):,}")

# 2. Find missing for each target date
daily_dir = Path(settings.DAILY_DIR)
df_all = pd.read_parquet(str(daily_dir))
df_all["date"] = pd.to_datetime(df_all["date"])
latest_per_sym = df_all.groupby("symbol")["date"].max()

for target in TARGET_DATES:
    target_dt = pd.Timestamp(target)
    missing = latest_per_sym[latest_per_sym < target_dt]
    logger.info(f"  {target}: {len(missing):,} stocks need update")

# Combined: any stock missing ANY target date gets updated to the LATEST target date
all_missing_syms = set()
for target in TARGET_DATES:
    target_dt = pd.Timestamp(target)
    missing = latest_per_sym[latest_per_sym < target_dt]
    all_missing_syms.update(missing.index)

max_target = max(TARGET_DATES)
logger.info(f"  Total unique symbols to update to {max_target}: {len(all_missing_syms):,}")

if not all_missing_syms:
    logger.info("All stocks up to date for all target dates!")
    sys.exit(0)

# 3. Fetch with baostock, conservative pacing
import baostock as bs

def _code(sym):
    code = str(sym).zfill(6)
    if code.startswith(("60", "68")): return f"sh.{code}"
    elif code.startswith(("00", "30", "002")): return f"sz.{code}"
    elif code.startswith(("8", "4")): return f"bj.{code}"
    return f"sz.{code}"

# Build fetch list: for each missing symbol, fetch from their last date to max_target
fetch_list = []
for sym in sorted(all_missing_syms):
    last_d = latest_per_sym[sym]
    start_str = last_d.strftime("%Y-%m-%d")
    fetch_list.append((sym, start_str))

t0 = time.time()
success = 0
fail = 0
batch_dfs = []

for batch_start in range(0, len(fetch_list), BATCH_SIZE):
    batch = fetch_list[batch_start:batch_start + BATCH_SIZE]

    bs.login()
    socket.setdefaulttimeout(30)

    for i, (sym, start_str) in enumerate(batch):
        if i > 0:
            time.sleep(INTER_STOCK_DELAY)

        name = name_map.get(sym, "")
        baocode = _code(sym)

        for retry in range(3):
            try:
                rs = bs.query_history_k_data_plus(
                    baocode,
                    "date,open,high,low,close,volume,amount",
                    start_date=start_str, end_date=max_target,
                    frequency="d", adjustflag="2",
                )
                data = []
                while (rs.error_code == "0") and rs.next():
                    data.append(rs.get_row_data())

                if data:
                    df_stock = pd.DataFrame(data, columns=["date","open","high","low","close","volume","amount"])
                    for c in ["open","high","low","close","volume","amount"]:
                        df_stock[c] = pd.to_numeric(df_stock[c], errors="coerce")
                    df_stock = df_stock.dropna(subset=["close"])
                    df_stock["symbol"] = sym
                    df_stock["name"] = name
                    batch_dfs.append(df_stock)
                    success += 1
                else:
                    fail += 1
                break

            except OSError:
                if retry < 2:
                    bs.logout()
                    time.sleep(2 ** retry)
                    bs.login()
                    socket.setdefaulttimeout(30)
                else:
                    fail += 1
            except Exception:
                fail += 1
                break

    bs.logout()

    # Save
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

    done = batch_start + len(batch)
    elapsed = time.time() - t0
    rate = done / elapsed if elapsed > 0 else 0
    remain = (len(fetch_list) - done) / rate if rate > 0 else 0
    logger.info(
        f"  {done}/{len(fetch_list)} ({done*100//len(fetch_list)}%) — "
        f"{success} ok, {fail} fail — "
        f"{elapsed/60:.1f}min elapsed, ~{remain/60:.1f}min left"
    )

    if done < len(fetch_list):
        time.sleep(INTER_BATCH_DELAY)

elapsed = time.time() - t0
logger.info(f"Done: {success} ok, {fail} fail in {elapsed/60:.1f}min")
