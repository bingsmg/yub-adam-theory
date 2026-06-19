请使用中文回答

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Adam's Theory A-Share stock recommendation system. Uses a pluggable multi-source data layer (**akshare** primary, **baostock** fallback) to fetch daily K-line data for 5000+ A-share stocks into date-partitioned Parquet files under `output/daily/`. Applies pure Adam's Theory — three visual conditions (breakout, trend change, gap/wide range) requiring >=2 met simultaneously — to identify buy signals for the next trading day. Outputs ranked recommendations with interactive Plotly charts, data-driven reasoning, and structural stop-loss levels.

## Common commands

```bash
# Activate the venv (always needed first)
cd E:/Projects/ClaudeCodeProjects/yd-project && source .venv/Scripts/activate

# Run all tests (18 tests, synthetic data only)
python -m pytest tests/ -v

# ── Daily workflow ──────────────────────────────────────────────

# Step 1: One-time backfill (all 5000+ stocks, 2yr → output/daily/*.parquet)
python scripts/init_backfill.py                       # Full: ~30-60min (parallel, auto-resume)
python scripts/init_backfill.py --limit 100           # Test: 100 stocks, ~30s
python scripts/init_backfill.py --start 2025-01-01    # Shorter history = faster

# Step 2: Daily update + recommendations
python scripts/daily_update.py                        # Fetch new days + analyze + HTML auto-open
python scripts/daily_update.py --no-update            # Skip fetch, analyze only (fastest)
python scripts/daily_update.py --limit 200            # Scan top 200 active stocks
python scripts/daily_update.py --output console       # Console output only (no HTML)
python scripts/daily_update.py --output html          # HTML report only, auto-open browser

# Notebook
jupyter notebook adam_theory_pipeline.ipynb

# Force specific data source
DATA_SOURCE_ORDER='["baostock"]' python scripts/init_backfill.py --limit 50
```

## Architecture

```
akshare (EastMoney, primary)               baostock (own server, fallback)
         \                                   /
          \    data/sources/ (ABC + strategy) 
           \                                /
            ───────────┬───────────────────
                        ▼
consolidated_store.py  ──→  output/daily/YYYY-MM-DD.parquet  (date-partitioned, all stocks, qfq)
        │
        ▼
daily_update.py:  update latest day(s) → filter active top-200 → detect → rank → report
        │
        ▼
detector.py  (3 conditions, require >=2, structural stop)
        │
        ▼
ranking.py → explainer.py → reporting/ (console + HTML with Plotly charts)
```

### Signal gating (pure Adam's Theory — no indicators)

Three conditions checked directly on price/volume data:

| # | Condition | Detection |
|---|-----------|-----------|
| 1 | Breakout (突破) | Close >= highest high of last 20 bars |
| 2 | Trend Change (趋势改变) | Prior downtrend/consolidation → price breaks above recent swing high |
| 3 | Gap/Wide Range (缺口/宽幅) | Gap up >= 0.5% OR today's range >= 1.5x 20-day avg |

**Gate**: >= 2 of 3 conditions must be met. **Stop loss**: lowest low in last 40 bars (structural).

No ADX, no Efficiency Ratio, no indicator gating — pure price action per Wilder's original work.

### Key modules

| Module | Role |
|--------|------|
| `data/sources/` | Pluggable data source layer. `base.py` (ABC), `baostock_source.py`, `akshare_source.py`, `ef_source.py` (stub), `strategy.py` (selection), `parallel.py` (ThreadPoolExecutor batch). Configurable via `DATA_SOURCE_ORDER` and `DATA_SOURCE_STRATEGY` in settings. |
| `data/consolidated_store.py` | Date-partitioned Parquet store. `build_all_stocks_parquet()`, `update_latest_days()`, `filter_active_stocks()`, `get_board()`, `migrate_to_daily()`. Now delegates fetching to `data/sources/` — uses parallel fetch by default. |
| `indicators/adams_theory.py` | Core: `compute_center_symmetry_projection()`, `detect_breakout()`, `detect_trend_change()`, `detect_gap_or_wide_range()`, `check_buy_signal()`, `find_structural_stop()` |
| `signals/detector.py` | `detect_signal(df, symbol)` — runs all 3 conditions, requires >=2, builds AdamSignal |
| `signals/scorer.py` | `compute_quality_score()` (0-100), `rank_signals()` |
| `recommendation/ranking.py` | `select_top_recommendations()` — quality^2 / risk ranking + "one question" rule |
| `recommendation/explainer.py` | `build_explanation()` — full Chinese-language reasoning per signal; `brief_reason()` — one-line summary |
| `reporting/console.py` | Rich table output showing met/missing conditions, stop%, risk colors |
| `reporting/html_report.py` | Enhanced HTML with 5 Plotly interactive charts (risk, quality, volume, projection, clue pie), summary dashboard, detailed cards, auto-open browser |
| `scripts/init_backfill.py` | One-time: download all stocks to `output/daily/*.parquet` |
| `scripts/daily_update.py` | Daily: update latest day(s) + pre-screen + detect + rank + explain + report |

