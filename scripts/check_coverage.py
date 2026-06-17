#!/usr/bin/env python3
"""Quick check: data coverage — are all stocks updated to latest trading day?"""
from pathlib import Path
import pandas as pd

daily_dir = Path("output/daily")
files = sorted(daily_dir.glob("*.parquet"))

# Latest 5 date files
print("=== Latest 5 date files ===")
for f in files[-5:]:
    df = pd.read_parquet(f)
    print(f"  {f.stem}: {len(df):,} stocks")

# Latest file details
latest_file = files[-1]
df_latest = pd.read_parquet(latest_file)
print(f"\n=== Latest date: {latest_file.stem} ===")
print(f"  Total stocks: {len(df_latest):,}")
print(f"  Price range: {df_latest['close'].min():.2f} ~ {df_latest['close'].max():.2f}")
print(f"  Zero volume: {(df_latest['volume'] == 0).sum()}")
print(f"  Null close: {df_latest['close'].isna().sum()}")

# Per-date coverage
print("\n=== Last 5 days per-date counts ===")
all_syms = set()
for f in files[-5:]:
    df = pd.read_parquet(f)
    syms = set(df["symbol"].unique())
    all_syms.update(syms)
    print(f"  {f.stem}: {len(syms):,} stocks")
print(f"  Unique across all 5: {len(all_syms):,}")

# Full range
print(f"\n=== Full data range ===")
print(f"  First: {files[0].stem}, Last: {files[-1].stem}")
print(f"  Total date files: {len(files)}")

# Load all and check per-symbol latest date
print("\n=== Per-symbol latest date ===")
df_all = pd.read_parquet(daily_dir)
df_all["date"] = pd.to_datetime(df_all["date"])
latest_per_sym = df_all.groupby("symbol")["date"].max()
print(f"  Total unique symbols: {len(latest_per_sym):,}")

date_counts = latest_per_sym.value_counts().sort_index()
print(f"  Latest dates (bottom 10):")
for d, c in date_counts.tail(10).items():
    flag = " <<<" if d != pd.Timestamp("2026-06-11") else ""
    print(f"    {d.date()}: {c:,} stocks{flag}")

latest_date = pd.Timestamp("2026-06-11")
not_latest = (latest_per_sym < latest_date).sum()
print(f"\n  NOT updated to 2026-06-11: {not_latest:,} / {len(latest_per_sym):,}")

if not_latest > 0:
    stale = latest_per_sym[latest_per_sym < latest_date].sort_values()
    print(f"\n  Stale stocks (oldest first):")
    for sym, d in stale.head(20).items():
        rows = df_all[df_all["symbol"] == sym]
        name = rows["name"].iloc[0] if len(rows) > 0 else "?"
        print(f"    {sym} ({name}): last = {d.date()}")

# Filter: how many pass the pre-screen?
print(f"\n=== Pre-screen filter results (latest date) ===")
ld = df_all[df_all["date"] == latest_date].copy()
print(f"  All stocks on {latest_date.date()}: {len(ld):,}")

# Apply same filters as filter_active_stocks
if "name" in ld.columns:
    ld = ld[~ld["name"].str.contains("ST|退", na=False)]
ld = ld[ld["close"] >= 3.0]
ld = ld[ld["volume"] > 0]
ld = ld[~ld["symbol"].astype(str).str.match(r"^[84]")]  # Exclude BSE
print(f"  After filters (no ST, price>=3, vol>0, no BSE): {len(ld):,}")
print(f"  Activity range: {ld['volume'].min()*ld['close'].min():.0f} ~ "
      f"{ld['volume'].max()*ld['close'].max():.0f}")
