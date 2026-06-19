#!/usr/bin/env python3
"""Quick check: data coverage — are all stocks updated to latest trading day?

Works with stock-partitioned files (output/stocks/*.parquet) primarily,
falls back to date-partitioned files (output/daily/*.parquet) if needed.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from data.consolidated_store import (
    load_latest_snapshot,
    load_all_stocks,
    get_latest_date,
    get_stale_stocks,
)
from config.settings import settings


def main():
    stocks_dir = settings.STOCKS_DIR

    # 1. Overview
    print("=== Stock-partitioned files ===")
    if stocks_dir.exists():
        stock_files = sorted(stocks_dir.glob("*.parquet"))
        print(f"  Directory: {stocks_dir}")
        print(f"  Total files: {len(stock_files)}")
        if stock_files:
            total_size = sum(f.stat().st_size for f in stock_files)
            print(f"  Total size: {total_size/1e6:.1f} MB")
            print(f"  Avg per stock: {total_size/len(stock_files)/1e3:.1f} KB")
    else:
        print(f"  {stocks_dir} does not exist yet. Run migrate_to_stock_files.py first.")
        # Fallback: try daily dir
        daily_dir = settings.DAILY_DIR
        if daily_dir.exists():
            files = sorted(daily_dir.glob("*.parquet"))
            print(f"\n=== Legacy date-partitioned files ({daily_dir}) ===")
            print(f"  Total files: {len(files)}")
            if files:
                total_size = sum(f.stat().st_size for f in files)
                print(f"  Total size: {total_size/1e6:.1f} MB")

    # 2. Latest snapshot stats
    print("\n=== Latest snapshot ===")
    snapshot = load_latest_snapshot()
    if not snapshot.empty:
        latest_date = snapshot['date'].max()
        print(f"  Latest date: {latest_date.date()}")
        print(f"  Stocks in snapshot: {len(snapshot):,}")
        print(f"  Price range: {snapshot['close'].min():.2f} ~ {snapshot['close'].max():.2f}")
        print(f"  Zero volume: {(snapshot['volume'] == 0).sum():,}")
        print(f"  Null close: {snapshot['close'].isna().sum():,}")
        print(f"  Names available: {snapshot['name'].notna().sum():,}")
    else:
        print("  NO DATA")

    # 3. Per-stock latest date check
    print("\n=== Per-stock staleness ===")
    try:
        df_all = load_all_stocks()
        if not df_all.empty:
            latest_per_sym = df_all.groupby('symbol')['date'].max()
            date_counts = latest_per_sym.value_counts().sort_index()
            print(f"  Total unique symbols: {len(latest_per_sym):,}")
            print(f"  Latest dates (last 10):")
            for d, c in date_counts.tail(10).items():
                print(f"    {d.date()}: {c:,} stocks")

            # Show oldest 10
            print(f"  Oldest dates (first 10):")
            for d, c in date_counts.head(10).items():
                print(f"    {d.date()}: {c:,} stocks")
    except Exception as e:
        print(f"  Error: {e}")

    # 4. Filter simulation
    print("\n=== Pre-screen filter results (latest date) ===")
    if not snapshot.empty:
        latest = snapshot.copy()
        total_before = len(latest)

        if 'name' in latest.columns:
            latest = latest[~latest['name'].str.contains('ST|退', na=False)]
        latest = latest[latest['close'] >= 3.0]
        latest = latest[latest['volume'] > 0]
        latest = latest[~latest['symbol'].astype(str).str.match(r'^[84]')]

        after = len(latest)
        print(f"  All stocks on latest date: {total_before:,}")
        print(f"  After filters (no ST, price>=3, vol>0, no BSE): {after:,}")
        if not latest.empty:
            latest['_score'] = latest['volume'] * latest['close']
            print(f"  Activity range: {latest['_score'].min():.0f} ~ {latest['_score'].max():.0f}")

    # 5. Top 5 most active by volume*close
    print("\n=== Top 5 most active stocks ===")
    try:
        if not snapshot.empty:
            snap = snapshot.copy()
            snap['_score'] = snap['volume'].fillna(0) * snap['close'].fillna(0)
            top5 = snap.nlargest(5, '_score')
            for _, row in top5.iterrows():
                print(f"  {row['symbol']} ({row.get('name', '?')}): "
                      f"close={row['close']:.2f}, vol={row['volume']:.0f}, "
                      f"score={row['_score']:.0f}")
    except Exception:
        pass


if __name__ == "__main__":
    main()