### Board permission filtering

Stocks can be filtered by trading board via settings in `config/settings.py`:

| Setting | Board | Symbol Prefix | Default |
|---------|-------|--------------|---------|
| `ALLOW_CHINEXT` | 创业板 ChiNext | 300, 301 | `True` |
| `ALLOW_STAR_MARKET` | 科创板 STAR | 688, 689 | `True` |
| `ALLOW_BSE` | 北交所 BSE | 8xxxxx, 4xxxxx | `False` |

Filtering happens in `filter_active_stocks()` — the pre-screen gate, before any detection computation. Use `get_board(symbol)` to classify any 6-digit code: returns `'main'`, `'chinext'`, `'star'`, or `'bse'`.

### Price adjustment

**Always use `qfq` (前复权)`** — historical prices adjusted backward so today's price IS the real market price. baostock uses `adjustflag='2'`.

## Data storage

- `output/daily/YYYY-MM-DD.parquet` — **Primary**: date-partitioned files, one per trading day (~486 files, ~140 MB total). Each contains all stocks' data for that date.
- `output/all_stocks.parquet` — Legacy consolidated file (kept as backup after migration).
- `output/stock_list.csv` — Stock universe cache (auto-generated by daily_update).
- `output/results/` — Daily recommendation CSVs.
- `output/reports/` — HTML reports with Plotly charts.

### Why date-partitioned?

- Daily update writes **only new date files** — no full-file read-merge-rewrite.
- Each file is independent — no data loss risk on interruption.
- `load_all_stocks()` reads the entire `output/daily/` directory via `pd.read_parquet(dir)`.
- Migrate from legacy single file: `migrate_to_daily()` splits `all_stocks.parquet` by date.

### Performance notes

- **Multi-source parallel fetch**: `FETCH_MAX_WORKERS=8` (configurable) threads query simultaneously, ~30-60 min for full backfill (was ~2h sequential baostock).
- **akshare** is the default primary (~0.5s/stock via EastMoney), **baostock** is the fallback (~1.5s/stock via own server).
- **efinance** supports native batch query (pass a list of codes to one call) — stub available, install with `pip install efinance`.
- Tune `FETCH_DELAY_SECONDS` to avoid rate limiting (akshare/efinance scrape EastMoney which may throttle; baostock has no limit).
- For daily recommendations, `--no-update` skips API calls entirely — runs in ~5 seconds.
- Override source at runtime: `DATA_SOURCE_ORDER='["baostock"]' python scripts/daily_update.py`

## Testing conventions

- Tests use **synthetic OHLCV DataFrames** from `tests/conftest.py`. Never call real APIs.
- All fixtures: `[open, high, low, close, volume]` columns, DatetimeIndex.
- 18 tests: projection, breakout, trend change, gap/wide range, combined detection (>=2 gate), structural stop, detector integration.

## Known issues

- **akshare EastMoney rate limiting**: akshare scrapes EastMoney which may throttle after ~800-1500 requests. Use `FETCH_DELAY_SECONDS=1.0` or higher to avoid. Switch to baostock with `DATA_SOURCE_ORDER='["baostock"]'` if blocked.
- **baostock connection instability**: baostock sessions can hang after ~10-15 minutes. Mitigated by session refresh every 200 stocks + 30s socket timeout in `BaostockDataSource`. Use `--no-update` to skip fetch entirely.
- **baostock BSE stocks**: Beijing Stock Exchange stocks (8xxxxx, 4xxxxx) often return empty data from baostock. Excluded by default (`ALLOW_BSE=False`).
- **New IPOs**: Stocks listed < 30 trading days ago are filtered out (minimum 30 bars required). They don't cause errors but are skipped.
- **2026-06-12 data**: Only available after market close (after 3 PM China time). 2026-06-11 is the latest complete trading day.
- **HTML report date filenames**: Use `strftime('%Y-%m-%d')` not `isoformat()` — colons are invalid in Windows filenames.
