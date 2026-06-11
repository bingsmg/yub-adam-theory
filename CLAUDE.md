# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project overview

Adam's Theory A-Share stock recommendation system. Uses **baostock** (primary, no rate limits) and akshare (fallback) to fetch daily K-line data for 5000+ A-share stocks. Applies pure Adam's Theory — three visual conditions (breakout, trend change, gap/wide range) requiring >=2 met simultaneously — to identify buy signals for the next trading day. Outputs ranked recommendations with data-driven reasoning and structural stop-loss levels.

## Common commands

```bash
# Activate the venv (always needed first)
cd E:/Projects/ClaudeCodeProjects/yd-project && source .venv/Scripts/activate

# Run all tests
python -m pytest tests/ -v

# Run a single test
python -m pytest tests/test_adams_theory.py -v
python -m pytest tests/test_adams_theory.py::TestBreakout -v

# ── Daily workflow ──────────────────────────────────────────────

# Step 1: One-time backfill (all 5000+ stocks, 2yr → output/all_stocks.parquet)
python scripts/init_backfill.py                       # Full: ~2h (sequential, auto-resume)
python scripts/init_backfill.py --limit 100           # Test: 100 stocks, ~2 min
python scripts/init_backfill.py --start 2025-01-01    # Shorter history = faster

# Step 2: Daily update + recommendations
python scripts/daily_update.py                        # Fetch new days + analyze
python scripts/daily_update.py --no-update            # Skip fetch, analyze only
python scripts/daily_update.py --limit 200            # Scan top 200 active stocks
python scripts/daily_update.py --output console       # Console output only

# ── Legacy / fallback ──────────────────────────────────────────
python main.py --cache-only --limit 50                 # Use per-stock parquet cache
```

## Architecture

```
baostock API (no rate limits)
        │
        ▼
consolidated_store.py  ──→  output/all_stocks.parquet  (single file, all stocks)
        │
        ▼
daily_update.py:  update latest day → filter active top-200 → detect → rank → report
        │
        ▼
detector.py  (3 conditions, require >=2, structural stop)
        │
        ▼
ranking.py → explainer.py → reporting/ (console + HTML)
```

### Data flow

1. **Backfill**: `init_backfill.py` calls `consolidated_store.build_all_stocks_parquet()` → single `all_stocks.parquet` with columns `[symbol, name, date, open, high, low, close, volume, amount]`
2. **Daily update**: `daily_update.py` calls `update_latest_days()` → appends only new trading days, then filters top-200 active stocks, runs detection, outputs recommendations
3. **Detection**: Pure Adam's Theory — no ADX, no ER, no indicator gating. Three conditions all checked directly on price/volume data:

| # | Condition | Detection |
|---|-----------|-----------|
| 1 | Breakout (突破) | Close >= highest high of last 20 bars |
| 2 | Trend Change (趋势改变) | Prior downtrend/consolidation → price breaks above recent swing high after bouncing from swing low |
| 3 | Gap/Wide Range (缺口/宽幅) | Gap up >= 0.5% OR today's range >= 1.5x 20-day avg |

**Gate**: >= 2 of 3 conditions must be met. **Stop loss**: lowest low in last 40 bars (structural support).

### Key modules

| Module | Role |
|--------|------|
| `data/consolidated_store.py` | Single-file Parquet store. `build_all_stocks_parquet()`, `update_latest_days()`, `filter_active_stocks()` |
| `data/fetcher.py` | akshare wrapper — use `qfq` (前复权) for real market prices. Fallback only. |
| `data/store.py` | Per-stock Parquet files — legacy, used by `main.py` fallback path. |
| `indicators/adams_theory.py` | Core: `compute_center_symmetry_projection()`, `detect_breakout()`, `detect_trend_change()`, `detect_gap_or_wide_range()`, `check_buy_signal()`, `find_structural_stop()` |
| `indicators/market_regime.py` | ADX, ATR, Efficiency Ratio — computed but **not used in gating**. |
| `signals/detector.py` | `detect_signal(df, symbol)` — runs 3 conditions, requires >=2, builds AdamSignal |
| `recommendation/pipeline.py` | `RecommendationPipeline` — legacy orchestrator via per-stock parquet |
| `reporting/console.py` | Rich table output showing met/missing conditions per stock |
| `reporting/html_report.py` | Jinja2 HTML report |

### Price adjustment

**Always use `qfq` (前复权)** — historical prices adjusted backward so today's price IS the real market price. This is what traders see on charts. baostock uses `adjustflag='2'` for qfq.

## Data storage

- `output/all_stocks.parquet` — **Primary**: single file with all stocks' daily data (2 years)
- `output/stock_list.csv` — Stock universe cache
- `output/parquet/` — Legacy per-stock files (from `main.py` fallback)
- `output/results/` — Daily recommendation CSVs
- `output/reports/` — HTML reports

## Testing conventions

- Tests use **synthetic OHLCV DataFrames** from `tests/conftest.py`. Never call real APIs in tests.
- All fixtures produce DataFrames with columns `[open, high, low, close, volume]`.
- Signal tests assert on signal presence/absence, clue types, clue count (>=2), risk score range — not exact numeric values.
- 18 tests: projection, 3 conditions, gate logic (>=2 of 3), structural stop, detector integration.

## Known issues

- **akshare rate limiting**: East Money blocks concurrent requests. Use baostock for bulk data. akshare only as fallback.
- **baostock requires login**: `bs.login()` / `bs.logout()` per session. No rate limits. Single session ~1.5s/stock sequential; concurrent logins from same IP cause hangs. Progressive save every 500 stocks — resume on restart.
- **qfq prices are correct**: The prices shown (~¥12 for 平安银行) are the real market prices traders see.
