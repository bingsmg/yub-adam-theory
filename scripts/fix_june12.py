"""Re-fetch only 2026-06-12 data (corrupted) using baostock."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import os
import time
from datetime import date

os.environ['DATA_SOURCE_ORDER'] = '["baostock"]'

from data.sources import get_fetcher
from data.sources.parallel import fetch_batch_parallel

DAILY_DIR = Path("output/daily")


def main():
    # Load stock list and name map
    df_all = pd.read_parquet(DAILY_DIR)
    stock_info = df_all[['symbol', 'name']].drop_duplicates()
    stocks = stock_info['symbol'].tolist()
    name_map = dict(zip(stock_info['symbol'], stock_info['name']))
    print(f"Stocks: {len(stocks)}")

    fetcher = get_fetcher()
    print(f"Source: {fetcher.name}")

    # Fetch June 12 only
    start_s = "2026-06-12"
    end_s = "2026-06-13"

    def _fetch_one(sym, s, e):
        df = fetcher.fetch_daily_kline(sym, s, e)
        if df is not None and not df.empty:
            if 'symbol' not in df.columns:
                df['symbol'] = sym
            if 'name' not in df.columns:
                df['name'] = name_map.get(sym, '')
        return df

    t0 = time.time()
    results = fetch_batch_parallel(
        fetch_fn=_fetch_one,
        symbols=stocks,
        start_date=start_s,
        end_date=end_s,
        max_workers=8,
        delay_per_worker=0.5,
    )
    elapsed = time.time() - t0
    print(f"Fetched {len(results)} stocks in {elapsed:.0f}s")

    # Save results
    rows = []
    for sym, df in results.items():
        if df is not None and not df.empty:
            if 'symbol' not in df.columns:
                df['symbol'] = sym
            if 'name' not in df.columns:
                df['name'] = name_map.get(sym, '')
            rows.append(df)

    if rows:
        new_data = pd.concat(rows, ignore_index=True)
        dates_found = sorted(new_data['date'].unique())
        print(f"New data: {len(new_data)} rows, dates: {dates_found}")

        for d in dates_found:
            day_data = new_data[new_data['date'] == d]
            d_str = pd.to_datetime(d).strftime('%Y-%m-%d')
            out_path = DAILY_DIR / f"{d_str}.parquet"
            day_data.to_parquet(out_path, index=False)
            print(f"  Saved {out_path.name}: {len(day_data)} rows")
    else:
        print("ERROR: No data fetched!")
        return

    # Sanity check
    print("\n--- Jump check ---")
    df = pd.read_parquet(DAILY_DIR)
    for d in sorted(df['date'].unique())[-5:]:
        day = df[df['date'] == d]
        prev_date = df[df['date'] < d]['date'].max()
        prev_day = df[df['date'] == prev_date]
        merged = day[['symbol', 'close']].merge(
            prev_day[['symbol', 'close']], on='symbol', suffixes=('', '_prev')
        )
        merged['jump'] = abs(merged['close'] / merged['close_prev'] - 1)
        bad = (merged['jump'] > 0.3).sum()
        print(f"  {d.date()}: {len(day)} stocks, {bad} with >30% jump")

    # Compare a known stock
    print("\n--- Spot check 601665 ---")
    s = df[df['symbol'] == '601665'].sort_values('date')
    for _, row in s.tail(5).iterrows():
        print(f"  {row['date'].date()} O={row['open']:.2f} H={row['high']:.2f} L={row['low']:.2f} C={row['close']:.2f}")


if __name__ == "__main__":
    main()
