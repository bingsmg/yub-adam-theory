#!/usr/bin/env python3
"""
Conservative data patch: fill missing 06-11 data with small batches,
long delays, and frequent session refresh to avoid server rejection.
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

TARGET_DATE = "2026-06-11"
BATCH_SIZE = 50          # Small batch to avoid overwhelming server
INTER_STOCK_DELAY = 1.5  # Seconds between stocks
INTER_BATCH_DELAY = 5.0  # Seconds between batches

logger.info(f"=== Conservative patch for {TARGET_DATE} ===")

# 1. Load cached stock list
stock_list_path = Path(settings.STOCK_LIST_PATH)
stock_list = pd.read_csv(stock_list_path, dtype={"symbol": str})
name_map = dict(zip(stock_list["symbol"], stock_list["name"]))
logger.info(f"  Stock universe: {len(name_map):,}")

# 2. Find missing
daily_dir = Path(settings.DAILY_DIR)
df_all = pd.read_parquet(str(daily_dir))
df_all["date"] = pd.to_datetime(df_all["date"])
latest_per_sym = df_all.groupby("symbol")["date"].max()
needs_update = latest_per_sym[latest_per_sym < pd.Timestamp(TARGET_DATE)]
logger.info(f"  Need update: {len(needs_update):,} stocks")

if needs_update.empty:
    logger.info("All stocks up to date!")
    sys.exit(0)

# 3. Fetch with baostock, conservative pacing
import baostock as bs

def _code(sym):
    code = str(sym).zfill(6)
    if code.startswith(("60", "68")): return f"sh.{code}"
    elif code.startswith(("00", "30", "002")): return f"sz.{code}"
    elif code.startswith(("8", "4")): return f"bj.{code}"
    return f"sz.{code}"

t0 = time.time()
success = 0
fail = 0
batch_dfs = []
items = list(needs_update.items())

for batch_start in range(0, len(items), BATCH_SIZE):
    batch = items[batch_start:batch_start + BATCH_SIZE]

    # Fresh session for each batch
    bs.login()
    socket.setdefaulttimeout(30)

    for i, (sym, last_d) in enumerate(batch):
        if i > 0:
            time.sleep(INTER_STOCK_DELAY)

        name = name_map.get(sym, "")
        start_str = last_d.strftime("%Y-%m-%d")
        baocode = _code(sym)

        for retry in range(3):
            try:
                rs = bs.query_history_k_data_plus(
                    baocode,
                    "date,open,high,low,close,volume,amount",
                    start_date=start_str, end_date=TARGET_DATE,
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
                break  # Success or empty data — move on

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

    # Save checkpoint
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
    remain = (len(items) - done) / rate if rate > 0 else 0
    logger.info(
        f"  {done}/{len(items)} ({done*100//len(items)}%) — "
        f"{success} ok, {fail} fail — "
        f"{elapsed/60:.1f}min elapsed, ~{remain/60:.1f}min left"
    )

    # Inter-batch pause
    if done < len(items):
        time.sleep(INTER_BATCH_DELAY)

elapsed = time.time() - t0
logger.info(f"Done: {success} ok, {fail} fail in {elapsed/60:.1f}min")
